"""Exercise terminal delivery, restart recovery and reply visibility without model turns."""
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cli.api import ApiError
from cli.chat import Chat, message_text, terminal_text
from cli.main import main


def user(identity='sent', request=None):
    return {'id': identity, 'account_user_id': 'human', 'content': {'text': 'Hello'}, 'request_id': request}


def reply(identity='reply'):
    return {'id': identity, 'account_user_id': 'calpico-member-pocket', 'role': 'user',
            'content': {'text': '[red]Hi\x1b there'}}


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = {'display_name': 'Pocket', 'messaging_room_id': 'room', 'is_paused': False}
        self.page = {'items': [user('old')]}
        self.posts = []
        self.failure = None
        self.client = Mock()
        self.client.path.side_effect = lambda dot: '/tbo/' + dot
        self.client.request.side_effect = self.request
        self.chat = Chat(self.client, 'pocket', Path(self.temp.name))

    def request(self, method, path, **kwargs):
        if path == '/tbo/pocket':
            return self.profile
        if method == 'GET':
            return self.page
        self.posts.append(kwargs['body'])
        if self.failure:
            raise self.failure
        # The recovery journal must exist before the network write.
        self.assertTrue(self.chat.state_path.exists())
        return {'id': 'sent'}

    def test_send_once_and_print_reply_even_when_dot_role_is_user(self):
        self.chat.send('Hello')
        body = self.posts[0]
        self.assertEqual(body['request_id'], body['idempotency_token'])
        self.assertEqual(body['content'], {'text': 'Hello', 'attachments': []})
        self.page = {'items': [reply(), user(), user('old')]}
        self.assertTrue(self.chat.wait(1, 1))
        self.assertEqual(len(self.posts), 1)
        self.assertFalse(self.chat.state_path.exists())

    def test_unknown_send_survives_restart_and_reconciles_without_retry(self):
        self.failure = ApiError('Network failure')
        with self.assertRaises(ApiError):
            self.chat.send('Hello')
        pending_id = self.posts[0]['request_id']
        recovered = Chat(self.client, 'pocket', Path(self.temp.name))
        self.page = {'items': [reply(), user(request=pending_id), user('old')]}
        self.assertTrue(recovered.refresh())
        self.assertEqual(len(self.posts), 1)
        self.assertIsNone(recovered.pending)

    def test_timeout_blocks_duplicate_send_and_preserves_pending(self):
        self.chat.send('Hello')
        with patch('cli.chat.time.monotonic', side_effect=[0, 2]):
            self.assertFalse(self.chat.wait(1, 1))
        with self.assertRaisesRegex(ApiError, 'still pending'):
            self.chat.send('Again')
        self.assertEqual(len(self.posts), 1)
        self.assertTrue(self.chat.state_path.exists())

    def test_paused_dot_cannot_send_or_resume(self):
        self.profile['is_paused'] = True
        with self.assertRaisesRegex(ApiError, 'paused'):
            self.chat.send('Hello')
        self.assertEqual(self.posts, [])
        self.assertFalse(self.chat.state_path.exists())

    def test_fifty_thousand_character_message_is_sent_intact(self):
        text = '日' * 50_000
        self.chat.send(text)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0]['content']['text'], text)

    def test_message_above_fifty_thousand_characters_is_rejected_before_post(self):
        with self.assertRaisesRegex(ApiError, '50,000'):
            self.chat.send('x' * 50_001)
        self.assertEqual(self.posts, [])
        self.assertIsNone(self.chat.pending)
        self.assertFalse(self.chat.state_path.exists())

    @patch('cli.chat.console.print')
    def test_status_reads_runtime_and_tasks_without_sending_or_clearing_pending(self, output):
        self.chat.pending = {'request_id': 'pending', 'message_id': 'accepted', 'baseline': []}
        self.client.request.side_effect = [
            {'is_paused': True, 'status': 'active', 'last_check_in_at': '2026-10-24T21:11:30Z'},
            {'data': [{'title': '[red]Research', 'status': 'running'}]},
        ]
        self.chat.show_status()
        panel = output.call_args.args[0].renderable.plain
        self.assertIn('Paused', panel)
        self.assertIn('Accepted', panel)
        self.assertIn('[red]Research · running', panel)
        self.assertEqual(self.chat.pending['message_id'], 'accepted')
        self.assertTrue(all(call.args[0] == 'GET' for call in self.client.request.call_args_list[-2:]))

    @patch('cli.chat.console.print')
    def test_status_keeps_runtime_visible_when_task_endpoint_is_unavailable(self, output):
        self.client.request.side_effect = [self.profile, ApiError('Unavailable', status=404)]
        self.chat.show_status()
        panel = output.call_args.args[0].renderable.plain
        self.assertIn('Not paused', panel)
        self.assertIn('Task activity unavailable', panel)

    @patch('cli.chat.console.print')
    def test_accepted_message_is_not_echoed_back_as_another_turn(self, output):
        self.chat.send('Hello')
        self.chat.display([user()])
        self.chat.display([user()])
        output.assert_not_called()
        self.assertEqual(self.chat.rendered['sent'], 'Hello')

    @patch('cli.chat.console.print')
    def test_uncertain_delivery_echo_is_identified_by_request_id(self, output):
        self.failure = ApiError('Network failure')
        with self.assertRaises(ApiError):
            self.chat.send('Hello')
        self.chat.display([user(request=self.posts[0]['request_id'])])
        output.assert_not_called()

    @patch('cli.chat.console.print')
    def test_uncertain_delivery_recovers_with_null_request_id_and_valid_token(self, output):
        self.chat.display(self.chat.history())
        output.reset_mock()
        self.failure = ApiError('Network failure')
        with self.assertRaises(ApiError):
            self.chat.send('Hello')
        accepted = user(identity='accepted')
        accepted['idempotency_token'] = self.posts[0]['request_id']
        self.page = {'items': [reply(), accepted, user('old')]}
        self.assertTrue(self.chat.refresh())
        self.assertEqual(output.call_args_list[0].args[0].plain, 'Pocket: [red]Hi there')
        self.assertEqual(output.call_count, 2)
        self.assertEqual(len(self.posts), 1)

    def test_confirmed_rejection_can_be_corrected(self):
        self.failure = ApiError('Forbidden', status=403)
        with self.assertRaises(ApiError):
            self.chat.send('Hello')
        self.assertIsNone(self.chat.pending)
        self.assertFalse(self.chat.state_path.exists())

    def test_older_assistant_message_does_not_finish_wait(self):
        self.chat.send('Hello')
        self.page = {'items': [user(), reply('older'), user('old')]}
        self.assertFalse(self.chat.refresh())

    @patch('cli.chat.console.print')
    def test_chronological_api_pages_do_not_treat_old_dot_messages_as_reply(self, output):
        old_reply = dict(reply('old-reply'), created_at='2026-10-20T14:22:22Z')
        old_user = dict(user('old'), created_at='2026-10-20T14:23:00Z')
        sent = dict(user(), created_at='2026-10-24T21:25:29Z')
        new_reply = dict(reply(), created_at='2026-10-24T21:25:37Z')
        self.page = {'items': [old_reply, old_user]}
        self.chat.display(self.chat.history())
        self.assertTrue(output.call_args_list[0].args[0].plain.startswith('Pocket:'))
        self.assertTrue(output.call_args_list[2].args[0].plain.startswith('You:'))
        output.reset_mock()
        self.chat.send('Hello')
        self.page = {'items': [old_reply, old_user, sent]}
        self.assertFalse(self.chat.refresh())
        output.assert_not_called()
        self.page = {'items': [old_reply, old_user, sent, new_reply]}
        self.assertTrue(self.chat.refresh())
        self.assertEqual(output.call_args_list[0].args[0].plain, 'Pocket: [red]Hi there')
        self.assertEqual(len(self.posts), 1)

    def test_pagination_finds_accepted_message_beyond_latest_page(self):
        self.chat.send('Hello')
        self.client.request.side_effect = [
            {'items': [reply()], 'prev_cursor': 'older'},
            {'items': [user(), user('old')]},
        ]
        self.assertTrue(self.chat.refresh())
        self.assertEqual(self.client.request.call_args.kwargs['query']['before'], 'older')

    def test_empty_room_send_reconciles_beyond_latest_page(self):
        self.page = {'items': []}
        self.chat.send('Hello')
        self.client.request.side_effect = [
            {'items': [reply(str(i)) for i in range(25)], 'prev_cursor': 'older'},
            {'items': [user()]},
        ]
        with patch('cli.chat.console.print'):
            self.assertTrue(self.chat.refresh())
        self.assertEqual(self.client.request.call_args.kwargs['query']['before'], 'older')
        self.assertEqual(len(self.posts), 1)
        self.assertFalse(self.chat.state_path.exists())

    def test_journal_failure_before_send_does_not_post_or_block_a_correction(self):
        with patch.object(self.chat, 'save', side_effect=OSError('Disk full')):
            with self.assertRaisesRegex(ApiError, 'no message was sent'):
                self.chat.send('Hello')
        self.assertIsNone(self.chat.pending)
        self.assertEqual(self.posts, [])
        self.chat.send('Corrected')
        self.assertEqual(len(self.posts), 1)

    def test_failed_journal_removal_keeps_pending_for_retry(self):
        self.chat.send('Hello')
        self.page = {'items': [reply(), user(), user('old')]}
        with patch.object(self.chat, 'save', side_effect=OSError('Read only')):
            with self.assertRaises(OSError):
                self.chat.refresh()
        self.assertIsNotNone(self.chat.pending)
        self.assertTrue(self.chat.refresh())
        self.assertFalse(self.chat.state_path.exists())

    def test_malformed_message_content_reports_api_error(self):
        for item in ({'content': ['bad']}, {'content': {'text': None}},
                     {'account_user_id': 123},
                     {'raw_messages': [{'author': ['bad']}]},
                     {'raw_messages': [{'author': {'role': 'assistant'}, 'content': ['bad']}]}):
            with self.subTest(item=item), self.assertRaises(ApiError):
                message_text(item)

    def test_full_chronological_page_without_cursor_uses_oldest_message_id(self):
        latest = [dict(reply(str(i)), created_at=f'2026-10-24T21:25:{i:02d}Z')
                  for i in range(1, 26)]
        self.client.request.side_effect = [
            {'items': latest, 'prev_cursor': None},
            {'items': [dict(user('baseline'), created_at='2026-10-24T21:24:00Z')]},
        ]
        history = self.chat.history(until={'baseline'})
        self.assertEqual(history[0]['id'], '25')
        self.assertEqual(history[-1]['id'], 'baseline')
        self.assertEqual(self.client.request.call_args.kwargs['query']['before'], '1')

    def test_hidden_analysis_and_nontext_parts_are_not_rendered(self):
        item = {'raw_messages': [
            {'author': {'role': 'assistant'}, 'channel': 'analysis', 'content': {'parts': ['secret']}},
            {'author': {'role': 'assistant'}, 'metadata': {'hidden': True}, 'content': {'parts': ['hidden']}},
            {'author': {'role': 'assistant'}, 'content': {'parts': ['Visible', {'image': 'x'}]}},
        ]}
        self.assertEqual(message_text(item), ('Visible', False))
        self.assertEqual(terminal_text('\x1b\x07Hello\n'), 'Hello\n')

    @patch('cli.chat.console.print')
    def test_reply_that_gains_visible_text_is_rendered(self, output):
        self.chat.display([{'id': 'evolving', 'raw_messages': []}])
        self.chat.display([reply('evolving')])
        self.chat.display([reply('evolving')])
        self.assertEqual(output.call_count, 2)  # One message and its spacing, despite repeated refresh.
        self.assertEqual(output.call_args_list[0].args[0].plain, 'Pocket: [red]Hi there')

    @patch('cli.chat.console.print')
    def test_copy_numbers_are_stable_for_updated_responses_and_exclude_own_messages(self, output):
        first = reply('first')
        self.chat.display([first, user('mine')])
        second = reply('second')
        self.chat.display([second, first])
        updated = dict(first, content={'text': 'Updated\n日本語 [literal]'})
        self.chat.display([updated])
        self.assertEqual(self.chat.response_numbers, {'first': 1, 'second': 2})
        self.assertEqual(self.chat.responses, {1: 'Updated\n日本語 [literal]', 2: '[red]Hi there'})
        self.assertEqual(output.call_args_list[-1].args[0].plain, 'Response #1 · /copy 1')

    @patch('cli.chat.DotClient')
    def test_invalid_timeout_does_not_authenticate(self, client):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--source', 'chatgpt', 'chat', 'Pocket', '--message', 'Hi', '--timeout', '0']), 1)
        client.assert_not_called()

    @patch('cli.chat.run', return_value=0)
    def test_dispatch(self, run):
        self.assertEqual(main(['--source', 'chatgpt', 'chat', 'Pocket', '--message', 'Hi']), 0)
        self.assertEqual(run.call_args.args[0].dot, 'Pocket')

    @patch('cli.chat.sys.stdin')
    @patch('cli.chat.DotClient')
    def test_piped_input_requires_explicit_message(self, client, stdin):
        stdin.isatty.return_value = False
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--source', 'chatgpt', 'chat', 'Pocket']), 1)
        client.assert_not_called()
