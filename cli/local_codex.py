"""Phone access to explicitly shared threads in an already-running local daemon.

Never launches a second harness or changes a thread's configuration. An
explicitly approved send may resume an opted-in shared thread in this daemon.
The existing Codex client continues to handle native tool/permission requests.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import threading
import uuid

from .api import ApiError

PREFIX = 'mac-codex-'


def native_reply_bindings(entries):
    """Bind visible replies to the preceding native user within their turn.

    Entries arrive newest first. Only identifiers leave this function; hidden
    tool/reasoning data is never published. A later steer replaces that turn's
    request identity instead of authorizing its replies for an earlier prompt.
    """
    requests, replies = {}, {}
    for entry in reversed(entries):
        turn = entry.get('turnId')
        if not isinstance(turn, str) or not turn:
            continue
        item = entry.get('item', {})
        if item.get('type') == 'userMessage':
            request = item.get('clientId') or item.get('id')
            if isinstance(request, str) and request:
                requests[turn] = request
        elif item.get('type') == 'agentMessage' and turn in requests:
            replies[item['id']] = {'turn_id': turn,
                                   'reply_to_request_id': requests[turn]}
    return replies


class DaemonRPC:
    def __init__(self, home):
        self.path = Path(home) / 'app-server-control/app-server-control.sock'

    @contextmanager
    def connection(self):
        import websocket
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(10)
        ws = None
        try:
            sock.connect(str(self.path))
            ws = websocket.create_connection('ws://localhost/', socket=sock,
                                             suppress_origin=True, timeout=15)
            sequence = 0

            def call(method, params):
                nonlocal sequence
                sequence += 1
                identity = sequence
                ws.send(json.dumps({'id': identity, 'method': method, 'params': params}))
                while True:
                    result = json.loads(ws.recv())
                    # Notifications and requests owned by the desktop are not
                    # answered here. Observation alone never resumes a thread.
                    if 'method' in result or result.get('id') != identity:
                        continue
                    if 'error' in result:
                        raise ApiError('Codex rejected the request. Refresh the session before retrying.', 409)
                    return result['result']

            call('initialize', {'clientInfo': {'name': 'dots-local-bridge', 'title': 'Dots', 'version': '1.0.0'},
                                'capabilities': {'experimentalApi': True}})
            ws.send(json.dumps({'method': 'initialized', 'params': {}}))
            yield call
        except ApiError:
            raise
        except (OSError, websocket.WebSocketException, ValueError, KeyError) as error:
            raise ApiError('Local Codex connection unavailable. A write may have been delivered; it will not be replayed.', 502) from error
        finally:
            if ws is not None:
                ws.close()
            sock.close()


class LocalCodexBridge:
    def __init__(self, sessions, database, rpc=None):
        self.sessions = {}
        for entry in sessions:
            identity = str(uuid.UUID(entry['thread_id']))
            if not isinstance(entry['name'], str) or not entry['name'].strip():
                raise ValueError('Name each shared Codex session.')
            self.sessions[identity] = dict(entry, thread_id=identity)
        self.rpc = rpc or DaemonRPC(Path.home() / '.codex')
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(database, check_same_thread=False)
        if str(database) != ':memory:':
            os.chmod(database, 0o600)
        self.conn.execute('CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,thread TEXT,text_hash TEXT,state TEXT,message TEXT)')
        self.conn.commit()

    @classmethod
    def configured(cls, directory):
        directory = Path(directory)
        config = directory / 'local-codex.json'
        if not config.exists():
            return None
        if config.is_symlink() or config.stat().st_mode & 0o077:
            raise ValueError('Local Codex configuration must be private (0600).')
        spec = json.loads(config.read_text())
        home = Path(spec.get('codex_home', str(Path.home() / '.codex'))).expanduser()
        return cls(spec['sessions'], directory / 'local-codex.sqlite', DaemonRPC(home))

    def profile(self, identity, call):
        entry = self.sessions[identity]
        thread = call('thread/read', {'threadId': identity, 'includeTurns': False})['thread']
        status = thread.get('status', {}).get('type', 'unknown')
        return {'id': PREFIX + identity, 'display_name': entry['name'],
                'description': 'Local Codex · ' + status + ' · ' + thread.get('cwd', ''),
                'source': 'local_codex', 'root_thread_id': identity,
                'messaging_room_id': PREFIX + identity, 'is_paused': False,
                'runtime_status': status}

    def catalog(self):
        with self.rpc.connection() as call:
            return [self.profile(identity, call) for identity in self.sessions]

    @staticmethod
    def turns(identity, call, limit=25):
        return call('thread/turns/list', {'threadId': identity, 'limit': limit, 'sortDirection': 'desc'})['data']

    def history(self, identity, query, call):
        cursor = query.get('before')
        rows = []
        entries = []
        # Tool-heavy coordinator turns can contain hundreds of hidden items.
        # Bound each read while preserving a cursor for all earlier history.
        for read_count in range(1, 11):
            params = {'threadId': identity, 'limit': 100, 'sortDirection': 'desc'}
            if cursor:
                params['cursor'] = cursor
            page = call('thread/items/list', params)
            entries.extend(page['data'])
            for entry in page['data']:
                item = entry['item']
                mine = item['type'] == 'userMessage'
                if mine:
                    text = '\n'.join(c['text'] for c in item.get('content', []) if c.get('type') == 'text')
                elif item['type'] == 'agentMessage':
                    text = item.get('text', '')
                else:
                    continue  # Never expose reasoning, tool arguments or outputs.
                if not text:
                    continue
                request = item.get('clientId') if mine else None
                rows.append({'id': request or item['id'], 'content': {'text': text},
                             'role': 'user' if mine else 'assistant', 'sender_is_self': mine,
                             'sender_display_name': self.sessions[identity]['name'],
                             'created_at': (entry.get('startedAtMs') or item.get('startedAtMs') or 0) / 1000,
                             'request_id': request,
                             'turn_id': entry.get('turnId'),
                             'phase': item.get('phase') if not mine else None,
                             'completed_at': (entry.get('completedAtMs') or item.get('completedAtMs') or 0) / 1000})
                if request:
                    with self.lock:
                        self.conn.execute("UPDATE sends SET state='accepted',message=? WHERE id=? AND thread=?",
                                          (request, request, identity))
                        self.conn.commit()
            cursor = page.get('nextCursor')
            if rows or not cursor:
                break
        # Keep the public page/cursor unchanged. Extra bounded reads recover
        # only the request association hidden behind tool-heavy native pages.
        history_cursor = cursor
        visible = {row['id'] for row in rows if row['role'] == 'assistant'}
        identified = {entry['item']['id'] for entry in entries
                      if entry.get('turnId') and entry['item'].get('id') in visible}
        bindings = native_reply_bindings(entries)
        for _ in range(read_count, 10):
            if not cursor or identified <= bindings.keys():
                break
            page = call('thread/items/list', {'threadId': identity, 'limit': 100,
                        'sortDirection': 'desc', 'cursor': cursor})
            entries.extend(page['data'])
            cursor = page.get('nextCursor')
            bindings = native_reply_bindings(entries)
        for row in rows:
            if row['role'] == 'assistant':
                row.update(bindings.get(row['id'], {}))
        return {'items': list(reversed(rows)), 'prev_cursor': history_cursor}

    def submit(self, identity, body, call):
        request = body.get('request_id')
        try:
            valid = isinstance(request, str) and str(uuid.UUID(request)) == request.lower()
        except ValueError:
            valid = False
        content = body.get('content', {})
        text = content.get('text') if isinstance(content, dict) else None
        if (not valid or body.get('idempotency_token') != request
                or not isinstance(text, str) or not text.strip() or len(text) > 12000
                or content.get('attachments') != []):
            raise ValueError('Invalid Codex message.')
        if body.get('work_approved') is not True:
            raise ApiError('Approve this Codex message before sending.', 403)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.lock:
            previous = self.conn.execute('SELECT thread,text_hash,state,message FROM sends WHERE id=?', (request,)).fetchone()
            if previous:
                if previous[:2] != (identity, digest):
                    raise ApiError('Request ID was already used for a different message.', 409)
                if previous[2] == 'accepted':
                    return {'id': previous[3]}
                raise ApiError('Delivery is uncertain. Check the session; this message will not be sent twice.', 409)
            loaded = call('thread/loaded/list', {})['data']
            if identity not in loaded:
                if self.sessions[identity].get('resume_on_send') is not True:
                    raise ApiError('Open this session in Codex on its server first.', 409)
                # Opt-in is operator configuration, never a field accepted from
                # the phone. Resume exactly the retained shared identity with no
                # source/configuration override, new thread, or input replay.
                resumed = call('thread/resume', {'threadId': identity, 'excludeTurns': True})
                if (resumed.get('thread', {}).get('id') != identity
                        or identity not in call('thread/loaded/list', {})['data']):
                    raise ApiError('The original session could not be restored. Nothing was sent.', 409)
            turns = self.turns(identity, call, 1)
            active = next((t for t in turns if t['status'] == 'inProgress'), None)
            # Persist before writing to the daemon. A crash/timeout must never
            # cause a second turn on retry, even after a bridge restart.
            self.conn.execute('INSERT INTO sends VALUES(?,?,?,?,?)', (request, identity, digest, 'unknown', None))
            self.conn.commit()
            params = {'threadId': identity, 'clientUserMessageId': request,
                      'input': [{'type': 'text', 'text': text, 'text_elements': []}]}
            if active:
                params['expectedTurnId'] = active['id']
            call('turn/steer' if active else 'turn/start', params)
            self.conn.execute("UPDATE sends SET state='accepted',message=? WHERE id=?", (request, request))
            self.conn.commit()
            return {'id': request}

    def request(self, method, path, query, body):
        match = re.fullmatch(r'/(?:tbo|messaging/rooms)/' + PREFIX + r'([0-9a-f-]{36})(.*)', path)
        if not match:
            return None
        identity, suffix = match.groups()
        if identity not in self.sessions:
            raise ApiError('This Codex session has not been shared with Dots.', 404)
        with self.rpc.connection() as call:
            if path.startswith('/tbo/'):
                if method == 'GET' and suffix == '':
                    return self.profile(identity, call)
                if method == 'GET' and suffix in ('/tasks', '/activity'):
                    return {'data': [{'id': t['id'], 'title': self.sessions[identity]['name'],
                                      'status': 'running' if t['status'] == 'inProgress' else t['status'],
                                      'description': 'Local Codex · native approvals remain in Codex on the Mac',
                                      'created_at': t.get('startedAt') or 0}
                                     for t in self.turns(identity, call)]}
                if method == 'POST' and suffix == '/runtime/pause' and not body:
                    active = next((t for t in self.turns(identity, call, 1) if t['status'] == 'inProgress'), None)
                    if active:
                        call('turn/interrupt', {'threadId': identity, 'turnId': active['id']})
                    return {'ok': True}
            elif suffix == '/messages':
                if method == 'GET':
                    return self.history(identity, query, call)
                if method == 'POST':
                    return self.submit(identity, body, call)
        raise ValueError('Unsupported local Codex action.')
