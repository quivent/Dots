"""Owner-only quick capture into the canonical FMVision TaskFactory inbox."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from aiohttp import ClientError, ClientSession, ClientTimeout, web

GROUP = 'OPERATOR-INBOX'
TOKEN = Path('/etc/dots-hub/task-database.token')
DATABASE = 'http://127.0.0.1:3750/v1/trackers/fmvisual'


class Rejected(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate(body):
    if not isinstance(body, dict) or set(body) != {'request_id', 'title'}:
        raise Rejected('Supply a request ID and task name.')
    try:
        request_id = str(uuid.UUID(body['request_id']))
    except (ValueError, TypeError, AttributeError):
        raise Rejected('Invalid request ID.') from None
    title = body['title']
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 500 or any(ord(c) < 32 for c in title):
        raise Rejected('Enter a task name of 1 to 500 characters.')
    return request_id, title.strip()


def capture(snapshot, request_id, title):
    """Prepare one CAS mutation; no second task store, claim or invented scope."""
    documents = dict(snapshot['documents'])
    journal = 'notes/task-inbox/' + request_id + '.json'
    digest = hashlib.sha256(title.encode()).hexdigest()
    if journal in documents:
        previous = json.loads(documents[journal])
        if previous['title_sha256'] != digest:
            raise Rejected('This request already saved a different task name.', 409)
        return documents, {**previous['result'], 'revision': snapshot['revision']}, False
    status = json.loads(documents['status.json'])
    # IDs are allocated only against the authoritative, revision-checked snapshot,
    # including archived IDs and prior creation journals.
    highest = 0
    def scan(value):
        nonlocal highest
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ('id', 'task_id') and isinstance(v, str) and re.fullmatch(r'FMV-[0-9]+', v):
                    highest = max(highest, int(v[4:]))
                scan(v)
        elif isinstance(value, list):
            for v in value:
                scan(v)
    for name, raw in documents.items():
        if name.endswith('.json'):
            scan(json.loads(raw))
    task_id = 'FMV-' + str(highest + 1)
    groups, stages = status['groups'], status['stages']
    group = next((g for g in groups if g['id'] == GROUP), None)
    stage = next((s for s in stages if GROUP in s.get('groups', [])), None)
    if group is None:
        group = {'id': GROUP, 'title': 'Jay’s task inbox', 'items': []}
        groups.append(group)
    if stage is None:
        # Captured intentions are visible backlog, not automatically executable
        # engineering tasks with fabricated acceptance tests or write scopes.
        stage = {'id': max((s['id'] for s in stages if type(s.get('id')) is int), default=0) + 1,
                 'name': 'Task inbox', 'track': 'tools', 'state': 'later', 'groups': [GROUP]}
        stages.append(stage)
    task = {'id': task_id, 'text': title, 'state': 'open', 'owner': 'unassigned',
            'lane': 'intake', 'depends_on': [], 'touches': [],
            'next': 'Clarify scope and assign this captured task before execution.',
            'capture': {'request_id': request_id, 'source': 'fmvision-quick-task', 'created_at': time.time()}}
    group['items'].append(task)
    result = {'request_id': request_id, 'task_id': task_id, 'title': title,
              'owner': None, 'status': 'captured', 'revision': snapshot['revision'] + 1}
    documents['status.json'] = json.dumps(status, ensure_ascii=False, indent=2) + '\n'
    documents[journal] = json.dumps({'title_sha256': digest, 'result': result}, ensure_ascii=False) + '\n'
    return documents, result, True


async def save(request_id, title):
    token = TOKEN.read_text().strip()
    headers = {'Authorization': 'Bearer ' + token}
    async with ClientSession(timeout=ClientTimeout(total=25), headers=headers) as client:
        for _ in range(5):
            async with client.get(DATABASE) as response:
                if response.status != 200:
                    raise Rejected('The task list is temporarily unavailable. Your task was not confirmed.', 503)
                snapshot = await response.json()
            documents, result, changed = capture(snapshot, request_id, title)
            if not changed:
                return result
            payload = {'expected_revision': snapshot['revision'], 'documents': documents,
                       'operation_id': 'quick-task-' + request_id + '-r' + str(snapshot['revision'])}
            async with client.put(DATABASE, json=payload) as response:
                if response.status == 409:
                    continue  # Re-read before allocating an ID or replaying a commit.
                if response.status == 423:
                    raise Rejected('The task list is paused for maintenance. Your task name is retained.', 503)
                if response.status != 200:
                    raise Rejected('Saving was not confirmed. Retry with the same request ID.', 503)
                committed = await response.json()
                result['revision'] = committed['revision']
                return result
    raise Rejected('The task list changed while saving. Retry this same task.', 409)


def install(app, authorized, writer=save):
    async def create(request):
        if request.headers.get('Origin') or not await authorized(request):
            raise web.HTTPUnauthorized()
        try:
            if request.content_length is None or request.content_length > 4096:
                raise Rejected('Task request is too large.', 413)
            request_id, title = validate(await request.json())
            result = await writer(request_id, title)
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return web.json_response({'error': str(error)}, status=error.status)
        except (ValueError, TypeError):
            return web.json_response({'error': 'Invalid task request.'}, status=400)
        except (OSError, asyncio.TimeoutError, ClientError):
            return web.json_response({'error': 'Saving was not confirmed. Retry the same task.'}, status=503)
    app.router.add_post('/v1/vmfactory/work/tasks', create)
