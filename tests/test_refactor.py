"""Compatibility checks for the Python simplification's behavioral boundaries."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from cli.api import ApiError
from cli.main import Launcher, main


class RefactorCompatibilityTests(unittest.TestCase):
    def invoke(self, arguments):
        from cli.sources import AGENT_COMMANDS
        if arguments and arguments[0] in AGENT_COMMANDS and "--source" not in arguments:
            arguments = [*arguments, "--source", "chatgpt"]
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            result = main(arguments)
        return result, stream.getvalue()

    def test_create_flags_keep_three_distinct_catalog_policies(self):
        with patch('cli.main.Launcher'), patch('cli.sources.run', return_value=0) as dispatch:
            for options, expected in (([], None), (['--first'], False), (['--additional'], True)):
                with self.subTest(options=options):
                    self.assertEqual(self.invoke(['create', 'Research', *options])[0], 0)
                    self.assertIs(dispatch.call_args.args[0].additional, expected)
            with self.assertRaises(SystemExit) as error:
                self.invoke(['create', 'Research', '--first', '--additional'])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(dispatch.call_count, 3)

    @patch('cli.cloud.credentials', side_effect=[
        ('saved-secret', 'account', 'OS credential store'),
        ('shared-secret', 'account', 'existing ChatGPT sign-in'),
    ])
    @patch('cli.cloud.credential_store')
    @patch('cli.auth.sign_in', return_value=('fresh-secret', 'account'))
    @patch('cli.cloud.DotClient')
    def test_auth_replaces_both_rejected_sources_before_deleting_saved_override(self, client, sign_in, store, credentials):
        events = []
        failures = iter([ApiError('expired', status=401), ApiError('expired', status=401), []])
        def verify():
            events.append('verify')
            result = next(failures)
            if isinstance(result, Exception):
                raise result
            return result
        client.return_value.list.side_effect = verify
        store.return_value.delete_password.side_effect = lambda *args: events.append('delete')
        code, output = self.invoke(['auth'])
        self.assertEqual(code, 0)
        self.assertEqual(events, ['verify', 'verify', 'verify', 'delete'])
        self.assertEqual(client.call_args_list, [call('saved-secret', 'account'), call('shared-secret', 'account'), call('fresh-secret', 'account')])
        sign_in.assert_called_once_with()
        credentials.assert_called_with(ignore_saved=True)
        self.assertNotIn('secret', output)

    @patch('cli.cloud.credentials', side_effect=[
        ('saved-secret', 'account', 'OS credential store'),
        ('shared-secret', 'account', 'existing ChatGPT sign-in'),
    ])
    @patch('cli.cloud.credential_store')
    @patch('cli.auth.sign_in', return_value=('fresh-secret', 'account'))
    @patch('cli.cloud.DotClient')
    def test_auth_does_not_retry_fresh_rejection_or_delete_saved_override(self, client, sign_in, store, credentials):
        client.return_value.list.side_effect = ApiError('expired', status=401)
        self.assertEqual(self.invoke(['auth'])[0], 1)
        self.assertEqual(client.return_value.list.call_count, 3)
        sign_in.assert_called_once_with()
        store.return_value.delete_password.assert_not_called()

    def test_protocol_spawn_exception_falls_back_once_and_records_actual_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            app = base / 'ChatGPT.exe'
            app.touch()
            for fallback_result in (0, 1):
                with self.subTest(fallback_result=fallback_result):
                    runner = Mock(side_effect=[OSError('protocol handler unavailable'), subprocess.CompletedProcess([], fallback_result, '', '')])
                    launcher = Launcher(project=base / 'project', runtime=base / 'runtime', runner=runner, app=app, platform='win32')
                    if fallback_result:
                        with self.assertRaises(ValueError):
                            launcher.launch('setup')
                    else:
                        self.assertTrue(launcher.launch('setup')['ok'])
                    self.assertEqual(runner.call_count, 2)
                    self.assertEqual(runner.call_args_list[0].args[0][-1], 'codex://dots')
                    self.assertEqual(runner.call_args_list[1].args[0][-1], 'https://chatgpt.com/dots')
                    self.assertEqual(launcher.history()[0]['outcome'], 'failed' if fallback_result else 'launch_requested')
                    self.assertFalse(launcher.history()[0]['submitted'])
