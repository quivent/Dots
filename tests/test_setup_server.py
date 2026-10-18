from contextlib import redirect_stdout
import io
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock

from dots_cli.cli import Launcher, PROJECT, ASSETS
from dots_cli.server import SetupServer, serve


class SetupServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / 'FIRST-MESSAGE.md').write_text((ASSETS / 'FIRST-MESSAGE.md').read_text(encoding='utf-8'), encoding='utf-8')
        for name in ('index.html', 'setup.html'):
            (self.base / name).write_text((ASSETS / name).read_text(encoding='utf-8'), encoding='utf-8')
        (self.base / 'TRIALS.md').write_text('# Existing evidence\n')
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
        self.launcher = Launcher(project=self.base, runtime=self.base / 'runtime', runner=self.runner, app=self.base / 'missing.app', platform='darwin')
        self.server = SetupServer(self.launcher, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        self.addCleanup(connection.close)
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()

    def post(self, data, **headers):
        return self.request('POST', '/api/action', data, {'Origin': self.server.origin, 'X-Dot-Token': self.server.token, 'Content-Type': 'application/json', **headers})

    def test_status_detects_result_without_launching_or_creating_runtime(self):
        status, body = self.request('GET', '/api/status')
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(data['result_exists'])
        self.assertFalse(data['app_available'])
        self.assertIn(str(self.base), data['presets'][1]['text'])
        (self.base / 'FIRST-RESULT.md').write_text('')
        self.assertFalse(json.loads(self.request('GET', '/api/status')[1])['result_exists'])
        (self.base / 'FIRST-RESULT.md').write_text('Observed output')
        self.assertTrue(json.loads(self.request('GET', '/api/status')[1])['result_exists'])
        self.runner.assert_not_called()
        self.assertFalse((self.base / 'runtime').exists())

    def test_foreign_origin_invalid_token_and_host_cannot_run_actions(self):
        for headers in ({'Origin': 'https://example.com'}, {'X-Dot-Token': 'wrong'}, {'Host': 'example.com'}, {'Origin': 'null'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.post({'action': 'setup'}, **headers)[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request('GET', '/api/status', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.runner.assert_not_called()

    def test_prepare_uses_saved_conversation_and_preset_as_data(self):
        self.launcher.configure('https://chatgpt.com/c/example')
        status, body = self.post({'action': 'prepare', 'preset': 'local'})
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)['submitted'])
        self.assertEqual(self.runner.call_args_list[0].args[0], ['/usr/bin/pbcopy'])
        self.assertIn(str(self.base), self.runner.call_args_list[0].kwargs['input'])
        self.assertEqual(self.runner.call_args_list[1].args[0], ['/usr/bin/open', 'https://chatgpt.com/c/example'])

    def test_prepare_falls_back_to_browser_without_desktop_app(self):
        self.assertEqual(self.post({'action': 'prepare', 'preset': 'first'})[0], 200)
        self.assertEqual(self.runner.call_args_list[0].args[0], ['/usr/bin/pbcopy'])
        self.assertEqual(self.runner.call_args_list[1].args[0], ['/usr/bin/open', 'https://chatgpt.com/dots'])

    def test_record_preserves_previous_trials_and_rejects_empty_notes(self):
        self.assertEqual(self.post({'action': 'record', 'notes': ''})[0], 400)
        self.assertEqual(self.post({'action': 'record', 'notes': 'Result checked. $(literal) <text>'})[0], 200)
        text = (self.base / 'TRIALS.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# Existing evidence\n'))
        self.assertIn('Result checked. $(literal) <text>', text)
        self.runner.assert_not_called()

    def test_only_declared_files_and_actions_are_available(self):
        for path in ('/.git/config', '/dots_launcher.py', '/../FIRST-MESSAGE.md', '/runtime/dots-launcher.json'):
            self.assertEqual(self.request('GET', path)[0], 404)
        for data in ({'action': 'shell', 'command': 'echo bad'}, {'action': 'prepare', 'preset': 'bad'}, {'action': 'configure', 'url': 'https://example.com'}, []):
            self.assertEqual(self.post(data)[0], 400)
        self.runner.assert_not_called()
        self.assertEqual(self.request('GET', '/setup.html')[0], 200)

    def test_serve_reuses_running_desk_for_same_checkout(self):
        output = io.StringIO()
        with redirect_stdout(output):
            serve(self.launcher, port=self.server.server_port, open_browser=False)
        self.assertIn('already running', output.getvalue())
        self.runner.assert_not_called()

    def test_static_pages_use_switches_and_have_no_personal_paths(self):
        setup = (ASSETS / 'setup.html').read_text(encoding='utf-8')
        self.assertEqual(setup.count('role="switch"'), 6)
        self.assertNotIn('type="checkbox"', setup)
        self.assertNotIn('/Users/', setup)
        self.assertIn('<h1>Set up a Dot</h1>', setup)


if __name__ == '__main__':
    unittest.main()
