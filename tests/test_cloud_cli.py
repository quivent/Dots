from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from dots_cli.cli import main, Launcher
from dots_cli.setup import run_step


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

    @patch('dots_cli.setup.credentials', return_value=('', '', 'none'))
    def test_corrupt_shortcut_settings_do_not_hide_working_setup_parts(self, credentials):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'dots-launcher.json').write_text('{broken', encoding='utf-8')
            launcher = Launcher(runtime=base, app=base / 'missing')
            result = run_step('check', launcher)
            self.assertEqual(result['checks'][3]['state'], 'available')
            self.assertIn('needs repair', result['checks'][4]['state'])
            self.assertEqual(result['checks'][5]['state'], 'ready')

    @patch('dots_cli.setup.DotClient')
    @patch('dots_cli.setup.credentials', return_value=('', '', 'none'))
    def test_setup_check_runs_without_cloud_or_launching(self, credentials, client):
        with tempfile.TemporaryDirectory() as folder:
            runner = Mock()
            launcher = Launcher(runtime=Path(folder) / 'runtime', runner=runner, app=Path(folder) / 'missing')
            result = run_step('check', launcher)
            self.assertEqual(result['checks'][2]['state'], 'missing')
            self.assertEqual(result['checks'][3]['state'], 'available')
            self.assertFalse(result['api_checked'])
            self.assertFalse((Path(folder) / 'runtime').exists())
            client.assert_not_called()
            runner.assert_not_called()

    @patch('dots_cli.setup.DotClient')
    def test_setup_api_check_never_creates_a_dot(self, client):
        client.return_value.list.return_value = []
        result = run_step('api', Mock())
        self.assertTrue(result['read_access_verified'])
        self.assertFalse(result['write_access_verified'])
        client.return_value.create.assert_not_called()

    @patch('dots_cli.setup.credentials', return_value=('', '', 'none'))
    def test_setup_auth_is_independent_and_read_only(self, credentials):
        launcher = Mock()
        self.assertFalse(run_step('auth', launcher)['verified'])
        launcher.launch.assert_not_called()

    def test_root_help_includes_expanded_commands(self):
        code, output = self.invoke(['--help'])
        self.assertEqual(code, 0)
        for command in ['auth', 'show', 'tasks', 'pause', 'resume', 'room']:
            self.assertIn(command, output)
