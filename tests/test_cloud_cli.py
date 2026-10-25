from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cli.main import main, Launcher


has = unittest.TestCase.assertIn


class CloudCliTests(unittest.TestCase):
    def invoke(self, argv):
        from cli.sources import AGENT_COMMANDS
        if argv and argv[0] in AGENT_COMMANDS and "--source" not in argv:
            argv = [*argv, "--source", "chatgpt"]
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            try:
                code = main(argv)
            except SystemExit as error:
                code = error.code
        return code, output.getvalue()

    @patch('cli.cloud.DotClient')
    def test_explicit_account_source_lists_account(self, client):
        client.return_value.list.return_value = [{'id': 'dot1', 'display_name': 'Research'}]
        code, output = self.invoke(['list', '--json'])
        self.assertEqual(code, 0)
        has(self, 'dot1', output)
        client.return_value.list.assert_called_once()

    @patch('cli.cloud.DotClient')
    @patch('cli.main.Launcher')
    def test_local_list_is_independent_of_cloud_auth(self, launcher, client):
        launcher.return_value.list_dots.return_value = []
        code, output = self.invoke(['list', '--source', 'shortcuts', '--json'])
        self.assertEqual(code, 0)
        has(self, 'local_registry', output)
        client.assert_not_called()

    @patch('cli.cloud.DotClient')
    def test_room_repair_is_explicit_single_write(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {'messaging_room_id': 'room'}
        code, _ = self.invoke(['room', 'one', '--json'])
        self.assertEqual(code, 0)
        client.return_value.request.assert_called_once_with('POST', '/tbo/one/messaging-room')
        client.return_value.create.assert_not_called()

    @patch('cli.cloud.DotClient')
    def test_registered_profile_and_runtime_routes_execute_once(self, client):
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {}
        for command, method, suffix in (('show', 'GET', ''), ('room', 'POST', '/messaging-room'),
                                         ('pause', 'POST', '/runtime/pause'), ('resume', 'POST', '/runtime/resume')):
            with self.subTest(command=command):
                client.reset_mock()
                self.assertEqual(self.invoke([command, 'one', '--by-id', '--json'])[0], 0)
                client.return_value.request.assert_called_once_with(method, '/tbo/one' + suffix)
                client.return_value.resolve.assert_not_called()
                client.return_value.list.assert_not_called()

    @patch('cli.cloud.DotClient')
    def test_task_detail_encodes_task_id(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {}
        code, _ = self.invoke(['tasks', 'one', '--task', 'task/id', '--json'])
        self.assertEqual(code, 0)
        client.return_value.request.assert_called_once_with('GET', '/tbo/one/tasks/task%2Fid')

    @patch('cli.cloud.DotClient')
    def test_inspection_by_id_does_not_depend_on_catalog(self, client):
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {'id': 'one'}
        code, _ = self.invoke(['show', 'one', '--by-id', '--json'])
        self.assertEqual(code, 0)
        client.return_value.resolve.assert_not_called()
        client.return_value.list.assert_not_called()
        client.return_value.request.assert_called_once_with('GET', '/tbo/one')

    @patch('cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('cli.api.DotClient')
    def test_preflight_verifies_reads_without_writing_or_launching(self, client, credential):
        client.return_value.list.return_value = []
        with patch('cli.main.Launcher') as launcher:
            launcher.return_value.local_readiness.return_value = {'project': '/mock/project'}
            code, output = self.invoke(['preflight', '--json'])
        self.assertEqual(code, 0)
        has(self, '"read_access_verified": true', output)
        has(self, '"write_access_verified": false', output)
        self.assertNotIn('fixture-token', output)
        client.return_value.create.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    @patch('cli.api.credentials', return_value=('', '', 'none'))
    @patch('cli.api.DotClient')
    def test_preflight_missing_login_never_calls_api(self, client, credential):
        code, output = self.invoke(['preflight', '--json'])
        self.assertEqual(code, 0)
        has(self, 'auth_required', output)
        client.assert_not_called()

    @patch('cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('cli.api.DotClient')
    def test_corrupt_local_settings_do_not_block_cloud_check(self, client, credential):
        client.return_value.list.return_value = []
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'dots-launcher.json').write_text('{broken', encoding='utf-8')
            with patch('cli.main.Launcher', return_value=Launcher(runtime=base)):
                code, output = self.invoke(['preflight', '--json'])
        self.assertEqual(code, 1)
        has(self, 'local_error', output)
        has(self, '\"read_access_verified\": true', output)

    @patch('cli.main.Launcher')
    def test_setup_only_opens_onboarding(self, launcher):
        launcher.return_value.launch.return_value = {'message': 'Dot onboarding launch requested.'}
        code, output = self.invoke(['setup', 'onboard'])
        self.assertEqual(code, 0)
        launcher.return_value.launch.assert_called_once_with('setup')
        has(self, 'onboarding', output)

    @patch('cli.cloud.credentials', return_value=('', '', 'none'))
    @patch('cli.auth.sign_in', return_value=('fixture-token', 'fixture-account'))
    @patch('cli.cloud.DotClient')
    def test_auth_starts_login_when_missing(self, client, sign_in, credential):
        client.return_value.list.return_value = []
        code, output = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_called_once()
        client.return_value.list.assert_called_once()
        client.return_value.create.assert_not_called()
        self.assertNotIn('fixture-token', output)

    @patch('cli.cloud.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('cli.auth.sign_in')
    @patch('cli.cloud.DotClient')
    def test_auth_reuses_login_without_launching_oauth_again(self, client, sign_in, credential):
        client.return_value.list.return_value = []
        code, output = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_not_called()
        has(self, 'Authenticated', output)

    @patch('cli.cloud.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('cli.auth.sign_in', return_value=('new-fixture-token', 'fixture-account'))
    @patch('cli.cloud.DotClient')
    def test_auth_can_replace_rejected_existing_login(self, client, sign_in, credential):
        from cli.api import ApiError
        client.return_value.list.side_effect = [ApiError('expired', status=401), []]
        code, _ = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_called_once()
        client.return_value.create.assert_not_called()

    @patch('cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('cli.auth.sign_in')
    @patch('cli.api.DotClient')
    def test_preflight_does_not_sign_in_if_existing_login_is_rejected(self, client, sign_in, credential):
        from cli.api import ApiError
        client.return_value.list.side_effect = ApiError('expired', status=401)
        code, _ = self.invoke(['preflight'])
        self.assertEqual(code, 1)
        sign_in.assert_not_called()

    def test_root_help_includes_expanded_commands(self):
        code, output = self.invoke(['--help'])
        self.assertEqual(code, 0)
        for command in ['preflight', 'auth', 'show', 'tasks', 'pause', 'resume', 'room']:
            has(self, command, output)
