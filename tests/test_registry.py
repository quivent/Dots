import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from dots_cli.cli import Launcher, PROJECT


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


if __name__ == '__main__':
    unittest.main()
