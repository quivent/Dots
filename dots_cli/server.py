"""Loopback-only setup actions. No shell commands or remote assets are served."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import urllib.error
import urllib.request
import webbrowser
from urllib.parse import urlsplit


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, launcher, port=8768):
        self.launcher = launcher
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), SetupHandler)
        self.authority = '127.0.0.1:' + str(self.server_port)
        self.origin = 'http://' + self.authority

    def status(self):
        launcher = self.launcher
        result = launcher.project / 'FIRST-RESULT.md'
        return dict(url=launcher.settings()['url'], app_available=launcher.app_available(),
                    project=str(launcher.project), presets=launcher.presets(),
                    result_exists=result.is_file() and result.stat().st_size > 0,
                    token=self.token)

    def action(self, data):
        action = data.get('action')
        launcher = self.launcher
        if action == 'configure':
            return launcher.configure(data.get('url', ''))
        if action == 'record':
            notes = data.get('notes', '')
            if not isinstance(notes, str) or not notes.strip() or len(notes) > 12000:
                raise ValueError('Enter trial notes (up to 12,000 characters).')
            # Personal notes stay outside tracked project documents.
            with launcher.locked():
                notes_path = launcher.runtime / 'dots-trials.md'
                if notes_path.is_symlink():
                    raise ValueError('Private notes file cannot be a symlink.')
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
                fd = os.open(notes_path, flags, 0o600)
                with os.fdopen(fd, 'a', encoding='utf-8') as f:
                    if os.name != 'nt':
                        os.fchmod(f.fileno(), 0o600)
                    f.write('\n## Local setup note — ' + datetime.now(timezone.utc).isoformat() + '\n\n' + notes.strip() + '\n')
            return dict(ok=True, message='Notes saved privately in ' + str(notes_path) + '.')
        if action == 'prepare':
            preset = data.get('preset')
            if preset not in ('first', 'local', 'followup'):
                raise ValueError('Choose a supported prompt.')
            prompt = next(p['text'] for p in launcher.presets() if p['id'] == preset)
            return launcher.prepare(prompt)
        if action not in ('setup', 'app', 'copy', 'dot', 'folder'):
            raise ValueError('Unsupported setup action.')
        prompt = ''
        if action in ('app', 'copy', 'dot'):
            preset = data.get('preset')
            if preset not in ('first', 'local', 'followup'):
                raise ValueError('Choose a supported prompt.')
            prompt = next(p['text'] for p in launcher.presets() if p['id'] == preset)
        return launcher.launch(action, prompt)


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log request bodies, conversation URLs, notes, or session tokens.

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        return self.headers.get('Host') == self.server.authority

    def do_GET(self):
        if not self.allowed_host():
            return self.reply(403, {'error': 'Local host required.'})
        path = urlsplit(self.path).path
        if path == '/api/status':
            origin = self.headers.get('Origin')
            if origin and origin != self.server.origin:
                return self.reply(403, {'error': 'Same-origin requests only.'})
            if self.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
                return self.reply(403, {'error': 'Same-origin requests only.'})
            try:
                return self.reply(200, self.server.status())
            except (ValueError, OSError):
                return self.reply(500, {'error': 'Could not read local launcher state.'})
        name = {'/': 'setup.html', '/setup.html': 'setup.html', '/index.html': 'index.html',
                '/README.md': 'README.md', '/LAUNCHER.md': 'LAUNCHER.md',
                '/FIRST-MESSAGE.md': 'FIRST-MESSAGE.md', '/FIRST-RESULT.md': 'FIRST-RESULT.md',
                '/TRIALS.md': 'TRIALS.md', '/INSTALL.md': 'INSTALL.md'}.get(path)
        if not name:
            return self.reply(404, {'error': 'Not found.'})
        try:
            target = self.server.launcher.project / name
            if not target.exists() and name != 'FIRST-RESULT.md':
                target = self.server.launcher.resource(name)
            if target.is_symlink():
                return self.reply(403, {'error': 'Symlink targets are not served.'})
            body = target.read_bytes()
        except FileNotFoundError:
            return self.reply(404, {'error': 'File not created yet.'})
        self.reply(200, body, 'text/html; charset=utf-8' if name.endswith('.html') else 'text/plain; charset=utf-8')

    def do_POST(self):
        if not self.allowed_host() or self.headers.get('Origin') != self.server.origin:
            return self.reply(403, {'error': 'Same-origin local requests only.'})
        if not secrets.compare_digest(self.headers.get('X-Dot-Token', ''), self.server.token):
            return self.reply(403, {'error': 'Reload the setup page and try again.'})
        if self.path != '/api/action':
            return self.reply(404, {'error': 'Not found.'})
        if self.headers.get('Content-Type') != 'application/json':
            return self.reply(415, {'error': 'Expected JSON.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 50000:
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected an action object.')
            result = self.server.action(data)
            return self.reply(200, result)
        except (ValueError, OSError) as error:
            return self.reply(400, {'error': str(error)})


def serve(launcher, port=8768, open_browser=True):
    launcher.init_project()
    try:
        server = SetupServer(launcher, port)
    except OSError:
        origin = 'http://127.0.0.1:' + str(port)
        try:
            with urllib.request.urlopen(origin + '/api/status', timeout=2) as response:
                existing = json.load(response)
            if existing.get('project') != str(launcher.project) or not isinstance(existing.get('token'), str):
                raise ValueError('Another service is using this port. Use dots serve --port 8769.')
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise ValueError('Port unavailable. Use dots serve --port 8769.') from error
        print('Dot setup desk already running: ' + origin + '/setup.html', flush=True)
        if open_browser:
            webbrowser.open(origin + '/setup.html')
        return
    print('Dot setup desk: ' + server.origin + '/setup.html', flush=True)
    print('Local launcher enabled. Press Ctrl+C to stop.', flush=True)
    if open_browser:
        webbrowser.open(server.origin + '/setup.html')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
