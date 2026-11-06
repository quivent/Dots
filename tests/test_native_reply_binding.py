"""Exact speech-parent metadata from bounded native reads; no live sessions."""
import json
from pathlib import Path
import tempfile
import unittest

from cli.local_codex import LocalCodexBridge, PREFIX, native_reply_bindings
from tests.test_local_codex import FakeRPC, THREAD


def user(identity, turn='turn-one'):
    return {'turnId': turn, 'item': {'id': 'native-' + identity,
            'type': 'userMessage', 'clientId': identity,
            'content': [{'type': 'text', 'text': identity}]}}


def reply(identity, turn='turn-one'):
    return {'turnId': turn, 'item': {'id': identity,
            'type': 'agentMessage', 'text': identity}}


class PagedRPC(FakeRPC):
    def __init__(self, pages):
        super().__init__()
        self.pages = pages

    def call(self, method, params):
        if method == 'thread/items/list':
            self.calls.append((method, params))
            return self.pages[params.get('cursor')]
        return super().call(method, params)


class NativeReplyBindingTests(unittest.TestCase):
    def history(self, pages):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        rpc = PagedRPC(pages)
        bridge = LocalCodexBridge([{'thread_id': THREAD, 'name': 'Fixture'}],
                                  Path(directory.name) / 'sends.sqlite', rpc)
        self.addCleanup(bridge.conn.close)
        value = bridge.request('GET', '/messaging/rooms/' + PREFIX + THREAD + '/messages', {}, {})
        return value, rpc

    def test_hidden_parent_is_recovered_without_expanding_visible_page(self):
        hidden = [{'turnId': 'turn-one', 'item': {'id': str(i),
                   'type': 'reasoning', 'content': ['private reasoning']}} for i in range(99)]
        value, rpc = self.history({
            None: {'data': [reply('final')] + hidden, 'nextCursor': 'older'},
            'older': {'data': [user('request-one')], 'nextCursor': None}})
        self.assertEqual(len(value['items']), 1)
        self.assertEqual(value['items'][0]['reply_to_request_id'], 'request-one')
        self.assertEqual(value['items'][0]['turn_id'], 'turn-one')
        self.assertEqual(value['prev_cursor'], 'older')
        self.assertEqual(len(rpc.calls), 2)
        self.assertNotIn('private reasoning', json.dumps(value))
        self.assertFalse(any(method.startswith('turn/') for method, _ in rpc.calls))

    def test_later_steer_in_same_turn_does_not_authorize_earlier_request(self):
        value = native_reply_bindings([reply('second'), user('request-two'),
                                      reply('first'), user('request-one')])
        self.assertEqual(value['first']['reply_to_request_id'], 'request-one')
        self.assertEqual(value['second']['reply_to_request_id'], 'request-two')
        self.assertEqual(value['first']['turn_id'], value['second']['turn_id'])

    def test_another_turn_cannot_supply_a_missing_parent(self):
        self.assertEqual(native_reply_bindings([reply('final', 'new-turn'),
                                               user('request-one', 'old-turn')]), {})
        self.assertEqual(native_reply_bindings([{'item': reply('final')['item']},
                                               user('request-one')]), {})

    def test_lookup_is_bounded_and_does_not_skip_public_history(self):
        pages = {None: {'data': [reply('final')], 'nextCursor': 'page-1'}}
        for i in range(1, 10):
            pages['page-' + str(i)] = {'data': [], 'nextCursor': 'page-' + str(i + 1)}
        value, rpc = self.history(pages)
        self.assertEqual(len(rpc.calls), 10)
        self.assertEqual(value['prev_cursor'], 'page-1')
        self.assertNotIn('reply_to_request_id', value['items'][0])

    def test_visible_parent_requires_no_extra_read(self):
        value, rpc = self.history({None: {'data': [reply('final'), user('request-one')],
                                         'nextCursor': 'older'}})
        self.assertEqual(len(rpc.calls), 1)
        self.assertEqual(value['items'][-1]['reply_to_request_id'], 'request-one')

    def test_native_completion_and_phase_are_preserved_for_early_speech(self):
        finished = reply('final')
        finished['completedAtMs'] = 5500
        finished['item']['phase'] = 'commentary'
        value, _ = self.history({None: {'data': [finished, user('request-one')],
                                       'nextCursor': None}})
        row = value['items'][-1]
        self.assertEqual(row['completed_at'], 5.5)
        self.assertEqual(row['phase'], 'commentary')
        self.assertEqual(row['reply_to_request_id'], 'request-one')


if __name__ == '__main__':
    unittest.main()
