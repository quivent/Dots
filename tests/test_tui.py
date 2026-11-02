"""The CLI launches the upstream frontend with the correct backend identity."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from cli.tui import interactive


class TuiLaunchTests(unittest.TestCase):
    def test_launch_preserves_provider_identity_and_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'qwen-code/packages/cli/dist/index.js'
            entry.parent.mkdir(parents=True)
            entry.touch()
            launcher = Mock(project=root, runtime=root / 'runtime')
            args = Namespace(dot='exact~provider-id', by_id=True, source='chatgpt', poll=3)
            with patch('cli.tui.shutil.which', return_value='/fixture/node'), \
                    patch('cli.tui.subprocess.run') as run, \
                    patch.dict('os.environ', {}, clear=True):
                run.return_value.returncode = 0
                self.assertEqual(interactive(args, launcher), 0)
            self.assertEqual(run.call_args.args[0], ['/fixture/node', str(entry.resolve())])
            env = run.call_args.kwargs['env']
            self.assertEqual(env['DOTS_DOT'], 'exact~provider-id')
            self.assertEqual(env['DOTS_BY_ID'], '1')
            self.assertEqual(env['DOTS_SOURCE'], 'chatgpt')
            self.assertEqual(env['DOTS_BACKEND'], '1')
            self.assertEqual(env['DOTS_DATA_HOME'], str(launcher.runtime))

    def test_unbuilt_frontend_fails_with_build_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Mock(project=Path(directory), runtime=Path(directory))
            with patch('cli.tui.shutil.which', return_value='/fixture/node'), \
                    patch.dict('os.environ', {'DOTS_ROOT': directory}), \
                    patch('cli.tui.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'Build the Qwen interface first'):
                    interactive(Namespace(), launcher)
                run.assert_not_called()

    def test_compiled_launch_reenters_installed_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'qwen-code/packages/cli/dist/index.js'
            entry.parent.mkdir(parents=True)
            entry.touch()
            executable = root / 'dots'
            executable.touch()
            launcher = Mock(project=root, runtime=root / 'runtime')
            args = Namespace(dot='Pocket', by_id=False, source='local', poll=2)
            with patch('cli.tui.shutil.which', return_value=str(executable)), \
                    patch('cli.tui.subprocess.run') as run, \
                    patch('cli.tui.sys.argv', [str(executable)]), \
                    patch('cli.tui.sys.executable', '/missing/python3.14'), \
                    patch.dict('cli.tui.__dict__', {'__compiled__': True}), \
                    patch.dict('os.environ', {}, clear=True):
                run.return_value.returncode = 0
                interactive(args, launcher)
            env = run.call_args.kwargs['env']
            self.assertEqual(env['DOTS_PYTHON'], str(executable.resolve()))
            self.assertEqual(env['DOTS_BRIDGE_BINARY'], '1')


if __name__ == '__main__':
    unittest.main()
