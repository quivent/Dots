from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from dots_cli.cli import Launcher, main


class DiagnosticsTests(unittest.TestCase):
    @patch('dots_cli.api.credentials', return_value=('', '', 'none'))
    @patch('dots_cli.api.DotClient')
    @patch('dots_cli.auth.sign_in')
    def test_preflight_reports_missing_auth_without_starting_login_or_creating_files(self, sign_in, client, credentials):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            launcher = Launcher(project=base / 'workspace', runtime=base / 'runtime', runner=Mock())
            out = io.StringIO()
            with patch('dots_cli.cli.Launcher', return_value=launcher), redirect_stdout(out):
                self.assertEqual(main(['preflight', '--json']), 0)
            data = json.loads(out.getvalue())
            self.assertEqual(data['connection'], 'auth_required')
            self.assertFalse(data['read_access_verified'])
            self.assertFalse(launcher.project.exists())
            self.assertFalse(launcher.runtime.exists())
            launcher.runner.assert_not_called()
            sign_in.assert_not_called()
            client.assert_not_called()

    @patch('dots_cli.api.credentials', return_value=('fixture-token', 'fixture-account', 'existing ChatGPT sign-in'))
    @patch('dots_cli.api.DotClient')
    @patch('dots_cli.diagnostics.executable', return_value='/mock/codex')
    def test_doctor_adds_full_diagnostics_and_keeps_independent_checks(self, executable, client, credentials):
        client.return_value.list.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'dots-launcher.json').write_text('{broken', encoding='utf-8')
            launcher = Launcher(project=base / 'workspace', runtime=base, runner=Mock())
            out = io.StringIO()
            with patch('dots_cli.cli.Launcher', return_value=launcher), redirect_stdout(out):
                self.assertEqual(main(['doctor', '--json']), 1)
            data = json.loads(out.getvalue())
            self.assertEqual(data['connection'], 'ready')
            diagnostics = {item['check']: item for item in data['diagnostics']}
            self.assertEqual(diagnostics['Settings']['state'], 'error')
            self.assertEqual(diagnostics['Guide assets']['state'], 'ready')
            self.assertEqual(diagnostics['App server']['state'], 'ready')
            self.assertNotIn('fixture-token', out.getvalue())
            self.assertNotIn('fixture-account', out.getvalue())
            self.assertFalse(launcher.project.exists())
            launcher.runner.assert_not_called()

    def test_old_check_command_is_removed_from_interface(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out), self.assertRaises(SystemExit) as error:
            main(['check'])
        self.assertEqual(error.exception.code, 2)
        self.assertIn('invalid choice', out.getvalue())
