"""Exercise the actual Makefile and installed command outside the checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from cli import __version__


has = unittest.TestCase.assertIn


@unittest.skipUnless(os.name != 'nt' and shutil.which('make'), 'Requires POSIX make')
class MakeTests(unittest.TestCase):
    def test_make_installs_a_runnable_cli_without_a_venv(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='dots-make-') as directory:
            base = Path(directory)
            binary = base / 'bin'
            environment = {key: value for key, value in os.environ.items()
                           if key not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONNOUSERSITE', 'VIRTUAL_ENV')}
            environment.update(PYTHONUSERBASE=str(base / 'packages'),
                               PATH=str(binary) + os.pathsep + os.environ.get('PATH', ''),
                               DOTS_PROJECT=str(base / 'workspace'), DOTS_DATA_HOME=str(base / 'runtime'),
                               PIP_DISABLE_PIP_VERSION_CHECK='1')
            python = getattr(sys, '_base_executable', sys.executable)

            def run(*arguments, cwd=base):
                result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                                        text=True, encoding='utf-8', timeout=180)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            self.assertEqual(run('make', f'PYTHON={python}', f'BIN_DIR={binary}', cwd=root / 'cli'),
                             'Installed dots.\n')
            self.assertEqual(run('dots', '--version').strip(), 'dots ' + __version__)
            has(self, '▸ Setup', run('dots', '--no-color', '--help'))
            self.assertEqual(json.loads(run('dots', 'list', '--json')), [])
            self.assertEqual(json.loads(run('dots', 'list', '--source', 'shortcuts', '--json')),
                             {'source': 'local_registry', 'dots': []})
            self.assertEqual(len(json.loads(run('dots', 'setup', '--json'))['steps']), 10)
            self.assertEqual(run(python, '-c', 'import sys; print(sys.prefix == sys.base_prefix)').strip(), 'True')
            installed = Path(run(python, '-c', 'import cli; print(cli.__file__)').strip())
            self.assertTrue(installed.is_relative_to(base / 'packages'), installed)
            self.assertFalse((base / 'workspace').exists())
            self.assertFalse((base / 'runtime').exists())
            # Resolve every packaged resource outside the source checkout, then
            # initialize a real fresh workspace without launching external tools.
            result = json.loads(run(python, '-c', """
import json
from cli.main import Launcher
from cli.resources import GUIDE_FILES
launcher = Launcher()
original = {name: launcher.resource(name).read_bytes() for name in GUIDE_FILES}
assert all(original.values()), 'Packaged guide files must be nonempty'
assert all(launcher.preset_text(preset) for preset in ('first', 'local', 'followup'))
launcher.init_project()
assert all((launcher.project / name).read_bytes() == content for name, content in original.items())
print(json.dumps(launcher.local_readiness()))
"""))
            self.assertTrue(result['workspace_ready'])
            self.assertTrue(result['presets_available'])
            # An empty PYTHONPATH component adds the caller's directory to imports.
            environment['PYTHONPATH'] = os.pathsep + str(base / 'unrelated')
            self.assertEqual(run('dots', '--version', cwd=root / 'cli').strip(), 'dots ' + __version__)
            has(self, '▸ Setup', run('dots', cwd=root / 'cli'))
