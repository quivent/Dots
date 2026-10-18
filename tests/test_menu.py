from contextlib import redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import Mock, patch, call

from rich.console import Console
from dots_cli.cli import main
from dots_cli.workflow import run_setup


class MenuTests(unittest.TestCase):
    def invoke(self, args, color=False):
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=color, no_color=not color, width=100)
        with patch('dots_cli.ui.console', console), redirect_stdout(stream), redirect_stderr(stream):
            result = main(args)
        return result, stream.getvalue()

    @patch('dots_cli.cli.Launcher')
    @patch('dots_cli.cloud.DotClient')
    def test_main_menu_is_grouped_and_side_effect_free(self, client, launcher):
        code, output = self.invoke([])
        self.assertEqual(code, 0)
        self.assertLess(output.index('▸ Setup'), output.index('▸ Dots'))
        self.assertLess(output.index('▸ Dots'), output.index('▸ Manage'))
        self.assertIn('  ├─ dots setup', output)
        self.assertIn('dots setup run', output)
        self.assertIn('dots setup onboard', output)
        client.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    def test_colors_and_no_color_are_honored(self):
        _, colored = self.invoke([], color=True)
        _, plain = self.invoke(['--no-color'], color=True)
        self.assertIn('\x1b[', colored)
        self.assertNotIn('\x1b[', plain)

    @patch('dots_cli.cli.Launcher')
    @patch('dots_cli.cloud.DotClient')
    def test_setup_lists_exact_steps_without_executing_them(self, client, launcher):
        code, output = self.invoke(['setup', '--json'])
        data = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(data['run'], 'dots setup run')
        self.assertEqual([step['command'] for step in data['steps']], ['dots preflight', 'dots auth', 'dots setup onboard'])
        client.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    @patch('dots_cli.workflow.run_setup')
    def test_setup_run_requires_explicit_action(self, run):
        run.return_value = 0
        code, _ = self.invoke(['setup', 'run'])
        self.assertEqual(code, 0)
        run.assert_called_once_with(main)

    def test_runner_runs_only_the_listed_commands(self):
        execute = Mock(return_value=0)
        with patch('dots_cli.ui.console', Console(file=io.StringIO())):
            self.assertEqual(run_setup(execute), 0)
        self.assertEqual(execute.call_args_list, [call(['preflight']), call(['auth']), call(['setup', 'onboard'])])

    def test_failed_step_stops_pipeline_and_names_the_independent_command(self):
        execute = Mock(side_effect=[0, 7])
        stream = io.StringIO()
        with patch('dots_cli.ui.console', Console(file=stream)):
            self.assertEqual(run_setup(execute), 7)
        self.assertEqual(execute.call_count, 2)
        self.assertIn('stopped at dots auth', stream.getvalue())
        self.assertIn('independently', stream.getvalue())

    @patch('dots_cli.workflow.run_setup')
    def test_interactive_run_rejects_json_before_any_execution(self, run):
        code, output = self.invoke(['setup', 'run', '--json'])
        self.assertEqual(code, 1)
        self.assertIn('interactive', output)
        run.assert_not_called()
