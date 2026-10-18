import base64
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from cli.auth import AuthUnavailable, _exchange, _account_id, existing_credentials
from cli.api import credentials


class ExistingAuthTests(unittest.TestCase):
    def test_existing_account_is_reused_without_a_login_request(self):
        rpc = Mock(side_effect=[{}, {'account': {'type': 'chatgpt'}}, {'authToken': 'fixture-token', 'accountId': 'fixture-account'}])
        self.assertEqual(_exchange(rpc), ('fixture-token', 'fixture-account'))
        self.assertEqual([call.args[0] for call in rpc.call_args_list], ['initialize', 'account/read', 'getAuthStatus'])
        self.assertFalse(rpc.call_args.args[1]['refreshToken'])

    def test_api_key_sign_in_is_not_used_for_dots(self):
        rpc = Mock(side_effect=[{}, {'account': {'type': 'apiKey'}}])
        with self.assertRaises(AuthUnavailable):
            _exchange(rpc)
        self.assertEqual(rpc.call_count, 2)

    def test_missing_sign_in_is_not_misreported_as_ready(self):
        rpc = Mock(side_effect=[{}, {'account': None}])
        with self.assertRaises(AuthUnavailable):
            _exchange(rpc)

    def test_missing_handoff_is_not_misreported_as_ready(self):
        rpc = Mock(side_effect=[{}, {'account': {'type': 'chatgpt'}}, {}])
        with self.assertRaises(AuthUnavailable):
            _exchange(rpc)

    def test_routing_claim_is_parsed_in_memory(self):
        part = base64.urlsafe_b64encode(json.dumps({'https://api.openai.com/auth': {'chatgpt_account_id': 'fixture-account'}}).encode()).decode().rstrip('=')
        self.assertEqual(_account_id({}, 'header.' + part + '.signature'), 'fixture-account')
        self.assertIsNone(_account_id({}, 'malformed'))

    @patch('cli.auth.executable', return_value='/mock/codex')
    @patch('cli.auth.subprocess.Popen')
    def test_server_transport_closes_without_persisting_credentials(self, start, executable):
        process = start.return_value
        process.stdin = io.StringIO()
        process.stdout = io.StringIO('\n'.join(json.dumps({'id': i, 'result': r}) for i, r in enumerate([
            {}, {'account': {'type': 'chatgpt'}}, {'authToken': 'fixture-token', 'accountId': 'fixture-account'}], 1)) + '\n')
        process.poll.return_value = None
        self.assertEqual(existing_credentials(), ('fixture-token', 'fixture-account'))
        self.assertEqual(start.call_args.args[0], ['/mock/codex', 'app-server', '--stdio'])
        self.assertEqual(start.call_args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertNotIn('shell', start.call_args.kwargs)
        process.terminate.assert_called_once()
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    @patch('cli.auth.executable', return_value='/mock/codex')
    @patch('cli.auth.subprocess.Popen', side_effect=OSError('fixture-sensitive-value'))
    def test_transport_failures_do_not_expose_raw_errors(self, start, executable):
        with self.assertRaises(AuthUnavailable) as error:
            existing_credentials()
        self.assertNotIn('fixture-sensitive-value', str(error.exception))

    @patch.dict('os.environ', {}, clear=True)
    @patch('cli.api.credential_store')
    @patch('cli.auth.existing_credentials', return_value=('fixture-token', 'fixture-account'))
    def test_client_falls_back_to_existing_login(self, existing, store):
        store.return_value.get_password.return_value = None
        self.assertEqual(credentials(), ('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
        store.return_value.set_password.assert_not_called()

    @patch.dict('os.environ', {'DOTS_ACCESS_TOKEN': 'explicit', 'DOTS_ACCOUNT_ID': 'account'}, clear=True)
    @patch('cli.auth.existing_credentials')
    def test_explicit_environment_overrides_existing_login(self, existing):
        self.assertEqual(credentials(), ('explicit', 'account', 'environment'))
        existing.assert_not_called()

    @patch('cli.auth.executable', return_value='/mock/codex')
    @patch('cli.auth.subprocess.run')
    @patch('cli.auth.existing_credentials', return_value=('fixture-token', 'fixture-account'))
    def test_missing_login_can_start_first_party_sign_in(self, existing, run, executable):
        from cli.auth import sign_in
        run.return_value.returncode = 0
        self.assertEqual(sign_in(), ('fixture-token', 'fixture-account'))
        run.assert_called_once_with(['/mock/codex', 'login'], check=False)

    @patch('cli.auth.executable', return_value='/mock/codex')
    @patch('cli.auth.subprocess.run')
    @patch('cli.auth.existing_credentials')
    def test_cancelled_sign_in_does_not_claim_success(self, existing, run, executable):
        from cli.auth import sign_in
        run.return_value.returncode = 1
        with self.assertRaises(AuthUnavailable):
            sign_in()
        existing.assert_not_called()
