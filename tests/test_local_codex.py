from contextlib import contextmanager
import tempfile
from pathlib import Path
import unittest
import uuid
import http.client
import json
import threading

from cli.api import ApiError
from cli.local_codex import LocalCodexBridge, PREFIX
from cli.mobile import MobileServer

THREAD = '01a1835f-30b5-78a0-937f-a18c4ee8fadb'


class FakeRPC:
    def __init__(self):
        self.calls = []
        self.active = True
        self.loaded = True
        self.fail_write = False
        self.items = []
        self.resume_identity = THREAD

    @contextmanager
    def connection(self):
        yield self.call

    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/read':
            return {'thread': {'cwd': '/workspace', 'status': {'type': 'active'}}}
        if method == 'thread/loaded/list':
            return {'data': [THREAD] if self.loaded else []}
        if method == 'thread/resume':
            self.loaded = self.resume_identity == THREAD
            return {'thread': {'id': self.resume_identity}}
        if method == 'thread/turns/list':
            return {'data': [{'id': 'turn', 'status': 'inProgress' if self.active else 'completed'}]}
        if method == 'thread/items/list':
            return {'data': self.items, 'nextCursor': None}
        if method in ('turn/start', 'turn/steer'):
            if self.fail_write:
                raise ApiError('Connection lost after send', 502)
            return {}
        if method == 'turn/interrupt':
            return {}
        raise AssertionError(method)


