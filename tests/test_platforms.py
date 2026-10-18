from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from cli.cli import Launcher


class WindowsPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
        self.launcher = Launcher(runtime=self.base / 'runtime', runner=self.runner,
                                 app=self.base / 'missing.exe', platform='win32')

    def test_setup_and_saved_conversation_use_browser_without_unix_commands(self):
        self.launcher.launch('setup')
        self.assertEqual(self.runner.call_args.args[0], [sys.executable, '-m', 'cli.browser', 'https://chatgpt.com/dots'])
        self.launcher.configure('https://chatgpt.com/c/test?one=1&two=2')
        self.launcher.launch('dot')
        self.assertEqual(self.runner.call_args.args[0][-1], 'https://chatgpt.com/c/test?one=1&two=2')
        self.assertNotIn('shell', self.runner.call_args.kwargs)

    def test_clipboard_keeps_unicode_and_powershell_metacharacters_in_stdin(self):
        prompt = 'Unicode café 日本語 👋; $(Write-Output bad) `quote`\nsecond line'
        result = self.launcher.launch('copy', prompt)
        call = self.runner.call_args
        self.assertEqual(call.args[0][0], 'powershell.exe')
        self.assertNotIn(prompt, ' '.join(call.args[0]))
        self.assertEqual(call.kwargs['input'], prompt)
        self.assertEqual(call.kwargs['encoding'], 'utf-8')
        self.assertNotIn('shell', call.kwargs)
        self.assertTrue(result['copied'])
        self.assertNotIn(prompt, (self.base / 'runtime/dots-launches.jsonl').read_text(encoding='utf-8'))

    def test_app_and_folder_launch_as_argument_arrays(self):
        app = self.base / 'ChatGPT.exe'
        app.touch()
        self.launcher.app = app
        self.assertTrue(self.launcher.app_available())
        self.launcher.launch('app')
        self.assertEqual(self.runner.call_args.args[0], [str(app)])
        self.launcher.launch('folder')
        self.assertEqual(self.runner.call_args.args[0][0], 'explorer.exe')

    def test_registry_preserves_non_ascii_names_and_atomic_writes(self):
        self.launcher.create('研究 café', no_open=True)
        self.launcher.configure('https://chatgpt.com/c/test', name='研究 café')
        self.assertEqual(self.launcher.list_dots()[0]['name'], '研究 café')
        self.launcher.configure('')
        self.assertEqual(self.launcher.list_dots()[0]['state'], 'setup pending')


if __name__ == '__main__':
    unittest.main()
