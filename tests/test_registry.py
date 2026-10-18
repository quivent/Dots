import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from cli.main import Launcher, PROJECT


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / 'runtime'
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
        self.launcher = Launcher(project=PROJECT, runtime=self.runtime, runner=self.runner, app=Path('/missing.app'), platform='darwin')

    def test_list_is_read_only_and_empty_is_not_account_discovery(self):
        self.assertEqual(self.launcher.list_dots(), [])
        self.assertFalse(self.runtime.exists())
        self.runner.assert_not_called()

    def test_create_records_pending_state_without_claiming_cloud_creation(self):
        result = self.launcher.create('research')
        self.assertFalse(result['cloud_created'])
        self.assertEqual(self.launcher.list_dots()[0]['state'], 'setup pending')
        self.assertEqual(self.runner.call_args.args[0], ['/usr/bin/open', 'https://chatgpt.com/dots'])
        self.assertFalse(self.launcher.history()[0]['submitted'])

    def test_no_open_create_and_duplicate_rejection_do_not_launch(self):
        self.launcher.create('research', no_open=True)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.launcher.create('RESEARCH')
        self.runner.assert_not_called()

    def test_named_configure_use_and_clear_preserve_other_entries(self):
        self.launcher.configure('https://chatgpt.com/c/one', name='research')
        self.launcher.configure('https://chatgpt.com/c/two', name='code')
        self.assertEqual(len(self.launcher.list_dots()), 2)
        self.launcher.use('RESEARCH')
        self.assertEqual(self.launcher.settings()['url'], 'https://chatgpt.com/c/one')
        self.launcher.configure('')
        self.assertEqual(self.launcher.settings()['url'], '')
        self.launcher.use('code')
        self.assertEqual(self.launcher.settings()['url'], 'https://chatgpt.com/c/two')
        with self.assertRaisesRegex(ValueError, 'No saved Dot'):
            self.launcher.use('missing')

    def test_legacy_single_url_survives_first_registry_write(self):
        self.runtime.mkdir()
        (self.runtime / 'dots-launcher.json').write_text(json.dumps({'url': 'https://chatgpt.com/c/old'}))
        self.assertEqual(self.launcher.list_dots()[0]['name'], 'default')
        self.launcher.configure('https://chatgpt.com/c/new', name='new')
        self.launcher.use('default')
        self.assertEqual(self.launcher.settings()['url'], 'https://chatgpt.com/c/old')

    def test_invalid_names_never_launch(self):
        for name in (' ', '\x1b[31m', 'a\nb', 'x' * 81):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                self.launcher.create(name)
        self.runner.assert_not_called()

    def test_history_failure_leaves_saved_entry_and_does_not_launch(self):
        with patch.object(self.launcher, 'record', side_effect=OSError('History unavailable')):
            with self.assertRaisesRegex(OSError, 'History unavailable'):
                self.launcher.create('research')
        self.assertEqual(self.launcher.list_dots()[0]['name'], 'research')
        self.assertEqual(self.launcher.history(), [])
        self.runner.assert_not_called()

    def test_separate_processes_do_not_overwrite_registry_updates(self):
        script = ('from cli.main import Launcher; import sys; '
                  'Launcher(runtime=sys.argv[1]).create(sys.argv[2], no_open=True)')
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.runtime), f'Dot {index}'],
                                     cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
                     for index in range(5)]
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stdout + stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate()
        self.assertEqual({entry['name'] for entry in self.launcher.list_dots()},
                         {f'Dot {index}' for index in range(5)})
        self.assertEqual(len(self.launcher.history()), 5)


if __name__ == '__main__':
    unittest.main()
