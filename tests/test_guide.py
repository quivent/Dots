"""Guides are rendered locally and all terminal aliases describe the same workflow."""
from contextlib import redirect_stdout, redirect_stderr
import io
import unittest
from unittest.mock import patch

from rich.console import Console
from cli.guide import GUIDES, render
from cli.main import main


class GuideTests(unittest.TestCase):
    def invoke(self, arguments, color=False):
        stream = io.StringIO()
        terminal = Console(file=stream, width=100, force_terminal=color,
                           no_color=False, color_system='truecolor' if color else None)
        with patch('cli.ui.console', terminal), patch('cli.guide.console', terminal), \
                redirect_stdout(stream), redirect_stderr(stream):
            try:
                code = main(arguments)
            except SystemExit as error:
                code = error.code
        return code, stream.getvalue()

    @patch('cli.sources.DotClient')
    @patch('subprocess.Popen')
    def test_overview_lists_interfaces_without_services_or_model_access(self, process, client):
        code, text = self.invoke(['guide'])
        self.assertEqual(code, 0)
        for interface in ('terminal', 'desktop', 'mobile', 'sources'):
            self.assertIn('dots guide ' + interface, text)
        client.assert_not_called()
        process.assert_not_called()

    def test_terminal_aliases_render_the_same_guide(self):
        canonical = self.invoke(['guide', 'terminal'])
        self.assertEqual(canonical[0], 0)
        for args in (['terminal'], ['terminal', 'guide'], ['terminal', '--help'], ['terminal', 'guide', '--help']):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(args), canonical)
        self.assertIn('dots import --source chatgpt', canonical[1])
        self.assertIn('/wait', canonical[1])
        self.assertIn('allowance', canonical[1])

    def test_plain_option_preserves_original_markdown_for_piping(self):
        for args in (['guide', 'terminal', '--plain'], ['terminal', 'guide', '--plain'], ['terminal', '--plain', 'guide']):
            code, text = self.invoke(args)
            self.assertEqual(code, 0)
            self.assertEqual(text, GUIDES['terminal'])
            self.assertIn('```sh', text)
            self.assertNotIn('\x1b', text)

    def test_rendering_has_color_in_a_terminal_and_honors_no_color(self):
        _, colored = self.invoke(['guide', 'terminal'], color=True)
        self.assertIn('\x1b[', colored)
        for args in (['--no-color', 'guide', 'terminal'], ['--no-color', 'terminal', '--help']):
            code, plain = self.invoke(args, color=True)
            self.assertEqual(code, 0)
            self.assertNotIn('\x1b', plain)

    def test_every_interface_is_available_as_raw_markdown(self):
        for interface in GUIDES:
            with self.subTest(interface=interface):
                self.assertEqual(self.invoke(['guide', interface, '--plain']), (0, GUIDES[interface]))

    def test_unknown_interface_returns_help_without_running_any_action(self):
        code, text = self.invoke(['guide', 'unknown'])
        self.assertEqual(code, 2)
        self.assertIn('dots guide --help', text)
