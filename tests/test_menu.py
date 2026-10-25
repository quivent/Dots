from contextlib import redirect_stdout, redirect_stderr
import io
import json
import unittest
from unittest.mock import Mock, patch, call

from rich.console import Console
from cli.main import main
from cli.workflow import run_setup


has = unittest.TestCase.assertIn


class MenuTests(unittest.TestCase):
    def invoke(self, args, color=False):
        stream = io.StringIO()
        console = Console(file=stream, force_terminal=color, no_color=not color, width=100)
        with patch('cli.ui.console', console), redirect_stdout(stream), redirect_stderr(stream):
            try:
                result = main(args)
            except SystemExit as error:
                result = error.code
        return result, stream.getvalue()

    @patch('cli.main.Launcher')
    @patch('cli.cloud.DotClient')
    def test_main_menu_is_grouped_and_side_effect_free(self, client, launcher):
        code, output = self.invoke([])
        self.assertEqual(code, 0)
        self.assertLess(output.index('▸ Setup'), output.index('▸ Dots'))
        self.assertLess(output.index('▸ Dots'), output.index('▸ Manage'))
        has(self, '  ├─ dots setup', output)
        has(self, 'dots setup run', output)
        self.assertLess(output.index('dots setup'), output.index('dots update'))
        has(self, 'dots setup onboard', output)
        client.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    def test_colors_and_no_color_are_honored(self):
        _, colored = self.invoke([], color=True)
        _, plain = self.invoke(['--no-color'], color=True)
        has(self, '\x1b[', colored)
        self.assertNotIn('\x1b[', plain)

    @patch('cli.main.Launcher')
    @patch('cli.workflow.run_setup')
    def test_wrong_commands_get_consistent_corrections_without_execution(self, run, launcher):
        cases = [
            (['setup', 'steps'], 'Unknown command: dots setup steps', 'Try: dots installation'),
            (['instalation'], 'Unknown command: dots instalation', 'Try: dots installation'),
            (['setup', 'ru'], 'Unknown command: dots setup ru', 'Try: dots setup run'),
            (['setup', 'nonsense'], 'Unknown command: dots setup nonsense', 'Help: dots setup --help'),
        ]
        for arguments, error, correction in cases:
            with self.subTest(arguments=arguments):
                code, output = self.invoke(arguments)
                self.assertEqual(code, 2)
                self.assertEqual(output.splitlines(), [error, correction])
        run.assert_not_called()
        launcher.assert_not_called()

    def test_bad_options_get_concise_help_on_stderr(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            main(['installation', '--bogus'])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(stdout.getvalue(), '')
        has(self, 'Error: unrecognized arguments: --bogus', stderr.getvalue())
        self.assertEqual(len(stderr.getvalue().splitlines()), 2)
        self.assertNotIn('Usage:', stderr.getvalue())

    @patch('cli.main.Launcher')
    @patch('cli.cloud.DotClient')
    def test_setup_lists_exact_steps_without_executing_them(self, client, launcher):
        code, output = self.invoke(['setup', '--json'])
        data = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(data['run'], 'dots setup run')
        self.assertEqual([step['command'] for step in data['steps']], ['dots update', 'dots preflight', 'dots auth', 'dots list --source chatgpt', 'dots create NAME', None, None, 'dots room DOT', 'dots use DOT', 'dots show DOT'])
        self.assertEqual(data['run_scope'], 'prerequisites only')
        self.assertEqual(data['steps'][5]['status'], 'bundled')
        self.assertEqual(data['steps'][6]['via'], 'dots create NAME')
        self.assertEqual(data['steps'][7]['status'], 'conditional')
        self.assertEqual(data['steps'][8]['status'], 'optional')
        client.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    @patch('cli.workflow.run_setup')
    @patch('cli.main.Launcher')
    @patch('cli.cloud.DotClient')
    def test_installation_matches_setup_without_executing(self, client, launcher, run):
        for suffix in ([], ['--json']):
            with self.subTest(suffix=suffix):
                code, output = self.invoke(['installation', *suffix])
                default_code, default_output = self.invoke(['setup', *suffix])
                self.assertEqual(code, 0)
                self.assertEqual((code, output), (default_code, default_output))
                has(self, 'dots update', output)
                has(self, 'dots preflight', output)
                has(self, 'dots auth', output)
        run.assert_not_called()
        client.assert_not_called()
        launcher.return_value.launch.assert_not_called()

    @patch('cli.workflow.run_setup')
    def test_setup_run_requires_explicit_action(self, run):
        run.return_value = 0
        code, _ = self.invoke(['setup', 'run'])
        self.assertEqual(code, 0)
        run.assert_called_once_with()

    def test_runner_executes_only_prerequisites_without_creation_or_browser(self):
        execute = Mock(return_value=0)
        with patch('cli.ui.console', Console(file=io.StringIO())):
            self.assertEqual(run_setup(execute), 0)
        self.assertEqual(execute.call_args_list, [call(['update']), call(['preflight']), call(['auth']), call(['list', '--source', 'chatgpt'])])

    def test_failed_step_stops_pipeline_and_names_the_independent_command(self):
        execute = Mock(side_effect=[0, 7])
        stream = io.StringIO()
        with patch('cli.ui.console', Console(file=stream)):
            self.assertEqual(run_setup(execute), 7)
        self.assertEqual(execute.call_count, 2)
        has(self, 'stopped at dots preflight', stream.getvalue())
        has(self, 'independently', stream.getvalue())

    @patch('cli.workflow.run_setup')
    def test_interactive_run_rejects_json_before_any_execution(self, run):
        code, output = self.invoke(['setup', 'run', '--json'])
        self.assertEqual(code, 1)
        has(self, 'interactive', output)
        run.assert_not_called()
