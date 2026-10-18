"""Reuse ChatGPT sign-in through the local app-server protocol.

Tokens exist only in memory. Never opens browser/session credential files or
prints raw server responses. The token handoff is an experimental legacy RPC.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time


class AuthUnavailable(ValueError):
    pass


def executable():
    configured = os.environ.get('DOTS_CODEX')
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() else None
    found = shutil.which('codex')
    if found:
        return found
    bundled = Path('/Applications/ChatGPT.app/Contents/Resources/codex')
    return str(bundled) if sys.platform == 'darwin' and bundled.is_file() else None


def _account_id(result, token):
    direct = result.get('accountId') or result.get('chatgptAccountId')
    if isinstance(direct, str) and direct:
        return direct
    try:
        part = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))
        value = claims.get('https://api.openai.com/auth', {}).get('chatgpt_account_id')
        # This claim selects routing only; the backend validates the credential.
        return value if isinstance(value, str) else None
    except (ValueError, IndexError, AttributeError, TypeError):
        return None


def _exchange(rpc):
    rpc('initialize', {'clientInfo': {'name': 'dots_cli', 'version': '0.2.5'},
                       'capabilities': {'experimentalApi': True}})
    account = rpc('account/read', {'refreshToken': False}).get('account') or {}
    if account.get('type') != 'chatgpt':
        raise AuthUnavailable('No existing ChatGPT sign-in is available to the local app server.')
    result = rpc('getAuthStatus', {'includeToken': True, 'refreshToken': False})
    token = result.get('authToken') or result.get('accessToken')
    if not isinstance(token, str) or not token:
        raise AuthUnavailable('This app server cannot hand off the existing ChatGPT login.')
    account_id = _account_id(result, token)
    if not account_id:
        raise AuthUnavailable('Existing login did not provide account routing.')
    return token, account_id


def existing_credentials():
    binary = executable()
    if not binary:
        raise AuthUnavailable('ChatGPT app-server executable not found. Sign in through ChatGPT/Codex, or set DOTS_CODEX to its executable.')
    process = None
    messages = queue.Queue()
    reader = None
    try:
        process = subprocess.Popen([binary, 'app-server', '--stdio'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding='utf-8', bufsize=1)
        def receive():
            try:
                for line in process.stdout:
                    messages.put(line)
            except (OSError, UnicodeError):
                pass
            finally:
                messages.put(None)
        reader = threading.Thread(target=receive, daemon=True)
        reader.start()
        request_id = 0
        deadline = time.monotonic() + 20
        def rpc(method, params):
            nonlocal request_id
            request_id += 1
            process.stdin.write(json.dumps({'method': method, 'params': params, 'id': request_id}) + '\n')
            process.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AuthUnavailable('Existing sign-in check timed out.')
                line = messages.get(timeout=remaining)
                if line is None:
                    raise AuthUnavailable('The local app server closed the sign-in connection.')
                message = json.loads(line)
                if message.get('id') != request_id:
                    continue
                if 'error' in message or not isinstance(message.get('result'), dict):
                    raise AuthUnavailable('The local app server does not support the required sign-in handoff.')
                if method == 'initialize':
                    process.stdin.write('{"method":"initialized"}\n')
                    process.stdin.flush()
                return message['result']
        return _exchange(rpc)
    except AuthUnavailable:
        raise
    except (OSError, ValueError, queue.Empty):
        raise AuthUnavailable('Could not reuse the existing ChatGPT sign-in. No credentials were displayed or saved.') from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if reader is not None:
                reader.join(timeout=1)
            if process.stdin:
                process.stdin.close()
            if process.stdout:
                process.stdout.close()


def sign_in():
    """Start the first-party ChatGPT login when no reusable sign-in exists."""
    binary = executable()
    if not binary:
        raise AuthUnavailable('Install the ChatGPT desktop app or Codex CLI to start ChatGPT sign-in. Set DOTS_CODEX if its executable is outside PATH.')
    try:
        result = subprocess.run([binary, 'login'], check=False)
    except OSError:
        raise AuthUnavailable('Could not start ChatGPT sign-in.') from None
    if result.returncode:
        raise AuthUnavailable('ChatGPT sign-in did not complete. Run dots auth to try again.')
    return existing_credentials()
