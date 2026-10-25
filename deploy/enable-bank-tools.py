#!/usr/bin/env python3
"""Install native Bank tools on empty agent sessions without starting a model turn.

The installed protocol registers tools on thread/start only. Preserve the old
empty thread IDs, verify every session is empty, and atomically switch registry.
Never replace an agent session that already contains conversation.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import tomllib
import websocket
from bank_client import TOOLS

ROOT = Path('/var/lib/dots-ops')


class Client:
    def __init__(self, slug):
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(20)
        sock.connect('/run/dots-agent-' + slug + '/control.sock')
        self.ws = websocket.create_connection('ws://localhost/', socket=sock, suppress_origin=True, timeout=20)
        self.sequence = 0
        self.call('initialize', {'clientInfo': {'name': 'dots-bank-setup', 'version': '1.0.0'}, 'capabilities': {'experimentalApi': True}})
        self.ws.send(json.dumps({'method': 'initialized', 'params': {}}))

    def call(self, method, params):
        self.sequence += 1
        identity = self.sequence
        self.ws.send(json.dumps({'id': identity, 'method': method, 'params': params}))
        while True:
            obj = json.loads(self.ws.recv())
            if obj.get('id') == identity and 'method' not in obj:
                if 'error' in obj: raise RuntimeError(str(obj['error']))
                return obj['result']


def prepare():
    registry = json.loads((ROOT / 'agents.json').read_text())
    clients = {}
    try:
        for name, entry in registry.items():
            if entry.get('bank_tools_version') == 1: continue
            client = clients[name] = Client(entry['profile'])
            result = client.call('thread/read', {'threadId': entry['thread_id'], 'includeTurns': True})
            if result['thread'].get('turns'):
                raise RuntimeError('Refusing to replace a nonempty saved session: ' + name)
        for name, client in clients.items():
            entry = registry[name]
            profile = tomllib.loads((ROOT / '.codex' / (entry['profile'] + '.config.toml')).read_text())
            result = client.call('thread/start', {'cwd': entry['workspace'], 'approvalPolicy': 'on-request',
                'approvalsReviewer': 'user', 'config': {'default_permissions': ':workspace'},
                'developerInstructions': profile['developer_instructions'], 'dynamicTools': TOOLS})
            identity = result['thread']['id']
            client.call('thread/name/set', {'threadId': identity, 'name': name})
            entry['previous_empty_thread_id'] = entry['thread_id']
            entry['thread_id'] = identity
            entry['bank_tools_version'] = 1
        print(json.dumps(registry))
    finally:
        for client in clients.values(): client.ws.close()


if __name__ == '__main__':
    if '--prepare' in sys.argv:
        prepare()
    else:
        path = ROOT / 'agents.json'
        before = path.read_bytes()
        output = subprocess.check_output(['runuser', '-u', 'dots-ops', '--', '/usr/bin/python3', __file__, '--prepare'])
        updated = json.loads(output)
        if path.read_bytes() != before: raise SystemExit('Registry changed; refusing overwrite')
        backup = ROOT / 'agents.before-bank.json'
        if not backup.exists():
            backup.write_bytes(before); os.chmod(backup, 0o640); os.chown(backup, path.stat().st_uid, path.stat().st_gid)
        fd, temporary = tempfile.mkstemp(dir=ROOT)
        os.fchmod(fd, 0o640); os.fchown(fd, path.stat().st_uid, path.stat().st_gid)
        with os.fdopen(fd, 'w') as out: json.dump(updated, out, indent=2)
        os.replace(temporary, path)
        print('Bank tools registered for ' + ', '.join(updated) + '; no model turns started')
