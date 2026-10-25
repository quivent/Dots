"""Optional authenticated relay for the native iOS app; account credentials stay on the Mac."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import hashlib
import socket
import tempfile
import threading
import time
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit
import uuid

from .api import ApiError, DotClient


def relay_request(client, method, path, query, body):
    """A fixed route catalog, never arbitrary command execution or arbitrary upstream URLs."""
    # Provider Dot IDs contain '~'. Accept its encoded spelling for older iOS
    # clients, without allowing arbitrary percent-encoded path separators.
    identifier = r'(?:[A-Za-z0-9_~-]|%7[Ee])+'
    if method == 'GET':
        allowed = (path == '/tbo' or re.fullmatch('/tbo/' + identifier, path)
                   or re.fullmatch('/tbo/' + identifier + '/(activity|tasks)', path)
                   or re.fullmatch('/messaging/rooms/' + identifier + '/messages', path))
        if not allowed or not set(query) <= {'limit', 'cursor', 'include_room_preview', 'before', 'after'}:
            raise ValueError('Unsupported read request.')
        return client.request('GET', path, query=query)
    if method != 'POST':
        raise ValueError('Unsupported method.')
    if path == '/tbo':
        if set(body) != {'display_name', 'create_thread', 'create_additional', 'should_initialize'}:
            raise ValueError('Unsupported Dot creation fields.')
        name = body['display_name']
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or not name.isprintable():
            raise ValueError('Use a printable Dot name of 1–80 characters.')
        if any(type(body[key]) is not bool for key in ('create_thread', 'create_additional', 'should_initialize')):
            raise ValueError('Invalid creation options.')
    elif re.fullmatch('/tbo/' + identifier + '/(messaging-room|runtime/(pause|resume))', path):
        if body:
            raise ValueError('This action takes no fields.')
    elif re.fullmatch('/messaging/rooms/' + identifier + '/messages', path):
        if set(body) != {'content', 'request_id', 'idempotency_token', 'timezone_offset_min'}:
            raise ValueError('Unsupported message fields.')
        content = body['content']
        if (not isinstance(content, dict) or set(content) != {'text', 'attachments'}
                or content['attachments'] != [] or not isinstance(content['text'], str)
                or not content['text'].strip() or len(content['text']) > 12000):
            raise ValueError('Use a text message of 1–12000 characters.')
        request_id = body['request_id']
        if not isinstance(request_id, str) or str(uuid.UUID(request_id)).lower() != request_id.lower() or body['idempotency_token'] != request_id:
            raise ValueError('Invalid message request ID.')
        offset = body['timezone_offset_min']
        if type(offset) is not int or not -900 <= offset <= 900:
            raise ValueError('Invalid timezone.')
    else:
        raise ValueError('Unsupported write request.')
    return client.request('POST', path, body=body)


class MobileServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, token, client_factory=DotClient, pairing_directory=None):
        if not isinstance(token, str) or len(token) < 32 or not token.isascii():
            raise ValueError('Use a connection token of at least 32 ASCII characters.')
        self.token, self.client_factory = token, client_factory
        self.client_lock = threading.Lock()
        self.cached_client, self.client_expires = None, 0
        self.pairing = PairingAuthority(token, pairing_directory)
        super().__init__(address, MobileHandler)

    def account_request(self, method, path, query, body):
        def current():
            with self.client_lock:
                if self.cached_client is None or time.monotonic() >= self.client_expires:
                    self.cached_client = self.client_factory()
                    self.client_expires = time.monotonic() + 240
                return self.cached_client
        try:
            return relay_request(current(), method, path, query, body)
        except ApiError as error:
            if error.status != 401: raise
            with self.client_lock: self.cached_client = None
            # Refresh a rejected login for reads only. Writes are never replayed.
            if method != 'GET': raise
            return relay_request(current(), method, path, query, body)


class PairingAuthority:
    """Short-lived, one-use local pairing codes issue independently revocable phone tokens."""
    def __init__(self, root_token, directory=None):
        self.root_token = root_token
        self.path = Path(directory) / 'paired-phones.json' if directory else None
        self.lock = threading.Lock()
        self.devices = {}
        self.code, self.expires, self.attempts = '', 0, 0
        if self.path and self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
                raise ValueError('Paired phone storage must be private.')
            self.devices = json.loads(self.path.read_text())
            if not isinstance(self.devices, dict):
                raise ValueError('Invalid paired phone storage.')

    def authorized(self, token):
        with self.lock:
            return self.admin(token) or hashlib.sha256(token.encode()).hexdigest() in self.devices

    def admin(self, token):
        return secrets.compare_digest(token.encode(), self.root_token.encode())

    def start(self):
        with self.lock:
            self.code = f'{secrets.randbelow(1_000_000):06d}'
            self.expires, self.attempts = time.monotonic() + 120, 0
            return {'code': self.code, 'expires_in': 120, 'name': socket.gethostname()}

    def pair(self, code):
        with self.lock:
            if not isinstance(code, str) or not code.isascii() or len(code) != 6 or not code.isdigit():
                return None
            if not self.code or time.monotonic() >= self.expires or self.attempts >= 5:
                return None
            self.attempts += 1
            if not secrets.compare_digest(code, self.code):
                return None
            token = secrets.token_urlsafe(32)
            self.devices[hashlib.sha256(token.encode()).hexdigest()] = {'paired_at': time.time()}
            self.save()
            self.code = ''
            return {'token': token, 'name': socket.gethostname()}

    def revoke(self):
        with self.lock:
            self.devices = {}; self.code = ''; self.save()

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.paired-phones-')
        try:
            with os.fdopen(descriptor, 'w') as file:
                json.dump(self.devices, file)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)


class MobileHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # No headers, tokens, message text, or upstream bodies in logs.

    def reply(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self, method):
        header = self.headers.get('Authorization', '')
        if self.headers.get('Origin') or self.headers.get('Transfer-Encoding'):
            return self.reply(403, {'error': 'Native app requests only.'})
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith('/v1/'):
                raise ValueError('Unsupported route.')
            bearer = header.removeprefix('Bearer ') if header.startswith('Bearer ') else ''
            pairing_request = parsed.path == '/v1/pair' and method == 'POST'
            if not pairing_request and not self.server.pairing.authorized(bearer):
                return self.reply(401, {'error': 'Invalid connection token.'})
            parameters = parse_qs(parsed.query, strict_parsing=True)
            if any(len(values) != 1 for values in parameters.values()):
                raise ValueError('Duplicate query parameter.')
            query = {key: values[0] for key, values in parameters.items()}
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 65536 or (method == 'GET' and length):
                raise ValueError('Invalid request size.')
            body = {}
            if length:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Expected JSON.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected an object.')
            path = parsed.path[3:]
            if pairing_request:
                if set(body) != {'code'}: raise ValueError('Expected pairing code.')
                paired = self.server.pairing.pair(body['code'])
                return self.reply(200 if paired else 403, paired or {'error': 'Invalid or expired pairing code.'})
            if path == '/health' and method == 'GET':
                return self.reply(200, {'name': socket.gethostname(), 'protocol_version': 1})
            if path in ('/pairing/start', '/pairing/revoke') and method == 'POST':
                if not self.server.pairing.admin(bearer):
                    return self.reply(403, {'error': 'Only this Mac can manage pairing.'})
                if path.endswith('/start'): return self.reply(200, self.server.pairing.start())
                self.server.pairing.revoke()
                return self.reply(200, {'ok': True})
            result = self.server.account_request(method, path, query, body)
            return self.reply(200, result)
        except ApiError as error:
            status = error.status if error.status and 400 <= error.status <= 599 else 502
            return self.reply(status, {'error': str(error)})
        except (ValueError, UnicodeError, TypeError):
            return self.reply(400, {'error': 'Invalid or unsupported mobile request.'})
        except OSError:
            return self.reply(502, {'error': 'The account request could not be completed.'})

    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')


def load_token(path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError('The mobile token file must be private and must not be a symlink.')
    else:
        with os.fdopen(descriptor, 'w') as file:
            file.write(secrets.token_urlsafe(32) + '\n')
    token = path.read_text().strip()
    if len(token) < 32 or not token.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('Invalid mobile connection token file.')
    return token


def install_daemon(args, token_file):
    """Write a per-user launchd job; no root, no virtual environment."""
    import plistlib
    if sys.platform != 'darwin':
        raise ValueError('Daemon installation currently uses macOS launchd.')
    label = 'com.quivent.dots.mobile'
    target = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    target.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent.parent
    if '__compiled__' in globals():
        executable = Path(shutil.which(sys.argv[0]) or sys.argv[0]).expanduser().resolve()
        if not executable.is_file():
            raise ValueError('Could not find the installed dots executable.')
        command = [str(executable), 'mobile']
    else:
        command = [sys.executable, '-m', 'cli.mobile']
    log_dir = Path.home() / 'Library/Logs/Dots'
    log_dir.mkdir(parents=True, exist_ok=True)
    spec = {'Label': label, 'ProgramArguments': [*command, '--host', args.host, '--port', str(args.port),
            '--token-file', str(token_file), '--quiet'], 'RunAtLoad': True, 'KeepAlive': True,
            'WorkingDirectory': str(root if (root / 'pyproject.toml').exists() else Path.home()),
            'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/usr/bin:/bin')},
            'StandardOutPath': str(log_dir / 'mobile.log'), 'StandardErrorPath': str(log_dir / 'mobile-error.log'),
            'ThrottleInterval': 10}
    with target.open('wb') as file:
        plistlib.dump(spec, file)
    domain = 'gui/' + str(os.getuid())
    subprocess.run(['launchctl', 'bootout', domain + '/' + label], capture_output=True)
    subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print('Dots mobile daemon installed: ' + str(target))


def run(args, launcher=None):
    token_file = Path(args.token_file).expanduser().resolve()
    token = load_token(token_file)
    if args.install_daemon:
        install_daemon(args, token_file)
        print('Open Dots Mac in the menu bar, then choose Pair iPhone.')
        return 0
    with MobileServer((args.host, args.port), token, pairing_directory=token_file.parent) as server:
        if not args.quiet:
            print(f'Dots mobile listening on {args.host}:{server.server_port}', flush=True)
            print('Connect the iPhone over your private network or Tailscale.', flush=True)
            print('Connection token: ' + token, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--token-file', default=str(Path.home() / '.local/share/dots/mobile-token'))
    parser.add_argument('--install-daemon', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
