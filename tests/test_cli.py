from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from cli.main import Launcher, PROJECT, main


has = unittest.TestCase.assertIn


class CliTests(unittest.TestCase):
    def test_prepare_dry_run_has_no_clipboard_launch_or_runtime_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runner = Mock()
            launcher = Launcher(runtime=base / 'runtime', runner=runner, app=base / 'missing.app', platform='darwin')
            result = launcher.prepare('A task', dry_run=True)
            self.assertEqual([c['argv'][0] for c in result['commands']], ['/usr/bin/pbcopy', '/usr/bin/open'])
            self.assertFalse(result['submitted'])
            self.assertFalse((base / 'runtime').exists())
            runner.assert_not_called()

    def test_local_readiness_does_not_claim_account_or_connection_access(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runner = Mock()
            launcher = Launcher(runtime=base / 'runtime', runner=runner, app=base / 'missing.app', platform='darwin')
            result = launcher.local_readiness()
            self.assertFalse(result['app_available'])
            self.assertFalse(result['conversation_saved'])
            self.assertTrue(result['presets_available'])
            self.assertFalse((base / 'runtime').exists())
            runner.assert_not_called()

    def test_no_arguments_prints_help(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([]), 0)
        has(self, '▸ Setup', output.getvalue())
        for command in ['create','list','use','activity','web','doctor','configure']:
            has(self, command, output.getvalue())

    @patch('cli.server.serve')
    @patch('cli.main.Launcher')
    def test_web_runs_local_server_with_its_options(self, launcher, serve):
        self.assertEqual(main(['web', '--port', '0', '--no-open']), 0)
        serve.assert_called_once_with(launcher.return_value, port=0, open_browser=False)

    def test_removed_commands_are_not_registered(self):
        for name in ['serve', 'folder']:
            with self.subTest(command=name), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main([name])
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
