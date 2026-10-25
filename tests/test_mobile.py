import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
import uuid

from cli.mobile import MobileServer, PairingAuthority, load_token


class MobileTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.request.return_value = {'items': []}
        self.token = 'fixture-' + 'x' * 40
        self.server = MobileServer(('127.0.0.1', 0), self.token, lambda: self.client)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, method='GET', path='/v1/tbo', body=None, token=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        actual = dict(headers or {})
        if token: actual['Authorization'] = 'Bearer ' + self.token
        if body is not None: actual['Content-Type'] = 'application/json'
        connection.request(method, path, json.dumps(body) if body is not None else None, actual)
        response = connection.getresponse()
        status, result = response.status, json.loads(response.read())
        connection.close()
        return status, result

    def test_unauthenticated_requests_never_touch_account(self):
        self.assertEqual(self.request(token=False)[0], 401)
        self.client.request.assert_not_called()

    def test_read_query_is_forwarded_without_phone_credentials(self):
        self.assertEqual(self.request(path='/v1/tbo?limit=25&include_room_preview=false')[0], 200)
        self.client.request.assert_called_once_with('GET', '/tbo', query={'limit': '25', 'include_room_preview': 'false'})

    def test_arbitrary_routes_and_browser_requests_are_rejected(self):
        for path in ('/v1/account', '/v1/tbo/../one', '/v1/tbo?limit=1&limit=2', '/v1/tbo?redirect=evil'):
            self.assertEqual(self.request(path=path)[0], 400)
        self.assertEqual(self.request(headers={'Origin': 'https://example.com'})[0], 403)
        self.client.request.assert_not_called()

    def test_provider_dot_ids_support_tilde_without_allowing_encoded_paths(self):
        for identifier in ('dot~fixture', 'dot%7Efixture', 'dot%7efixture'):
            for route in ('activity', 'tasks'):
                self.assertEqual(self.request(path='/v1/tbo/' + identifier + '/' + route)[0], 200)
        for identifier in ('dot%2Ffixture', 'dot%2e%2efixture', 'dot%257Efixture'):
            self.assertEqual(self.request(path='/v1/tbo/' + identifier + '/tasks')[0], 400)

    def test_profile_and_chat_are_independent_requests(self):
        body = dict(display_name='Scout', create_thread=False, create_additional=True, should_initialize=False)
        self.assertEqual(self.request('POST', '/v1/tbo', body)[0], 200)
        self.client.request.assert_called_once_with('POST', '/tbo', body=body)
        self.client.reset_mock()
        self.assertEqual(self.request('POST', '/v1/tbo/scout/messaging-room')[0], 200)
        self.client.request.assert_called_once_with('POST', '/tbo/scout/messaging-room', body={})

    def test_message_idempotency_key_is_preserved(self):
        identifier = str(uuid.uuid4())
        body = dict(content={'text': 'Hello', 'attachments': []}, request_id=identifier, idempotency_token=identifier, timezone_offset_min=0)
        self.assertEqual(self.request('POST', '/v1/messaging/rooms/room/messages', body)[0], 200)
        self.client.request.assert_called_once_with('POST', '/messaging/rooms/room/messages', body=body)

    def test_unsupported_message_payload_does_not_write(self):
        body = dict(content={'text': 'Hello', 'attachments': []}, request_id='bad', idempotency_token='different', timezone_offset_min=0)
        self.assertEqual(self.request('POST', '/v1/messaging/rooms/room/messages', body)[0], 400)
        self.client.request.assert_not_called()

    def test_token_is_stable_private_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            token = load_token(path)
            self.assertEqual(token, load_token(path))
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            alias = Path(directory) / 'alias'
            alias.symlink_to(path)
            with self.assertRaises(ValueError): load_token(alias)

    def test_pairing_code_issues_phone_token_without_exposing_mac_credential(self):
        status, response = self.request('POST', '/v1/pairing/start')
        self.assertEqual(status, 200)
        code = response['code']
        status, paired = self.request('POST', '/v1/pair', {'code': code}, token=False)
        self.assertEqual(status, 200)
        self.assertNotEqual(paired['token'], self.token)
        self.assertEqual(self.request('POST', '/v1/pair', {'code': code}, token=False)[0], 403)
        headers = {'Authorization': 'Bearer ' + paired['token']}
        self.assertEqual(self.request(headers=headers, token=False)[0], 200)
        self.assertEqual(self.request('POST', '/v1/pairing/start', headers=headers, token=False)[0], 403)
        self.assertEqual(self.request('POST', '/v1/pairing/revoke')[0], 200)
        self.assertEqual(self.request(headers=headers, token=False)[0], 401)

    def test_pairing_stops_after_five_guesses(self):
        code = self.server.pairing.start()['code']
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5): self.assertIsNone(self.server.pairing.pair(wrong))
        self.assertIsNone(self.server.pairing.pair(code))

    def test_phone_token_survives_daemon_restart_as_private_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            authority = PairingAuthority(self.token, directory)
            phone = authority.pair(authority.start()['code'])['token']
            path = Path(directory) / 'paired-phones.json'
            self.assertNotIn(phone, path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(PairingAuthority(self.token, directory).authorized(phone))

    def test_health_does_not_contact_chatgpt(self):
        self.assertEqual(self.request(path='/v1/health')[0], 200)
        self.client.request.assert_not_called()
