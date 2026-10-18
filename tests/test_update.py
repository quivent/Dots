import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rich.console import Console
from dots_cli import __version__
from dots_cli.update import SOURCE, update, latest_version, install, report_failure
from dots_cli.workflow import execute_step


class UpdateTests(unittest.TestCase):
    def invoke(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            def private_log(**kwargs):
                return tempfile.mkstemp(dir=directory, **kwargs)
            with patch('dots_cli.ui.console', Console(file=stream)), patch('dots_cli.update.mkstemp', side_effect=private_log):
                result = update()
        return result, stream.getvalue()

    @patch('dots_cli.update.latest_version', return_value=__version__)
    @patch('dots_cli.update.install')
    @patch('dots_cli.update.subprocess.run')
    def test_current_version_does_not_install_or_spawn(self, run, installer, latest):
        code, output = self.invoke()
        self.assertEqual(code, 0)
        self.assertIn('up to date', output)
        self.assertEqual(len(output.splitlines()), 1)
        installer.assert_not_called()
        run.assert_not_called()

    @patch('dots_cli.update.latest_version', return_value='0.0.1')
    @patch('dots_cli.update.install')
    def test_newer_local_version_is_not_downgraded(self, installer, latest):
        self.assertEqual(self.invoke()[0], 0)
        installer.assert_not_called()

    @patch.dict('os.environ', {'PYTHONPATH': '/unrelated/source', 'PYTHONHOME': '/unrelated/python'})
    @patch('dots_cli.update.latest_version', return_value='9.0.0')
    @patch('dots_cli.update.install')
    @patch('dots_cli.update.subprocess.run')
    def test_update_hides_all_output_and_checks_installed_version(self, run, installer, latest):
        run.return_value.stdout = 'dots 9.0.0\n'
        run.return_value.stderr = 'UNWANTED OUTPUT\n' * 100
        code, output = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 1)
        environment = installer.call_args.args[0]
        self.assertNotIn('PYTHONPATH', environment)
        self.assertNotIn('PYTHONHOME', environment)
        self.assertTrue(run.call_args.kwargs['capture_output'])
        self.assertIn('updated to 9.0.0', output)
        self.assertNotIn('UNWANTED', output)
        self.assertEqual(len(output.splitlines()), 1)

    @patch('dots_cli.update.shutil.which', return_value='/tools/uv')
    @patch('dots_cli.update.find_spec')
    @patch('dots_cli.update.subprocess.run')
    def test_uv_is_one_install_command_without_environment_or_pip_bootstrap(self, run, spec, which):
        install({})
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ['/tools/uv', 'pip', 'install', '--quiet', '--python', sys.executable])
        self.assertIn('--upgrade-package', command)
        self.assertNotIn('--upgrade', command)
        self.assertNotIn('--force-reinstall', command)
        self.assertEqual(command[-1], SOURCE)
        self.assertTrue(run.call_args.kwargs['capture_output'])
        spec.assert_not_called()

    @patch('dots_cli.update.shutil.which', return_value=None)
    @patch('dots_cli.update.find_spec', return_value=object())
    @patch('dots_cli.update.subprocess.run')
    def test_existing_pip_is_one_install_command(self, run, spec, which):
        install({})
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, '-m', 'pip'])
        self.assertNotIn('--force-reinstall', command)
        self.assertNotIn('--no-cache-dir', command)
        self.assertEqual(command[-1], SOURCE)

    @patch('dots_cli.update.shutil.which', return_value=None)
    @patch('dots_cli.update.find_spec', return_value=None)
    @patch('dots_cli.update.subprocess.run')
    def test_bootstrap_only_when_no_installer_exists(self, run, spec, which):
        install({})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable, '-m', 'ensurepip', '--upgrade'])
        for invocation in run.call_args_list:
            self.assertTrue(invocation.kwargs['capture_output'])

    @patch('dots_cli.update.latest_version', return_value='9.0.0')
    @patch('dots_cli.update.install', side_effect=subprocess.CalledProcessError(1, ['pip'], stderr='RAW INSTALLER ERROR\n' * 100))
    def test_failed_install_never_prints_raw_output(self, installer, latest):
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertNotIn('updated to', output)
        self.assertNotIn('RAW INSTALLER ERROR', output)
        self.assertIn('Update log:', output)
        self.assertLessEqual(len(output.splitlines()), 4)

    def test_error_details_only_in_private_log(self):
        stream = io.StringIO()
        error = subprocess.CalledProcessError(1, ['pip'], stderr='PRIVATE FAILURE DETAILS')
        with tempfile.TemporaryDirectory() as directory:
            def private_log(**kwargs):
                return tempfile.mkstemp(dir=directory, **kwargs)
            with patch('dots_cli.update.mkstemp', side_effect=private_log):
                report_failure(Console(file=stream, width=200), error)
            logs = list(Path(directory).glob('*.log'))
            self.assertEqual(len(logs), 1)
            self.assertIn('PRIVATE FAILURE DETAILS', logs[0].read_text())
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(logs[0].stat().st_mode), 0o600)
        self.assertNotIn('PRIVATE FAILURE DETAILS', stream.getvalue())

    @patch('dots_cli.update.latest_version', return_value='9.0.0')
    @patch('dots_cli.update.install')
    @patch('dots_cli.update.subprocess.run')
    def test_old_version_after_install_is_not_success(self, run, installer, latest):
        run.return_value.stdout = 'dots 0.0.1\n'
        self.assertEqual(self.invoke()[0], 1)

    @patch('dots_cli.update.latest_version', side_effect=OSError('RAW NETWORK ERROR'))
    @patch('dots_cli.update.install')
    def test_network_failure_does_not_start_install_or_dump_error(self, installer, latest):
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertNotIn('RAW NETWORK ERROR', output)
        installer.assert_not_called()

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
