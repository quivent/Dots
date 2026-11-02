"""Use the existing authenticated loopback relay for terminal conversations."""
from pathlib import Path

from .api import ApiError, DotClient


class RelayClient(DotClient):
    base_url = 'http://127.0.0.1:8769/v1'

    def __init__(self, token):
        super().__init__(token=token, account_id='local-relay')

    def request(self, method, path, body=None, query=None):
        try:
            return super().request(method, path, body=body, query=query)
        except ApiError as error:
            raise ApiError(f'Local Dots relay: {method} {path}: {error}',
                           status=error.status) from None


def conversation_client():
    path = Path.home() / '.local/share/dots/mobile-token'
    try:
        token = path.read_text().strip()
    except FileNotFoundError:
        return DotClient()
    # Once configured, keep the relay as the transport. A transient health
    # failure must not silently switch to a different account/login route.
    return RelayClient(token)
