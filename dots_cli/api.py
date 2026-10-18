"""Experimental client for the account-scoped Dot routes observed in ChatGPT.

These are internal routes, not the public /v1/agents API. Never retries writes.
Reuses the local app-server login or explicit credentials; never reads session stores directly.
"""
from __future__ import annotations

import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE_URL = 'https://chatgpt.com/backend-api'
SERVICE = 'dots-cli'


class ApiError(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward account credentials to a redirected host.


def credential_store():
    import keyring
    try:
        backend = keyring.get_keyring()
    except Exception:
        raise ApiError('Could not initialize the OS credential store. Use environment credentials instead.') from None
    # Only OS-backed stores. Never silently use a plaintext fallback plugin.
    module = type(backend).__module__
    if module not in ('keyring.backends.macOS', 'keyring.backends.Windows',
                      'keyring.backends.SecretService', 'keyring.backends.kwallet'):
        raise ApiError('No supported OS credential store. Use DOTS_ACCESS_TOKEN and DOTS_ACCOUNT_ID in this process instead.')
    return SecureStore(backend)


class SecureStore:
    def __init__(self, backend):
        self.backend = backend

    def _call(self, method, *args):
        try:
            return getattr(self.backend, method)(*args)
        except Exception:
            raise ApiError('Could not access the OS credential store. Check that it is unlocked, or use environment credentials.') from None

    def get_password(self, *args):
        return self._call('get_password', *args)

    def set_password(self, *args):
        return self._call('set_password', *args)

    def delete_password(self, *args):
        return self._call('delete_password', *args)


def credentials():
    token, account = os.environ.get('DOTS_ACCESS_TOKEN', ''), os.environ.get('DOTS_ACCOUNT_ID', '')
    if token:
        return token, account, 'environment'
    try:
        saved = credential_store().get_password(SERVICE, 'account')
        if saved:
            data = json.loads(saved)
            return data['token'], account or data['account_id'], 'OS credential store'
    except (ImportError, ApiError, ValueError, KeyError):
        pass
    from .auth import AuthUnavailable, existing_credentials
    try:
        token, existing_account = existing_credentials()
        return token, account or existing_account, 'existing ChatGPT sign-in'
    except AuthUnavailable:
        return '', account, 'none'


class DotClient:
    def __init__(self, token=None, account_id=None, opener=None):
        if token is None:
            token, saved_account, _ = credentials()
            account_id = account_id or saved_account
        self.token, self.account_id = token, account_id
        self.opener = opener or build_opener(NoRedirect())

    def request(self, method, path, body=None, query=None):
        if not self.token or not self.account_id:
            raise ApiError('No usable ChatGPT sign-in found. Run dots auth to sign in, then dots check. Run dots auth --help for explicit credential alternatives. An OpenAI API key does not provide Dot account access.')
        if not isinstance(self.token, str) or not isinstance(self.account_id, str) or not (self.token + self.account_id).isascii() or any(c in self.token + self.account_id for c in '\r\n\0'):
            raise ApiError('Invalid account credential.')
        url = BASE_URL + path + ('?' + urlencode(query) if query else '')
        payload = json.dumps(body).encode('utf-8') if body is not None else None
        request = Request(url, data=payload, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'ChatGPT-Account-Id': self.account_id,
            'Accept': 'application/json', 'Content-Type': 'application/json',
            'User-Agent': 'dots-cli/0.2.2',
        })
        try:
            with self.opener.open(request, timeout=540 if method == 'POST' and path == '/tbo' else 30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            error.close()
            messages = {401: 'Account authorization expired or was rejected. Check your ChatGPT/Codex sign-in, then run dots check.',
                        403: 'Dot access was denied. Check account eligibility, workspace permissions, and credential scope.',
                        404: 'Dot or internal route not found.',
                        409: 'Account state conflict. Check dots list before retrying creation.',
                        429: 'Rate limited. Wait before trying again.'}
            # Do not print raw responses, request headers, or token-bearing exception URLs.
            message = messages.get(error.code, 'Internal Dot API request failed.')
            if method != 'GET' and error.code >= 500:
                message += ' Outcome unknown; inspect dots list/activity before repeating the command.'
            raise ApiError(f'{message} (HTTP {error.code})', status=error.code) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            suffix = ' Outcome unknown; inspect dots list/activity before repeating the command.' if method != 'GET' else ''
            raise ApiError('Could not reach the Dot API.' + suffix) from None
        except (ValueError, UnicodeError):
            suffix = ' The write may have succeeded; check dots list/activity before repeating it.' if method != 'GET' else ''
            raise ApiError('Unexpected response from the internal Dot API.' + suffix) from None

    @staticmethod
    def path(dot_id):
        if not dot_id or not isinstance(dot_id, str) or not dot_id.isprintable():
            raise ApiError('Use a Dot ID from dots list.')
        return '/tbo/' + quote(dot_id, safe='')

    def pages(self, path, limit=25, catalog=False):
        items, cursor, seen = [], '', set()
        for _ in range(1000):
            query = {'limit': limit}
            if cursor:
                query['cursor'] = cursor
            if catalog:
                query['include_room_preview'] = 'false'
            page = self.request('GET', path, query=query)
            key = 'items' if catalog else 'data'
            if not isinstance(page, dict) or not isinstance(page.get(key), list):
                raise ApiError('Unexpected collection response from the internal Dot API.')
            items.extend(page[key])
            cursor = page.get('cursor') if catalog else page.get('next_cursor', page.get('cursor'))
            if not cursor:
                return items
            if not isinstance(cursor, str) or cursor in seen:
                raise ApiError('Dot API pagination did not advance.')
            seen.add(cursor)
        raise ApiError('Dot API pagination exceeded its safety limit.')

    def list(self):
        return self.pages('/tbo', catalog=True)

    def resolve(self, target=None):
        entries = self.list()
        if target:
            exact = [e for e in entries if e.get('id') == target]
            matches = exact or [e for e in entries if str(e.get('display_name', '')).casefold() == target.casefold()]
        else:
            if len(entries) == 1:
                matches = entries
            else:
                primary = self.request('GET', '/tbo/primary')
                profile = primary.get('profile') if isinstance(primary, dict) else None
                if isinstance(profile, dict) and profile.get('id') in [e.get('id') for e in entries]:
                    return profile['id']
                raise ApiError('Specify a Dot ID or unique name, or select one with dots use.')
        if len(matches) != 1:
            raise ApiError('Dot not found or name is ambiguous. Use its ID from dots list.')
        return matches[0]['id']

    def create(self, name, additional=None):
        if additional is None:
            additional = bool(self.list())  # Auto-detect unless caller explicitly chooses.
        result = self.request('POST', '/tbo', {
            'display_name': name, 'create_thread': True,
            'create_additional': additional, 'should_initialize': True,
        })
        if not isinstance(result, dict) or not result.get('id') or not result.get('root_thread_id'):
            raise ApiError('Creation returned an incomplete profile. Outcome unknown; run dots list before retrying.')
        return result
