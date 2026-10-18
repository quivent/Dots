from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from cli.cli import Launcher, PROJECT, main


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
        self.assertIn('usage:', output.getvalue().lower())
        for command in ['create','list','use','activity','serve','doctor','configure']:
            self.assertIn(command, output.getvalue())


if __name__ == '__main__':
    unittest.main()
