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
from cli import __version__
from cli.update import SOURCE, update, latest_version, install, report_failure
from cli.workflow import execute_step
from cli.install import pip_command


has = unittest.TestCase.assertIn


class UpdateTests(unittest.TestCase):
    def invoke(self):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            def private_log(**kwargs):
                return tempfile.mkstemp(dir=directory, **kwargs)
            with patch('cli.ui.console', Console(file=stream)), patch('cli.update.mkstemp', side_effect=private_log):
                result = update()
        return result, stream.getvalue()

    @patch('cli.update.latest_version', return_value=__version__)
    @patch('cli.update.install')
    @patch('cli.update.subprocess.run')
    def test_current_version_does_not_install_or_spawn(self, run, installer, latest):
        code, output = self.invoke()
        self.assertEqual(code, 0)
        has(self, 'up to date', output)
        self.assertEqual(len(output.splitlines()), 1)
        installer.assert_not_called()
        run.assert_not_called()

    @patch('cli.update.latest_version', return_value='0.0.1')
    @patch('cli.update.install')
    def test_newer_local_version_is_not_downgraded(self, installer, latest):
        self.assertEqual(self.invoke()[0], 0)
        installer.assert_not_called()

    @patch.dict('os.environ', {'PYTHONPATH': '/unrelated/source', 'PYTHONHOME': '/unrelated/python'})
    @patch('cli.update.latest_version', return_value='9.0.0')
    @patch('cli.update.install')
    @patch('cli.update.subprocess.run')
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
        has(self, 'updated to 9.0.0', output)
        self.assertNotIn('UNWANTED', output)
        self.assertEqual(len(output.splitlines()), 1)

    def test_install_policy_targets_user_python_or_active_environment(self):
        with patch('cli.install.sys.prefix', sys.base_prefix):
            command = pip_command(SOURCE, upgrade=True)
            has(self, '--user', command)
            has(self, '--break-system-packages', command)
            has(self, '--upgrade', command)
        with patch('cli.install.sys.prefix', '/active/venv'):
            command = pip_command(SOURCE)
            self.assertNotIn('--user', command)
            self.assertNotIn('--break-system-packages', command)

    @patch('cli.update.find_spec', return_value=object())
    @patch('cli.update.subprocess.run')
    def test_existing_pip_is_one_install_command(self, run, spec):
        install({})
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [sys.executable, '-m', 'pip'])
        self.assertNotIn('--force-reinstall', command)
        self.assertNotIn('--no-cache-dir', command)
        self.assertEqual(command[-1], SOURCE)

    @patch('cli.update.find_spec', return_value=None)
    @patch('cli.update.subprocess.run')
    def test_bootstrap_only_when_no_installer_exists(self, run, spec):
        install({})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], [sys.executable, '-m', 'ensurepip', '--upgrade'])
        for invocation in run.call_args_list:
            self.assertTrue(invocation.kwargs['capture_output'])

    @patch('cli.update.latest_version', return_value='9.0.0')
    @patch('cli.update.install', side_effect=subprocess.CalledProcessError(1, ['pip'], stderr='RAW INSTALLER ERROR\n' * 100))
    def test_failed_install_never_prints_raw_output(self, installer, latest):
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertNotIn('updated to', output)
        self.assertNotIn('RAW INSTALLER ERROR', output)
        has(self, 'Update log:', output)
        self.assertLessEqual(len(output.splitlines()), 4)

    def test_error_details_only_in_private_log(self):
        stream = io.StringIO()
        error = subprocess.CalledProcessError(1, ['pip'], stderr='PRIVATE FAILURE DETAILS')
        with tempfile.TemporaryDirectory() as directory:
            def private_log(**kwargs):
                return tempfile.mkstemp(dir=directory, **kwargs)
            with patch('cli.update.mkstemp', side_effect=private_log):
                report_failure(Console(file=stream, width=200), error)
            logs = list(Path(directory).glob('*.log'))
            self.assertEqual(len(logs), 1)
            has(self, 'PRIVATE FAILURE DETAILS', logs[0].read_text())
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(logs[0].stat().st_mode), 0o600)
        self.assertNotIn('PRIVATE FAILURE DETAILS', stream.getvalue())

    @patch('cli.update.latest_version', return_value='9.0.0')
    @patch('cli.update.install')
    @patch('cli.update.subprocess.run')
    def test_old_version_after_install_is_not_success(self, run, installer, latest):
        run.return_value.stdout = 'dots 0.0.1\n'
        self.assertEqual(self.invoke()[0], 1)

    @patch('cli.update.latest_version', side_effect=OSError('RAW NETWORK ERROR'))
    @patch('cli.update.install')
    def test_network_failure_does_not_start_install_or_dump_error(self, installer, latest):
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertNotIn('RAW NETWORK ERROR', output)
        installer.assert_not_called()

    @patch('cli.update.urlopen')
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
        run.assert_called_once_with([sys.executable, '-m', 'cli', 'preflight'],
                                    cwd=Path(sys.executable).parent)
