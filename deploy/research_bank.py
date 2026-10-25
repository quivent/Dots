#!/usr/bin/env python3
"""Append-only research storage, served privately over an authenticated Unix socket."""
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socket
import socketserver
import sqlite3
import struct
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
import pwd


class Bank:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(directory / 'research.sqlite', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS entries(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,request_id TEXT UNIQUE,
            payload TEXT,author TEXT,room TEXT,thread TEXT,created REAL);
        ''')

    def save(self, body):
        if not isinstance(body, dict): raise ValueError('Expected an object')
        data = body.get('entry')
        if not isinstance(data, dict) or set(data) - {'title', 'synthesis', 'sources', 'tags', 'uncertainty', 'supersedes'}:
            raise ValueError('Invalid entry fields')
        for key, maximum in [('title', 200), ('synthesis', 60000), ('uncertainty', 8000)]:
            value = data.get(key, '' if key == 'uncertainty' else None)
            if not isinstance(value, str) or len(value) > maximum or (key != 'uncertainty' and not value.strip()):
                raise ValueError('Invalid ' + key)
        sources, tags = data.get('sources'), data.get('tags')
        if not isinstance(sources, list) or len(sources) > 100 or not isinstance(tags, list) or len(tags) > 20:
            raise ValueError('Provide sources and tags as lists')
        for source in sources:
            if not isinstance(source, dict) or set(source) != {'title', 'url'} or not isinstance(source['title'], str) or not 1 <= len(source['title']) <= 500:
                raise ValueError('Invalid source')
            url = source['url']
            if not isinstance(url, str) or len(url) > 3000: raise ValueError('Invalid source URL')
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Sources must be public-format HTTP or HTTPS links')
        if not all(isinstance(t, str) and 1 <= len(t) <= 60 for t in tags): raise ValueError('Invalid tags')
        for key in ('request_id', 'author', 'room', 'thread'):
            if not isinstance(body.get(key), str) or not 1 <= len(body[key]) <= 200: raise ValueError('Invalid attribution')
        encoded = json.dumps(data, sort_keys=True, ensure_ascii=False)
        if len(encoded.encode()) > 200000: raise ValueError('Entry exceeds 200 KB')
        with self.lock:
            prior = self.conn.execute('SELECT * FROM entries WHERE request_id=?', (body['request_id'],)).fetchone()
            if prior:
                if (prior['payload'], prior['author'], prior['room'], prior['thread']) != (encoded, body['author'], body['room'], body['thread']):
                    raise ValueError('Request ID already belongs to a different entry')
                return self.present(prior)
            parent = data.get('supersedes')
            if parent is not None and (not isinstance(parent, str) or not self.conn.execute('SELECT 1 FROM entries WHERE id=?', (parent,)).fetchone()):
                raise ValueError('Previous entry does not exist')
            identity = str(uuid.uuid4())
            with self.conn:
                self.conn.execute('INSERT INTO entries(id,request_id,payload,author,room,thread,created) VALUES(?,?,?,?,?,?,?)',
                                  (identity, body['request_id'], encoded, body['author'], body['room'], body['thread'], time.time()))
            return self.get(identity)

    def present(self, row, full=True):
        data = json.loads(row['payload'])
        if not full:
            data = {'title': data['title'], 'excerpt': data['synthesis'][:300], 'tags': data['tags'],
                    'source_count': len(data['sources']), 'supersedes': data.get('supersedes')}
        return dict(data, id=row['id'], author=row['author'], room=row['room'], thread=row['thread'], created_at=row['created'])

    def get(self, identity):
        with self.lock:
            row = self.conn.execute('SELECT * FROM entries WHERE id=?', (identity,)).fetchone()
            if row is None: raise KeyError('Entry not found')
            return self.present(row)

    def search(self, query='', before=None):
        if not isinstance(query, str) or len(query) > 300: raise ValueError('Invalid query')
        clauses, values = ['seq<?'], [int(before) if before else 9223372036854775807]
        for word in query.split()[:12]:
            clauses.append("payload LIKE ? ESCAPE '\\'")
            values.append('%' + word.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
        with self.lock:
            rows = self.conn.execute('SELECT * FROM entries WHERE ' + ' AND '.join(clauses) + ' ORDER BY seq DESC LIMIT 26', values).fetchall()
            return {'items': [self.present(r, full=False) for r in rows[:25]],
                    'next_cursor': str(rows[24]['seq']) if len(rows) > 25 else None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')

    def handle_request(self, method):
        status, result = 200, None
        try:
            peer = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
            if peer not in (0, self.server.allowed_uid): raise PermissionError()
            self.connection.settimeout(15)
            path = urlsplit(self.path)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 262144 or self.headers.get('Transfer-Encoding') or (method == 'GET' and length):
                raise ValueError('Invalid request')
            if method == 'POST' and path.path == '/entries':
                result = self.server.bank.save(json.loads(self.rfile.read(length)))
            elif method == 'GET' and path.path == '/entries':
                query = parse_qs(path.query)
                result = self.server.bank.search(query.get('q', [''])[0], query.get('before', [None])[0])
            elif method == 'GET' and path.path.startswith('/entries/'):
                result = self.server.bank.get(path.path[len('/entries/'):])
            else: status, result = 404, {'error': 'Unknown Bank route'}
        except PermissionError: status, result = 403, {'error': 'Bank access denied'}
        except KeyError: status, result = 404, {'error': 'Entry not found'}
        except (ValueError, TypeError, AttributeError): status, result = 400, {'error': 'Invalid Bank entry or query'}
        except Exception: status, result = 503, {'error': 'Bank unavailable; retry with the same request ID'}
        encoded = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(encoded)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


if __name__ == '__main__':
    path = Path('/run/dots-bank/bank.sock')
    path.unlink(missing_ok=True)
    server = Server(str(path), Handler)
    os.chmod(path, 0o660)
    server.allowed_uid = pwd.getpwnam('dots-ops').pw_uid
    server.bank = Bank('/var/lib/dots-bank')
    server.serve_forever()
