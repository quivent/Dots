"""Explicit read/control access to the hosted hub, using its own device credential."""
import json
import os
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from .api import ApiError, DotClient, NoRedirect, valid_credential


class HostedClient:
    path = staticmethod(DotClient.path)

    def __init__(self):
        self.base = os.environ.get('DOTS_HUB_URL', 'https://dots.kosmos.institute').rstrip('/')
        parsed = urlsplit(self.base)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ApiError('DOTS_HUB_URL must be an HTTPS origin without credentials or a path.')
        self.token = os.environ.get('DOTS_HUB_TOKEN')
        if not self.token:
            path = Path(os.environ.get('DOTS_HUB_TOKEN_FILE', str(Path.home() / '.local/share/dots/mobile-token'))).expanduser()
            if not path.is_file() or path.is_symlink() or (os.name != 'nt' and path.stat().st_mode & 0o077):
                raise ApiError('Set DOTS_HUB_TOKEN or DOTS_HUB_TOKEN_FILE to a private hub device credential. ChatGPT credentials are never sent to the hub.')
            self.token = path.read_text(encoding='utf-8').strip()
        if not valid_credential(self.token):
            raise ApiError('Invalid hosted hub credential.')
        self.opener = build_opener(NoRedirect())

    def request(self, method, path, body=None, query=None):
        # No inference sends. Hosted workers consume Codex usage even for conversation.
        if '/messaging/' in path or method not in ('GET', 'POST'):
            raise ApiError('Hosted Codex conversations consume usage. Use an actual ChatGPT Dot for the default terminal chat.')
        if method == 'POST' and not (path.endswith('/runtime/pause') or path.endswith('/runtime/resume')):
            raise ApiError('This hosted operation is not supported by the Dot terminal client.')
        payload = json.dumps(body or {}).encode() if method == 'POST' else None
        request = Request(self.base + '/v1' + path + ('?' + urlencode(query) if query else ''),
                          data=payload, method=method,
                          headers={'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json', 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.loads(response.read())
        except HTTPError as error:
            status = error.code
            error.close()
            raise ApiError(f'Hosted hub request failed (HTTP {status}). No request was retried.', status=status) from None
        except (OSError, HTTPException, ValueError):
            raise ApiError('Could not read the hosted hub response. No request was retried.') from None

    def list(self):
        result = self.request('GET', '/hosted/rooms')
        if (not isinstance(result, dict) or not isinstance(result.get('items'), list)
                or not all(isinstance(e, dict) and isinstance(e.get('id'), str)
                           and isinstance(e.get('display_name'), str) for e in result['items'])):
            raise ApiError('Unexpected hosted catalog response.')
        return result['items']

    def resolve(self, target=None):
        entries = self.list()
        matches = [e for e in entries if e.get('id') == target]
        if not matches and target:
            matches = [e for e in entries if str(e.get('display_name', '')).casefold() == target.casefold()]
        if not target and len(entries) == 1:
            matches = entries
        if len(matches) != 1:
            raise ApiError('Choose a hosted ID or unique name from dots list --source hosted.')
        return matches[0]['id']
