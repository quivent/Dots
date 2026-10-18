from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from dots_cli.cli import main, Launcher


class CloudCliTests(unittest.TestCase):
    def invoke(self, argv):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            try:
                code = main(argv)
            except SystemExit as error:
                code = error.code
        return code, output.getvalue()

    @patch('dots_cli.cloud.DotClient')
    def test_list_defaults_to_account(self, client):
        client.return_value.list.return_value = [{'id': 'dot1', 'display_name': 'Research'}]
        code, output = self.invoke(['list', '--json'])
        self.assertEqual(code, 0)
        self.assertIn('dot1', output)
        client.return_value.list.assert_called_once()

    @patch('dots_cli.cloud.DotClient')
    @patch('dots_cli.cli.Launcher')
    def test_local_list_is_independent_of_cloud_auth(self, launcher, client):
        launcher.return_value.list_dots.return_value = []
        code, output = self.invoke(['list', '--local', '--json'])
        self.assertEqual(code, 0)
        self.assertIn('local_registry', output)
        client.assert_not_called()

    @patch('dots_cli.cloud.DotClient')
    def test_room_repair_is_explicit_single_write(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {'messaging_room_id': 'room'}
        code, _ = self.invoke(['room', 'one', '--json'])
        self.assertEqual(code, 0)
        client.return_value.request.assert_called_once_with('POST', '/tbo/one/messaging-room')
        client.return_value.create.assert_not_called()

    @patch('dots_cli.cloud.DotClient')
    def test_task_detail_encodes_task_id(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {}
        code, _ = self.invoke(['tasks', 'one', '--task', 'task/id', '--json'])
        self.assertEqual(code, 0)
        client.return_value.request.assert_called_once_with('GET', '/tbo/one/tasks/task%2Fid')

    @patch('dots_cli.cloud.DotClient')
    def test_inspection_by_id_does_not_depend_on_catalog(self, client):
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {'id': 'one'}
        code, _ = self.invoke(['show', 'one', '--by-id', '--json'])
        self.assertEqual(code, 0)
        client.return_value.resolve.assert_not_called()
        client.return_value.list.assert_not_called()
        client.return_value.request.assert_called_once_with('GET', '/tbo/one')

    @patch('dots_cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('dots_cli.api.DotClient')
    def test_check_verifies_reads_without_writing_or_launching(self, client, credential):
        client.return_value.list.return_value = []
        with patch('dots_cli.cli.Launcher') as launcher:
            code, output = self.invoke(['check', '--json'])
        self.assertEqual(code, 0)
        self.assertIn('"read_access_verified": true', output)
        self.assertIn('"write_access_verified": false', output)
        self.assertNotIn('fixture-token', output)
        client.return_value.create.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    @patch('dots_cli.api.credentials', return_value=('', '', 'none'))
    @patch('dots_cli.api.DotClient')
    def test_check_missing_login_never_calls_api(self, client, credential):
        code, output = self.invoke(['check', '--json'])
        self.assertEqual(code, 1)
        self.assertIn('sign-in', output)
        client.assert_not_called()

    @patch('dots_cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('dots_cli.api.DotClient')
    def test_corrupt_local_settings_do_not_block_cloud_check(self, client, credential):
        client.return_value.list.return_value = []
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'dots-launcher.json').write_text('{broken', encoding='utf-8')
            with patch('dots_cli.cli.Launcher', return_value=Launcher(runtime=base)):
                code, _ = self.invoke(['check', '--json'])
        self.assertEqual(code, 0)

    @patch('dots_cli.cli.Launcher')
    def test_setup_only_opens_onboarding(self, launcher):
        launcher.return_value.launch.return_value = {'message': 'Dot onboarding launch requested.'}
        code, output = self.invoke(['setup'])
        self.assertEqual(code, 0)
        launcher.return_value.launch.assert_called_once_with('setup')
        self.assertIn('onboarding', output)

    @patch('dots_cli.cloud.credentials', return_value=('', '', 'none'))
    @patch('dots_cli.auth.sign_in', return_value=('fixture-token', 'fixture-account'))
    @patch('dots_cli.cloud.DotClient')
    def test_auth_starts_login_when_missing(self, client, sign_in, credential):
        client.return_value.list.return_value = []
        code, output = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_called_once()
        client.return_value.list.assert_called_once()
        client.return_value.create.assert_not_called()
        self.assertNotIn('fixture-token', output)

    @patch('dots_cli.cloud.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('dots_cli.auth.sign_in')
    @patch('dots_cli.cloud.DotClient')
    def test_auth_reuses_login_without_launching_oauth_again(self, client, sign_in, credential):
        client.return_value.list.return_value = []
        code, output = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_not_called()
        self.assertIn('Authenticated', output)

    @patch('dots_cli.cloud.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('dots_cli.auth.sign_in', return_value=('new-fixture-token', 'fixture-account'))
    @patch('dots_cli.cloud.DotClient')
    def test_auth_can_replace_rejected_existing_login(self, client, sign_in, credential):
        from dots_cli.api import ApiError
        client.return_value.list.side_effect = [ApiError('expired', status=401), []]
        code, _ = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_called_once()
        client.return_value.create.assert_not_called()

    @patch('dots_cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('dots_cli.auth.sign_in')
    @patch('dots_cli.api.DotClient')
    def test_check_does_not_sign_in_if_existing_login_is_rejected(self, client, sign_in, credential):
        from dots_cli.api import ApiError
        client.return_value.list.side_effect = ApiError('expired', status=401)
        code, _ = self.invoke(['check'])
        self.assertEqual(code, 1)
        sign_in.assert_not_called()

    def test_root_help_includes_expanded_commands(self):
        code, output = self.invoke(['--help'])
        self.assertEqual(code, 0)
        for command in ['check', 'auth', 'show', 'tasks', 'pause', 'resume', 'room']:
            self.assertIn(command, output)
