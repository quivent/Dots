#!/usr/bin/env python3
"""Create idle named Codex sessions through its local protocol, without turns."""
import json
import os
import pwd
from pathlib import Path
import selectors
import subprocess
import tempfile
import time

ROOT = Path('/var/lib/dots-ops')
CODEX = '/opt/dots-codex/node_modules/.bin/codex'
REGISTRY = ROOT / 'agents.json'
NAMES = ('Wavesmith', 'Oscillator', 'Belle')


class Protocol:
    def __init__(self):
        self.proc = subprocess.Popen(
            ['runuser', '-u', 'dots-ops', '--', CODEX, 'app-server', '--listen', 'stdio://'],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0)
        self.sequence = 0
        self.buffer = b''
        self.lines = []
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.call('initialize', {'clientInfo': {'name': 'dots-host-setup', 'version': '1.0.0'}})
        self.send({'method': 'initialized', 'params': {}})

    def send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + '\n').encode())
        self.proc.stdin.flush()

    def call(self, method, params):
        self.sequence += 1
        identity = self.sequence
        self.send({'id': identity, 'method': method, 'params': params})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if not self.lines:
                if not self.selector.select(timeout=1):
                    if self.proc.poll() is not None:
                        raise RuntimeError('Codex protocol exited')
                    continue
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError('Codex protocol closed')
                pieces = (self.buffer + chunk).split(b'\n')
                self.lines.extend(pieces[:-1]); self.buffer = pieces[-1]
                if not self.lines:
                    continue
            line = self.lines.pop(0)
            obj = json.loads(line)
            if obj.get('id') == identity and 'method' not in obj:
                if 'error' in obj:
                    raise RuntimeError(f'{method}: {obj["error"].get("message", "failed")}')
                return obj['result']
            # Setup never grants a tool, execution or permission request.
            if 'method' in obj and 'id' in obj:
                self.send({'id': obj['id'], 'error': {'code': -32601, 'message': 'Idle setup only'}})
        raise TimeoutError(method)

    def close(self):
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        self.selector.close()


def save_registry(registry):
    fd, name = tempfile.mkstemp(dir=ROOT, prefix='.agents-')
    try:
        os.fchmod(fd, 0o640)
        os.fchown(fd, 0, pwd.getpwnam('dots-ops').pw_gid)
        with os.fdopen(fd, 'w') as stream:
            json.dump(registry, stream, indent=2)
            stream.write('\n')
        os.replace(name, REGISTRY)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    client = Protocol()
    try:
        for name in NAMES:
            if name in registry:
                print(f'{name}: already registered')
                continue
            slug = name.lower()
            workspace = ROOT / 'agents' / slug
            if not workspace.is_dir():
                raise RuntimeError(f'Prepare workspace first: {workspace}')
            instructions = (
                f'Your name is {name}. You are a hosted agent on Jay\'s Dots server. '
                'Only start work when the user requests or approves that task. '
                'Keep work inside your workspace unless the user explicitly approves broader access. '
                'Before live server changes, show the exact commands or diff, impact and rollback, '
                'then request manual approval. Never bypass the sandbox or approval mechanism. '
                'Do not schedule recurring work, delegate tasks or access credentials without approval. '
                'Ordinary conversation and read-only research may proceed. '
                'Report context and usage only when known; do not invent counters.')
            profile = ROOT / '.codex' / (slug + '.config.toml')
            if not profile.exists():
                profile.write_text('default_permissions = ":workspace"\n'
                                   'approval_policy = "on-request"\n'
                                   'approvals_reviewer = "user"\n'
                                   'developer_instructions = ' + json.dumps(instructions) + '\n')
                profile.chmod(0o644)
            result = client.call('thread/start', {
                'cwd': str(workspace), 'ephemeral': False,
                'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
                'developerInstructions': instructions,
                'config': {'default_permissions': ':workspace'},
            })
            thread = result['thread']['id']
            # Save immediately so a naming/verification interruption cannot create twice.
            registry[name] = {'name': name, 'thread_id': thread, 'workspace': str(workspace),
                              'profile': slug, 'setup_state': 'created', 'turns_started': 0}
            save_registry(registry)
            client.call('thread/name/set', {'threadId': thread, 'name': name})
            registry[name]['setup_state'] = 'named'
            save_registry(registry)
            print(f'{name}: created and named; no task started')
    finally:
        client.close()

    # Verify the saved sessions survive a new local app-server process.
    client = Protocol()
    try:
        for name in NAMES:
            item = registry[name]
            result = client.call('thread/resume', {
                'threadId': item['thread_id'], 'cwd': item['workspace'],
                'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
                'config': {'default_permissions': ':workspace'},
            })
            if result['thread']['id'] != item['thread_id']:
                raise RuntimeError('Unexpected session identity')
            item['setup_state'] = 'verified'
            save_registry(registry)
            print(f'{name}: saved session verified after reconnect')
    finally:
        client.close()


if __name__ == '__main__':
    main()