class LocalCodexTests(unittest.TestCase):
    def setUp(self):
        self.rpc = FakeRPC()
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / 'sends.sqlite'
        self.bridge = self.make_bridge()
        self.body = {'request_id': str(uuid.uuid4()), 'content': {'text': 'Please check progress', 'attachments': []},
                     'work_approved': True}
        self.body['idempotency_token'] = self.body['request_id']

    def make_bridge(self):
        return LocalCodexBridge([{'thread_id': THREAD, 'name': 'Explain the work'}], self.database, self.rpc)

    def tearDown(self):
        self.bridge.conn.close()
        self.directory.cleanup()

    def send(self):
        return self.bridge.request('POST', '/messaging/rooms/' + PREFIX + THREAD + '/messages', {}, self.body)

    def writes(self):
        return [c for c in self.rpc.calls if c[0].startswith('turn/')]

    def test_live_followup_steers_existing_turn_without_configuration_overrides(self):
        self.send()
        method, params = self.writes()[0]
        self.assertEqual(method, 'turn/steer')
        self.assertEqual(params, {'threadId': THREAD, 'clientUserMessageId': self.body['request_id'],
                                 'expectedTurnId': 'turn', 'input': [{'type': 'text', 'text': 'Please check progress', 'text_elements': []}]})
        self.assertFalse(any(m in ('thread/resume', 'thread/start') for m, _ in self.rpc.calls))

    def test_idle_session_starts_turn_and_successful_retry_is_deduplicated_after_restart(self):
        self.rpc.active = False
        first = self.send()
        self.bridge.conn.close()
        self.bridge = self.make_bridge()
        self.assertEqual(first, self.send())
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][0], 'turn/start')
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_uncertain_delivery_is_never_replayed_even_after_restart(self):
        self.rpc.fail_write = True
        with self.assertRaises(ApiError): self.send()
        self.bridge.conn.close()
        self.bridge = self.make_bridge()
        with self.assertRaises(ApiError): self.send()
        self.assertEqual(len(self.writes()), 1)

    def test_request_identity_cannot_be_reused_for_different_text(self):
        self.send()
        self.body['content']['text'] = 'Different work'
        with self.assertRaises(ApiError): self.send()
        self.assertEqual(len(self.writes()), 1)

    def test_explicit_approval_and_loaded_session_are_required(self):
        self.body['work_approved'] = False
        with self.assertRaises(ApiError): self.send()
        self.body['work_approved'] = True
        self.rpc.loaded = False
        with self.assertRaises(ApiError): self.send()
        self.assertEqual(self.writes(), [])

    def test_only_allowlisted_threads_are_accessible(self):
        with self.assertRaises(ApiError):
            self.bridge.request('GET', '/tbo/' + PREFIX + str(uuid.uuid4()), {}, {})
        self.assertEqual(self.rpc.calls, [])

    def test_opted_in_approved_send_restores_exact_identity_and_deduplicates(self):
        self.bridge.sessions[THREAD]['resume_on_send'] = True
        self.rpc.loaded = False; self.rpc.active = False
        first = self.send(); self.assertEqual(first, self.send())
        resumes = [p for m, p in self.rpc.calls if m == 'thread/resume']
        self.assertEqual(resumes, [{'threadId': THREAD, 'excludeTurns': True}])
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0][0], 'turn/start')

    def test_phone_cannot_enable_resume_and_unapproved_send_never_resumes(self):
        self.rpc.loaded = False
        self.body['resume_on_send'] = True
        with self.assertRaises(ApiError): self.send()
        self.bridge.sessions[THREAD]['resume_on_send'] = True
        self.body['work_approved'] = False
        with self.assertRaises(ApiError): self.send()
        self.assertFalse(any(m == 'thread/resume' for m, _ in self.rpc.calls))

    def test_mismatched_resume_cannot_send_or_create_uncertain_receipt(self):
        self.bridge.sessions[THREAD]['resume_on_send'] = True
        self.rpc.loaded = False; self.rpc.resume_identity = str(uuid.uuid4())
        with self.assertRaises(ApiError): self.send()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.bridge.conn.execute('SELECT count(*) FROM sends').fetchone()[0], 0)

    def test_observation_of_opted_in_session_does_not_resume(self):
        self.bridge.sessions[THREAD]['resume_on_send'] = True
        self.rpc.loaded = False
        self.bridge.request('GET', '/messaging/rooms/' + PREFIX + THREAD + '/messages', {}, {})
        self.assertFalse(any(m == 'thread/resume' for m, _ in self.rpc.calls))

    def test_history_filters_internal_data_and_reconciles_unknown_send(self):
        self.rpc.fail_write = True
        with self.assertRaises(ApiError): self.send()
        self.rpc.items = [
            {'startedAtMs': 3000, 'item': {'type': 'agentMessage', 'id': 'reply', 'text': 'Progress update', 'phase': 'commentary'}},
            {'startedAtMs': 2000, 'item': {'type': 'reasoning', 'id': 'secret', 'content': ['private']}},
            {'startedAtMs': 1000, 'item': {'type': 'userMessage', 'id': 'native', 'clientId': self.body['request_id'],
                                         'content': [{'type': 'text', 'text': 'Please check progress'}]}}]
        result = self.bridge.request('GET', '/messaging/rooms/' + PREFIX + THREAD + '/messages', {}, {})
        self.assertEqual([m['id'] for m in result['items']], [self.body['request_id'], 'reply'])
        self.assertEqual(result['items'][0]['created_at'], 1)
        self.assertEqual(self.send()['id'], self.body['request_id'])
        self.assertEqual(len(self.writes()), 1)

    def test_mobile_catalog_keeps_local_sessions_when_account_is_offline(self):
        def unavailable(): raise ApiError('No account', 401)
        server = MobileServer(('127.0.0.1', 0), 'x' * 40, unavailable, codex=self.bridge)
        try:
            result = server.account_request('GET', '/tbo', {}, {})
            self.assertEqual(result['items'][0]['source'], 'local_codex')
            self.assertEqual(result['cloud_connection'], 'unavailable')
        finally:
            server.server_close()

    def test_phone_authentication_is_checked_before_local_thread_access(self):
        server = MobileServer(('127.0.0.1', 0), 'x' * 40, codex=self.bridge)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for authorized in (False, True):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                headers = {'Authorization': 'Bearer ' + 'x' * 40} if authorized else {}
                connection.request('GET', '/v1/tbo/' + PREFIX + THREAD, headers=headers)
                response = connection.getresponse()
                result = json.loads(response.read())
                self.assertEqual(response.status, 200 if authorized else 401)
                if not authorized: self.assertEqual(self.rpc.calls, [])
                else: self.assertEqual(result['display_name'], 'Explain the work')
                connection.close()
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__':
    unittest.main()
