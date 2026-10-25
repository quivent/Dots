"""Runtime differences required by a bundled executable."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cli import resources, update, workflow


class NativeCliTests(unittest.TestCase):
    def test_bundled_guides_resolve_without_installed_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guide = root / 'share' / 'dots' / 'README.md'
            guide.parent.mkdir(parents=True)
            guide.write_text('Bundled guide')
            with patch.dict(resources.__dict__, {'__compiled__': object()}), \
                    patch.object(resources, 'SOURCE_ROOT', root), \
                    patch.object(resources, 'distribution') as distribution:
                self.assertEqual(resources.shared_resource('README.md'), guide)
                distribution.assert_not_called()

    def test_compiled_update_does_not_run_pip_or_check_network(self):
        with patch.dict(update.__dict__, {'__compiled__': object()}), \
                patch('cli.ui.console') as console, \
                patch.object(update, 'latest_version') as latest, \
                patch.object(update, 'install') as install:
            self.assertEqual(update.update(), 0)
            latest.assert_not_called()
            install.assert_not_called()
            self.assertIn('make -C cli binary', console.print.call_args.args[0])

    def test_setup_reexecutes_binary_without_python_module_arguments(self):
        with patch.dict(workflow.__dict__, {'__compiled__': object()}), \
                patch('sys.executable', '/tmp/dots'), patch('subprocess.run') as run:
            run.return_value.returncode = 0
            self.assertEqual(workflow.execute_step(['preflight']), 0)
            run.assert_called_once_with(['/tmp/dots', 'preflight'], cwd=Path('/tmp'))
