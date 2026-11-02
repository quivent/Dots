"""The terminal transport shares delivery recovery with the existing Dot client."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cli.api import ApiError
from cli.main import Launcher
from cli.registry import Registry
from cli.tui_bridge import Backend, serve


def message(identity, text, mine=False, **extra):
    return {'id': identity, 'sender_is_self': mine, 'content': {'text': text}, **extra}


class Client:
    def __init__(self):
        self.profile = {'id': 'remote', 'display_name': 'Pocket', 'messaging_room_id': 'room',
                        'is_paused': False, 'access_token': 'SECRET_TOKEN'}
        self.items = [message('old', 'Earlier reply')]
        self.posts = []
        self.calls = []
        self.failure = None

    def path(self, identity):
        return '/tbo/' + identity

    def resolve(self, name):
        return 'remote'

    def request(self, method, path, **kwargs):
        self.calls.append((method, path))
        if path == '/tbo/remote':
            return self.profile.copy()
        if path.endswith('/tasks'):
            return {'data': [{'id': 'task', 'title': 'Research', 'status': 'running',
                              'token': 'SECRET_TOKEN'}]}
        if method == 'GET':
            return {'items': self.items}
        body = kwargs['body']
        self.posts.append(body)
        if self.failure:
            raise self.failure
        self.items.insert(0, message('sent', body['content']['text'], True,
                                     request_id=body['request_id']))
        return {'id': 'sent'}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.launcher = Launcher(runtime=Path(self.temp.name))
        self.client = Client()
        Registry(self.launcher).remember(self.client.profile)
        self.backend = Backend(self.launcher, lambda: self.client)
        self.addCleanup(self.backend.close)

    def connect(self):
        return self.backend.request('connect', {'dot': 'Pocket'})

    def test_connect_resolves_saved_provider_identity_and_only_reads(self):
        result = self.connect()
        self.assertEqual(result['name'], 'Pocket')
        self.assertEqual(result['messages'], [{'id': 'old', 'text': 'Earlier reply', 'mine': False}])
        self.assertFalse(result['pending'])
        self.assertEqual(self.client.calls[0], ('GET', '/tbo/remote'))
        self.assertTrue(all(method == 'GET' for method, _ in self.client.calls))
        self.assertNotIn('SECRET_TOKEN', json.dumps(result))

    def test_send_posts_once_and_refresh_reconciles_reply(self):
        self.connect()
        state = self.backend.request('send', {'text': 'Hello\n日本語'})
        self.assertTrue(state['pending'])
        self.assertEqual(state['messages'][-1], {'id': 'sent', 'text': 'Hello\n日本語', 'mine': True})
        self.assertTrue(self.backend.chat.state_path.exists())
        with self.assertRaisesRegex(ApiError, 'still pending'):
            self.backend.request('send', {'text': 'Duplicate'})
        self.client.items.insert(0, message('reply', '**Received**'))
        state = self.backend.request('refresh', {})
        self.assertFalse(state['pending'])
        self.assertFalse(self.backend.chat.state_path.exists())
        self.assertEqual([m['id'] for m in state['messages']], ['old', 'sent', 'reply'])
        self.assertEqual(len(self.client.posts), 1)

    def test_uncertain_send_survives_reconnect_without_retry(self):
        self.connect()
        self.client.failure = ApiError('Network failure')
        with self.assertRaisesRegex(ApiError, 'No automatic retry'):
            self.backend.request('send', {'text': 'Once'})
        self.backend.close()
        state = self.connect()
        self.assertTrue(state['pending'])
        self.client.items = [message('reply', 'Done'),
                             message('accepted', 'Once', True,
                                     request_id=self.client.posts[0]['request_id']),
                             *self.client.items]
        state = self.backend.request('refresh', {})
        self.assertFalse(state['pending'])
        self.assertEqual(len(self.client.posts), 1)

    def test_paused_dot_is_readable_but_not_resumed_or_sent(self):
        self.client.profile['is_paused'] = True
        state = self.connect()
        self.assertTrue(state['profile']['is_paused'])
        with self.assertRaisesRegex(ApiError, 'paused'):
            self.backend.request('send', {'text': 'Hello'})
        self.assertEqual(self.client.posts, [])
        self.assertTrue(all(method == 'GET' for method, _ in self.client.calls))

    def test_response_updates_keep_provider_identity_and_hide_analysis(self):
        self.connect()
        self.client.items = [message('old', 'Updated\x1b text'),
                             {'id': 'hidden', 'raw_messages': [
                                 {'author': {'role': 'assistant'}, 'channel': 'analysis',
                                  'content': {'parts': ['Hidden reasoning']}}]}]
        state = self.backend.request('refresh', {})
        self.assertEqual(state['messages'], [{'id': 'old', 'text': 'Updated text', 'mine': False}])

    def test_abandon_rolls_back_if_journal_cannot_be_removed(self):
        self.connect()
        self.backend.request('send', {'text': 'Hello'})
        pending = self.backend.chat.pending
        with patch.object(self.backend.chat, 'save', side_effect=OSError('Read only')):
            with self.assertRaises(OSError):
                self.backend.request('abandon', {})
        self.assertIs(self.backend.chat.pending, pending)
        self.backend.request('abandon', {})
        self.assertFalse(self.backend.chat.state_path.exists())
        self.assertEqual(len(self.client.posts), 1)

    def test_status_only_reads_and_filters_provider_metadata(self):
        self.connect()
        state = self.backend.request('status', {})
        self.assertEqual(state['tasks'], [{'id': 'task', 'title': 'Research', 'status': 'running'}])
        self.assertNotIn('SECRET_TOKEN', json.dumps(state))
        self.assertEqual(self.client.posts, [])

    def test_protocol_recovers_after_invalid_request_and_emits_only_json(self):
        requests = ['invalid json', json.dumps({'id': 1, 'method': 'connect',
                                                'params': {'dot': 'Pocket'}}),
                    json.dumps({'id': 2, 'method': 'send', 'params': {'text': 7}}),
                    json.dumps({'id': 'bad-close', 'method': 'close', 'params': []}),
                    json.dumps({'id': 3, 'method': 'status'}),
                    json.dumps({'id': 4, 'method': 'close'})]
        output, incidental = io.StringIO(), io.StringIO()
        with redirect_stdout(incidental):
            serve(self.backend, io.StringIO('\n'.join(requests)), output)
        replies = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(replies), 6)
        self.assertIn('error', replies[0])
        self.assertEqual(replies[1]['result']['name'], 'Pocket')
        self.assertIn('error', replies[2])
        self.assertIn('error', replies[3])
        self.assertEqual(replies[4]['result']['tasks'][0]['title'], 'Research')
        self.assertEqual(replies[5]['result'], {'closed': True})
        self.assertEqual(incidental.getvalue(), '')
        self.assertIsNone(self.backend.chat)
        self.assertNotIn('SECRET_TOKEN', output.getvalue())

    def test_eof_closes_connection_and_releases_session_lock(self):
        self.connect()
        connection = self.backend.connection
        with patch.object(connection, 'close', wraps=connection.close) as close:
            serve(self.backend, io.StringIO(''), io.StringIO())
            close.assert_called_once()
        self.assertIsNone(self.backend.chat)

    def test_hosted_entries_and_invalid_targets_are_not_opened(self):
        Registry(self.launcher).remember({'id': 'worker', 'display_name': 'Worker'}, 'hosted')
        for params in ({'dot': 'Worker'}, {'dot': 7}, {'dot': 'Pocket', 'by_id': 'yes'},
                       {'source': 'hosted'}, {'by_id': True}):
            with self.subTest(params=params), self.assertRaises(ApiError):
                self.backend.request('connect', params)
        self.assertEqual(self.client.calls, [])
