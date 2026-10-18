import io
import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from dots_cli.api import ApiError, DotClient, NoRedirect, SecureStore


def reply(data):
    response = Mock()
    response.read.return_value = json.dumps(data).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class ApiTests(unittest.TestCase):
    def client(self, *pages):
        opener = Mock()
        opener.open.side_effect = [reply(p) for p in pages]
        return DotClient('private-token', 'account-1', opener), opener

    def test_missing_credentials_never_calls_network(self):
        client, opener = self.client()
        client.token = ''
        with self.assertRaisesRegex(ApiError, 'dots auth'):
            client.list()
        opener.open.assert_not_called()

    def test_headers_and_catalog_pagination(self):
        client, opener = self.client({'items': [{'id': 'one'}], 'cursor': 'next'}, {'items': [{'id': 'two'}], 'cursor': None})
        self.assertEqual([x['id'] for x in client.list()], ['one', 'two'])
        request = opener.open.call_args_list[1].args[0]
        self.assertIn('cursor=next', request.full_url)
        self.assertIn('include_room_preview=false', request.full_url)
        self.assertEqual(request.get_header('Authorization'), 'Bearer private-token')
        self.assertEqual(request.get_header('Chatgpt-account-id'), 'account-1')

    def test_activity_uses_data_and_next_cursor(self):
        client, _ = self.client({'data': [{'thread_id': 'task'}], 'next_cursor': 'more'}, {'data': [], 'next_cursor': None})
        self.assertEqual(client.pages('/tbo/one/activity'), [{'thread_id': 'task'}])

    def test_repeated_cursor_is_an_error(self):
        client, opener = self.client({'items': [], 'cursor': 'repeat'}, {'items': [], 'cursor': 'repeat'})
        with self.assertRaisesRegex(ApiError, 'pagination'):
            client.list()
        self.assertEqual(opener.open.call_count, 2)

    def test_malformed_collection_is_an_error(self):
        client, _ = self.client({'unexpected': []})
        with self.assertRaisesRegex(ApiError, 'collection'):
            client.list()

    def test_creation_is_single_write_without_hidden_room_repair(self):
        client, opener = self.client({'items': [], 'cursor': None}, {'id': 'one', 'root_thread_id': 'thread'})
        self.assertEqual(client.create('Research')['id'], 'one')
        self.assertEqual(opener.open.call_count, 2)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(json.loads(request.data), {'display_name': 'Research', 'create_thread': True, 'create_additional': False, 'should_initialize': True})

    def test_explicit_creation_does_not_depend_on_catalog(self):
        client, opener = self.client({'id': 'new', 'root_thread_id': 'thread'})
        client.create('Other', additional=True)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(opener.open.call_args.args[0].method, 'POST')

    def test_additional_creation_flag(self):
        client, opener = self.client({'items': [{'id': 'existing'}]}, {'id': 'new', 'root_thread_id': 'thread'})
        client.create('Other')
        self.assertTrue(json.loads(opener.open.call_args.args[0].data)['create_additional'])

    def test_creation_failure_never_retries_or_leaks_response(self):
        client, opener = self.client({'items': []})
        opener.open.side_effect = [reply({'items': []}), HTTPError('https://example', 503, 'private-token', {}, io.BytesIO(b'private-token'))]
        with self.assertRaises(ApiError) as caught:
            client.create('Research')
        self.assertIn('Outcome unknown', str(caught.exception))
        self.assertNotIn('private-token', str(caught.exception))
        self.assertEqual(opener.open.call_count, 2)

    def test_network_error_marks_write_outcome_unknown(self):
        client, opener = self.client()
        opener.open.side_effect = URLError('private-token')
        with self.assertRaisesRegex(ApiError, 'Outcome unknown'):
            client.request('POST', '/tbo')
        self.assertEqual(opener.open.call_count, 1)

    def test_incomplete_create_is_not_reported_as_success(self):
        client, _ = self.client({'items': []}, {'id': 'one'})
        with self.assertRaisesRegex(ApiError, 'Outcome unknown'):
            client.create('Research')

    def test_resolve_requires_unique_name(self):
        client, _ = self.client({'items': [{'id': 'one', 'display_name': 'same'}, {'id': 'two', 'display_name': 'same'}]})
        with self.assertRaisesRegex(ApiError, 'ambiguous'):
            client.resolve('same')

    def test_primary_selection_resolves_default(self):
        client, _ = self.client({'items': [{'id': 'one'}, {'id': 'two'}]}, {'profile': {'id': 'two'}, 'selection': {'available': True}})
        self.assertEqual(client.resolve(), 'two')

    def test_dot_ids_cannot_inject_paths(self):
        self.assertEqual(DotClient.path('a/b?x=1'), '/tbo/a%2Fb%3Fx%3D1')

    def test_redirects_are_not_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_credential_store_errors_are_sanitized(self):
        backend = Mock()
        backend.get_password.side_effect = RuntimeError('private-token')
        with self.assertRaises(ApiError) as caught:
            SecureStore(backend).get_password('dots-cli', 'account')
        self.assertNotIn('private-token', str(caught.exception))

    def test_environment_credentials_do_not_read_app_stores(self):
        from dots_cli.api import credentials
        with patch.dict('os.environ', {'DOTS_ACCESS_TOKEN': 'token', 'DOTS_ACCOUNT_ID': 'account'}), patch('dots_cli.api.credential_store') as store:
            self.assertEqual(credentials(), ('token', 'account', 'environment'))
            store.assert_not_called()
