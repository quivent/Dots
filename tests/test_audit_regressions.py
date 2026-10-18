from contextlib import redirect_stdout, redirect_stderr
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from cli.api import ApiError, DotClient, credentials, credential_store
from cli.browser import main as open_browser
from cli.cli import Launcher, main


class AuditRegressions(unittest.TestCase):
    def invoke(self, args):
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            code = main(args)
        return code, stream.getvalue()

    def test_truncated_creation_reply_preserves_unknown_outcome_without_retry(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = IncompleteRead(b'fixture-sensitive-fragment')
        opener = Mock()
        opener.open.return_value = response
        client = DotClient('fixture-token', 'fixture-account', opener)
        with self.assertRaises(ApiError) as caught:
            client.create('Research', additional=False)
        self.assertIn('Outcome unknown', str(caught.exception))
        self.assertNotIn('fixture-sensitive-fragment', str(caught.exception))
        opener.open.assert_called_once()

    @patch.dict('os.environ', {}, clear=True)
    @patch('cli.api.credential_store')
    @patch('cli.auth.existing_credentials', return_value=('shared-token', 'shared-account'))
    def test_invalid_saved_records_fall_back_to_shared_login(self, existing, store):
        for record in ([], None, 42, 'wrong', {'token': 7, 'account_id': 'account'},
                       {'token': 'token', 'account_id': None}, {'token': '', 'account_id': 'account'},
                       {'token': 'bad\nheader', 'account_id': 'account'}):
            with self.subTest(record=record):
                store.return_value.get_password.return_value = json.dumps(record)
                self.assertEqual(credentials(), ('shared-token', 'shared-account', 'existing ChatGPT sign-in'))
        store.return_value.set_password.assert_not_called()

    @patch('cli.cloud.credentials', side_effect=[('old-token', 'account', 'OS credential store'), ('shared-token', 'account', 'existing ChatGPT sign-in')])
    @patch('cli.cloud.credential_store')
    @patch('cli.auth.sign_in')
    @patch('cli.cloud.DotClient')
    def test_rejected_saved_token_is_removed_after_shared_login_verified(self, client, sign_in, store, credential):
        client.return_value.list.side_effect = [ApiError('expired', status=401), []]
        code, output = self.invoke(['auth'])
        self.assertEqual(code, 0)
        credential.assert_any_call(ignore_saved=True)
        sign_in.assert_not_called()
        store.return_value.delete_password.assert_called_once_with('dots-cli', 'account')
        self.assertNotIn('shared-token', output)

    @patch('cli.cloud.credentials', side_effect=[('old-token', 'account', 'OS credential store'), ('', '', 'none')])
    @patch('cli.cloud.credential_store')
    @patch('cli.auth.sign_in', return_value=('new-token', 'account'))
    @patch('cli.cloud.DotClient')
    def test_rejected_saved_token_can_start_new_login(self, client, sign_in, store, credential):
        client.return_value.list.side_effect = [ApiError('expired', status=401), []]
        code, _ = self.invoke(['auth'])
        self.assertEqual(code, 0)
        sign_in.assert_called_once()
        store.return_value.delete_password.assert_called_once()

    @patch('cli.cloud.credentials', side_effect=[('old-token', 'account', 'OS credential store'), ('shared-token', 'account', 'existing ChatGPT sign-in')])
    @patch('cli.cloud.credential_store')
    @patch('cli.cloud.DotClient')
    def test_failed_replacement_does_not_delete_saved_credentials(self, client, store, credential):
        client.return_value.list.side_effect = [ApiError('expired', status=401), ApiError('denied', status=403)]
        code, _ = self.invoke(['auth'])
        self.assertEqual(code, 1)
        store.return_value.delete_password.assert_not_called()

    @patch('cli.cloud.credentials', return_value=('explicit-token', 'account', 'environment'))
    @patch('cli.auth.sign_in')
    @patch('cli.cloud.DotClient')
    def test_environment_override_is_not_silently_replaced(self, client, sign_in, credential):
        client.return_value.list.side_effect = ApiError('expired', status=401)
        self.assertEqual(self.invoke(['auth'])[0], 1)
        sign_in.assert_not_called()
        client.return_value.list.assert_called_once()

    def test_dot_segments_are_rejected_before_any_request(self):
        for dot in ('.', '..', 'a/../b', '%2e%2e', '%2E', 'a\\..\\b'):
            with self.subTest(dot=dot), self.assertRaises(ApiError):
                DotClient.path(dot)

    @patch('cli.cloud.DotClient')
    def test_task_dot_segment_does_not_reach_api(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        self.assertEqual(self.invoke(['tasks', 'one', '--task', '..'])[0], 1)
        client.return_value.request.assert_not_called()

    @patch('cli.browser.webbrowser.open', return_value=False)
    def test_browser_failure_returns_nonzero(self, browser):
        self.assertEqual(open_browser(['https://chatgpt.com/dots']), 1)

    def test_onboarding_initializes_fresh_workspace_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runner = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
            launcher = Launcher(project=base / 'workspace', runtime=base / 'runtime', runner=runner,
                                app=base / 'missing.app', platform='darwin')
            self.assertFalse(launcher.local_readiness()['workspace_ready'])
            self.assertFalse(launcher.project.exists())
            with patch('cli.cli.Launcher', return_value=launcher):
                self.assertEqual(self.invoke(['setup', 'onboard'])[0], 0)
            self.assertTrue(launcher.local_readiness()['workspace_ready'])
            self.assertIn('FIRST-RESULT.md', (launcher.project / '.gitignore').read_text(encoding='utf-8'))
            prompt = next(p['text'] for p in launcher.presets() if p['id'] == 'local')
            self.assertIn(str(launcher.project / 'README.md'), prompt)
            self.assertNotIn('tracker-factory', prompt)
            (launcher.project / 'README.md').write_text('Keep my project', encoding='utf-8')
            launcher.prepare(prompt)
            self.assertEqual((launcher.project / 'README.md').read_text(encoding='utf-8'), 'Keep my project')

    def test_existing_ignore_rules_and_linked_starter_docs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / '.gitignore').write_text('custom-build/', encoding='utf-8')
            launcher = Launcher(project=base, runtime=base / 'runtime')
            launcher.init_project()
            launcher.init_project()
            ignore = (base / '.gitignore').read_text(encoding='utf-8')
            self.assertTrue(ignore.startswith('custom-build/\n'))
            self.assertEqual(ignore.splitlines().count('dots-trials.md'), 1)
            self.assertIn('FIRST-RESULT.md', ignore.splitlines())
            for name in ('setup.html', 'index.html', 'LAUNCHER.md', 'INSTALL.md'):
                self.assertTrue((base / name).is_file(), name)

    def test_failed_protocol_launch_uses_https_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            app = base / 'ChatGPT.exe'
            app.touch()
            runner = Mock(side_effect=[subprocess.CompletedProcess([], 1, '', ''), subprocess.CompletedProcess([], 0, '', '')])
            launcher = Launcher(project=base / 'workspace', runtime=base / 'runtime', runner=runner, app=app, platform='win32')
            self.assertTrue(launcher.launch('setup')['ok'])
            self.assertEqual(runner.call_args_list[0].args[0][-1], 'codex://dots')
            self.assertEqual(runner.call_args_list[1].args[0][-1], 'https://chatgpt.com/dots')

    def test_browser_failure_is_recorded_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runner = Mock(return_value=subprocess.CompletedProcess([], 1, '', ''))
            launcher = Launcher(project=base, runtime=base / 'runtime', runner=runner, platform='linux')
            with self.assertRaises(ValueError):
                launcher.launch('web')
            self.assertEqual(launcher.history()[0]['outcome'], 'failed')

    @patch('cli.cloud.DotClient')
    def test_activity_navigation_failures_are_handled_after_data_is_returned(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.pages.return_value = [{'thread_id': 'thread', 'title': 'Loaded activity'}]
        for error in (subprocess.CalledProcessError(1, ['browser']), subprocess.TimeoutExpired(['browser'], 15)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                launcher = Launcher(project=base, runtime=base / 'runtime', runner=Mock(side_effect=error), platform='linux')
                with patch('cli.cli.Launcher', return_value=launcher):
                    code, output = self.invoke(['activity', 'one', '--open', '--json'])
                self.assertEqual(code, 1)
                self.assertIn('Loaded activity', output)
                self.assertIn('Activity loaded, but', output)
                self.assertNotIn('Traceback', output)

    def test_plaintext_keyring_backend_is_rejected(self):
        backend = type('PlaintextBackend', (), {'__module__': 'keyrings.alt.file'})()
        fake = Mock()
        fake.get_keyring.return_value = backend
        with patch.dict(sys.modules, {'keyring': fake}), self.assertRaises(ApiError):
            credential_store()

    def test_real_redirect_does_not_forward_credentials(self):
        paths = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                paths.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/should-not-be-requested')
                self.end_headers()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch('cli.api.BASE_URL', 'http://127.0.0.1:' + str(server.server_port)):
                with self.assertRaises(ApiError) as caught:
                    DotClient('fixture-token', 'fixture-account').list()
            self.assertEqual(len(paths), 1)
            self.assertNotIn('fixture-token', str(caught.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
