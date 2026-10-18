import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from rich.console import Console
from dots_cli.update import SOURCE, update
from dots_cli.workflow import execute_step


class UpdateTests(unittest.TestCase):
    @patch('dots_cli.update.venv.EnvBuilder')
    @patch('dots_cli.update.subprocess.run')
    def test_update_targets_running_interpreter_even_without_pip(self, run, builder):
        with patch('dots_cli.ui.console', Console(file=io.StringIO())):
            self.assertEqual(update(), 0)
        builder.assert_called_once_with(with_pip=True)
        builder.return_value.create.assert_called_once()
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[1:5], ['-m', 'pip', '--python', sys.executable])
        self.assertIn('--force-reinstall', command)
        self.assertEqual(command[-1], SOURCE)
        run.assert_called_with([sys.executable, '-m', 'dots_cli', '--version'],
                               cwd=Path(sys.executable).parent, check=True)

    @patch('dots_cli.update.venv.EnvBuilder')
    @patch('dots_cli.update.subprocess.run')
    def test_failed_install_never_reports_success(self, run, builder):
        run.side_effect = [None, subprocess.CalledProcessError(1, ['pip'])]
        stream = io.StringIO()
        with patch('dots_cli.ui.console', Console(file=stream)):
            self.assertEqual(update(), 1)
        self.assertNotIn('Dots CLI updated.', stream.getvalue())
        self.assertEqual(run.call_count, 2)

    @patch('subprocess.run')
    def test_setup_steps_start_fresh_installed_code(self, run):
        run.return_value.returncode = 7
        self.assertEqual(execute_step(['preflight']), 7)
        run.assert_called_once_with([sys.executable, '-m', 'dots_cli', 'preflight'],
                                    cwd=Path(sys.executable).parent)
