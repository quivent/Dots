import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from rich.console import Console
from dots_cli import __version__
from dots_cli.update import SOURCE, update, latest_version
from dots_cli.workflow import execute_step


class UpdateTests(unittest.TestCase):
    def invoke(self):
        stream = io.StringIO()
        with patch('dots_cli.ui.console', Console(file=stream)):
            result = update()
        return result, stream.getvalue()

    @patch('dots_cli.update.latest_version', return_value=__version__)
    @patch('dots_cli.update.venv.EnvBuilder')
    @patch('dots_cli.update.subprocess.run')
    def test_current_version_does_not_build_or_install(self, run, builder, latest):
        code, output = self.invoke()
        self.assertEqual(code, 0)
        self.assertIn('up to date', output)
        builder.assert_not_called()
        run.assert_not_called()

    @patch('dots_cli.update.latest_version', return_value='0.0.1')
    @patch('dots_cli.update.subprocess.run')
    def test_newer_local_version_is_not_downgraded(self, run, latest):
        self.assertEqual(self.invoke()[0], 0)
        run.assert_not_called()

    @patch.dict('os.environ', {'PYTHONPATH': '/unrelated/source', 'PYTHONHOME': '/unrelated/python'})
    @patch('dots_cli.update.latest_version', return_value='9.0.0')
    @patch('dots_cli.update.venv.EnvBuilder')
    @patch('dots_cli.update.subprocess.run')
    def test_updates_running_interpreter_without_forcing_dependencies(self, run, builder, latest):
        run.return_value.stdout = 'dots 9.0.0\n'
        code, output = self.invoke()
        self.assertEqual(code, 0)
        builder.assert_called_once_with(with_pip=True)
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[1:5], ['-m', 'pip', '--python', sys.executable])
        self.assertNotIn('--force-reinstall', command)
        self.assertNotIn('--no-cache-dir', command)
        self.assertEqual(command[-1], SOURCE)
        self.assertTrue(run.call_args_list[1].kwargs['capture_output'])
        environment = run.call_args_list[1].kwargs['env']
        self.assertNotIn('PYTHONPATH', environment)
        self.assertNotIn('PYTHONHOME', environment)
        self.assertIn('updated to 9.0.0', output)

    @patch('dots_cli.update.latest_version', return_value='9.0.0')
    @patch('dots_cli.update.venv.EnvBuilder')
    @patch('dots_cli.update.subprocess.run')
    def test_failed_install_is_concise_and_never_reports_success(self, run, builder, latest):
        run.side_effect = [None, subprocess.CalledProcessError(1, ['pip'], stderr='noise\n' * 50 + 'Actual failure')]
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertNotIn('updated to', output)
        self.assertIn('Actual failure', output)
        self.assertLess(len(output.splitlines()), 16)
        self.assertEqual(run.call_count, 2)

    @patch('dots_cli.update.latest_version', return_value='9.0.0')
    @patch('dots_cli.update.venv.EnvBuilder')
    @patch('dots_cli.update.subprocess.run')
    def test_old_version_after_install_is_not_success(self, run, builder, latest):
        run.return_value.stdout = 'dots 0.0.1\n'
        self.assertEqual(self.invoke()[0], 1)

    @patch('dots_cli.update.latest_version', side_effect=OSError('Network unavailable'))
    @patch('dots_cli.update.venv.EnvBuilder')
    def test_network_failure_does_not_start_install(self, builder, latest):
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('Network unavailable', output)
        builder.assert_not_called()

    @patch('dots_cli.update.urlopen')
    def test_remote_version_is_validated(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b"__version__ = '0.2.10'\n"
        self.assertEqual(latest_version(), '0.2.10')
        response.read.return_value = b'<html>proxy error</html>'
        with self.assertRaises(ValueError):
            latest_version()

    @patch('subprocess.run')
    def test_setup_steps_start_fresh_installed_code(self, run):
        run.return_value.returncode = 7
        self.assertEqual(execute_step(['preflight']), 7)
        run.assert_called_once_with([sys.executable, '-m', 'dots_cli', 'preflight'],
                                    cwd=Path(sys.executable).parent)
