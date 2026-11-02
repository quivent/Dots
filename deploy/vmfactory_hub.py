#!/usr/bin/env python3
"""Persistent central state + WebSocket deltas for paired VMFactory clients.

Publishers have fixed metadata/agent scopes. Paired owners read state and
explicitly send text or stop a turn; no shell or arbitrary filesystem API exists.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
from aiohttp import web, ClientSession, ClientTimeout, WSMsgType
from task_store import TaskStore
from work_replica import WorkReplica
from studio_access import StudioAccess, view_digest
from asset_store import AssetStore,MAX_BLOB
from agent_notifications import AgentNotifications

DATA = Path('/var/lib/dots-ops/chat-hub/vmfactory-sync.sqlite')
PUBLISHER = Path('/etc/dots-hub/vmfactory-publisher.sha256')
AUTH_HEALTH = 'http://127.0.0.1:18770/v1/health'
KEYS = {'discoveries', 'tasks', 'roster', 'inventory', 'crew', 'worker', 'maestroHistory', 'agents', 'work', 'worlds', 'reports', 'assets'}


class State:
    def __init__(self, path=DATA):
        self.path = Path(path)
        self.data = {'schema': 'vmfactory.mobile-snapshot/1'}
        self.clients = set()
        self.client_access = {}
        self.read_views = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS records(key TEXT PRIMARY KEY,payload TEXT); CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,revision TEXT,keys TEXT,received REAL);')
        for key, payload in self.db.execute('SELECT key,payload FROM records'):
            if key in KEYS: self.data[key] = json.loads(payload)
        self.notifications = AgentNotifications(self.db)
        self.tasks = TaskStore(self.db)
        with self.db:
            for key in ('tasks','worker'):
                if key in self.data:
                    (self.tasks.save_tasks if key=='tasks' else self.tasks.save_worker)(self.data[key])
                    self.db.execute('DELETE FROM records WHERE key=?',(key,))
                value = self.tasks.tasks() if key=='tasks' else self.tasks.worker()
                if value is not None:self.data[key]=value
        self.work = WorkReplica(self.db)
        existing=self.data.get('work') or self.work.snapshot()
        if existing:
            self.data['work']=existing
            with self.db:
                self.work.save(existing)
                self.db.execute("DELETE FROM records WHERE key='work'")
        self.revision = self.digest()
        self.sequence = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0]
        self.publishers = 0
        self.publisher_channels = {}
        self.publisher_scopes = {}
        self.requests = {}
        self.drafts = {}
        self.wire_sequence = 0
        self.epoch = secrets.token_hex(12)

    def close(self):
        self.db.close()

    def digest(self):
        return hashlib.sha256(json.dumps(self.data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def agents(self):
        agents = {key: dict(value) for key, value in self.data.get('agents', {}).items()}
        agents['maestro'] = dict(agents.get('maestro', {}), id='maestro', name='Maestro', server='Mac', history=self.history())
        for identity, value in agents.items():
            value['relayOnline'] = any(identity in scope['agents'] for scope in self.publisher_scopes.values())
            if identity != 'maestro': value['history'] = self.history(identity)
        return agents

    def snapshot(self):
        return dict(self.data, revision=self.revision, sequence=self.sequence, source='central-hub', publisherOnline=self.publishers > 0, wireSequence=self.wire_sequence, epoch=self.epoch, maestroHistory=self.history(), agents=self.agents())


    def reader_view(self, access):
        source = dict(self.data)
        source['agents'] = {identity: dict(value, relayOnline=any(identity in scope['agents'] for scope in self.publisher_scopes.values()))
                            for identity, value in self.data.get('agents', {}).items()}
        projected = access.snapshot(source)
        if access.key not in self.read_views:
            self.read_views[access.key] = {'sequence': 0, 'revision': view_digest(projected),
                'epoch': hashlib.sha256((self.epoch + ':' + access.key).encode()).hexdigest()[:24]}
        return self.read_views[access.key], projected

    def snapshot_for(self, access):
        if access.owner:
            return access.snapshot(self.snapshot())
        view, projected = self.reader_view(access)
        return dict(projected, revision=view_digest(projected), epoch=view['epoch'],
                    wireSequence=view['sequence'], sequence=view['sequence'])

    def history(self, agent='maestro'):
        cached = self.data.get('maestroHistory', {'items': [], 'prev_cursor': None}) if agent == 'maestro' else self.data.get('agents', {}).get(agent, {}).get('history', {'items': [], 'prev_cursor': None})
        rows = {row['id']: row for row in cached.get('items', [])}
        for key, draft in self.drafts.items():
            if draft.get('agent', 'maestro') != agent: continue
            identity=draft['id']
            rows[identity] = {'id': identity, 'content': {'text': draft['text']}, 'sender_is_self': False, 'role': 'assistant', 'created_at': draft['created']}
        return dict(cached, items=sorted(rows.values(), key=lambda row: row.get('created_at', 0)))

    def append_delta(self, identity, text, agent='maestro'):
        key=agent+':'+identity
        if key not in self.drafts:
            existing=next((r for r in self.history(agent).get('items', []) if r['id']==identity),{})
            self.drafts[key]={'id':identity,'agent':agent,'text':existing.get('content',{}).get('text',''),'created':existing.get('created_at',time.time())}
        draft=self.drafts[key]
        if len(draft['text'])+len(text)>1024*1024:raise ValueError('Visible draft exceeds stream bound')
        draft['text']+=text
        if len(self.drafts)>64:self.drafts.pop(next(iter(self.drafts)))

    def publish(self, changes):
        if not isinstance(changes, dict) or not set(changes) <= KEYS or not all(isinstance(v, dict) for v in changes.values()):
            raise ValueError('Unsupported published data')
        changes=dict(changes)
        activity_ids={id for id,value in changes.get("agents",{}).items() if isinstance(value,dict) and ("working" in value or "activityKnown" in value)}
        if 'work' in changes:changes['work']=self.work.apply(changes['work'],self.data.get('work'))
        if 'agents' in changes:
            merged={key:dict(value) for key,value in self.data.get('agents',{}).items()}
            for identity,value in changes['agents'].items():
                if not isinstance(value,dict):raise ValueError('Invalid agent record')
                merged[identity]=dict(merged.get(identity,{}),**value)
            changes['agents']=merged
        delta = {k: v for k, v in changes.items() if self.data.get(k) != v}
        if not delta:
            return {}
        updated = dict(self.data, **delta)
        revision = hashlib.sha256(json.dumps(updated, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with self.db:
            for key, value in delta.items():
                if key=='tasks':self.tasks.save_tasks(value)
                elif key=='worker':self.tasks.save_worker(value)
                elif key=='work':self.work.save(value)
                else:self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?)', (key, json.dumps(value, separators=(',', ':'))))
            cursor = self.db.execute('INSERT INTO events(revision,keys,received) VALUES(?,?,?)', (revision, json.dumps(sorted(delta)), time.time()))
            sequence = cursor.lastrowid
            self.db.execute('DELETE FROM events WHERE seq <= ?', (sequence - 2048,))
        self.data, self.revision, self.sequence = updated, revision, sequence
        for row in delta.get('maestroHistory', {}).get('items', []):
            identity = row.get('id')
            key='maestro:'+str(identity)
            if key in self.drafts and len(row.get('content',{}).get('text',''))>=len(self.drafts[key]['text']):del self.drafts[key]
        for agent,value in delta.get('agents',{}).items():
            for row in value.get('history',{}).get('items',[]):
                key=agent+':'+str(row.get('id'))
                if key in self.drafts and len(row.get('content',{}).get('text',''))>=len(self.drafts[key]['text']):del self.drafts[key]
        if 'agents' in delta:self.notifications.observe({id:delta['agents'][id] for id in activity_ids})
        return delta

    def broadcast(self, value):
        self.wire_sequence += 1
        value = dict(value, eventSequence=self.wire_sequence, epoch=self.epoch)
        owner_text = json.dumps(value, separators=(',', ':'))
        read_messages = {}
        for queue in tuple(self.clients):
            access = self.client_access.get(queue)
            text = owner_text
            if access is not None and not access.owner:
                if access.key not in read_messages:
                    view, projected = self.reader_view(access)
                    revision = view_digest(projected)
                    text = None
                    if revision != view['revision']:
                        view['sequence'] += 1
                        view['revision'] = revision
                        changes = {key: item for key, item in projected.items() if key not in ('schema', 'source')}
                        text = json.dumps({'type': 'update', 'revision': revision, 'changes': changes,
                                           'eventSequence': view['sequence'], 'epoch': view['epoch']}, separators=(',', ':'))
                    read_messages[access.key] = text
                text = read_messages[access.key]
            if text is None:
                continue
            try:
                queue.put_nowait(text)
            except asyncio.QueueFull:
                self.clients.discard(queue)
                while not queue.empty(): queue.get_nowait()
                queue.put_nowait(None)


def bearer(request):
    value = request.headers.get('Authorization', '')
    return value[7:] if value.startswith('Bearer ') and len(value) <= 300 else ''


def publisher_authorized(token, path=PUBLISHER):
    if not token: return False
    try:
        return secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(), Path(path).read_text().strip())
    except OSError:
        return False


def publisher_scope(token):
    if publisher_authorized(token):return {'agents':['maestro'],'metadata':True,'source':'mac'}
    try:
        registry=json.loads(Path('/etc/dots-hub/vmfactory-publishers.json').read_text())
        value=registry.get(hashlib.sha256(token.encode()).hexdigest())
        if isinstance(value,dict) and isinstance(value.get('agents'),list) and value['agents'] and all(isinstance(a,str) and 0<len(a)<=64 for a in value['agents']):return value
    except (OSError,ValueError):pass
    return None


async def identity_health(request):
    token = bearer(request)
    if not token:
        return None
    try:
        async with request.app['http'].get(AUTH_HEALTH, headers={'Authorization': 'Bearer ' + token}) as response:
            if response.status != 200:
                return None
            value = await response.json()
            return value if isinstance(value, dict) else None
    except Exception:
        return None


async def viewer_authorized(request):
    # Existing private routes remain owner-only. The request value is refreshed
    # on every call, including WebSocket revocation checks; never a token cache.
    health = await identity_health(request)
    request['studio_identity_health'] = health
    return isinstance(health, dict) and health.get('scope') == 'owner'


async def viewer_access(request):
    request['studio_identity_health'] = None
    if await viewer_authorized(request):
        return StudioAccess.owner_access()
    return StudioAccess.from_health(request.get('studio_identity_health'))


def denied_studio_view(request):
    health = request.get('studio_identity_health')
    if isinstance(health, dict) and health.get('scope') == 'hosted':
        return web.json_response({'error': 'studio_access_required',
            'message': 'This invitation does not include Studio tasks or crew. Request a Studio invitation from its owner.'}, status=403)
    return web.json_response({'error': 'studio_authentication_required',
        'message': 'Join your Studio or reconnect this device.'}, status=401)


async def register_notifications(request):
    if request.headers.get('Origin') or not await viewer_authorized(request):raise web.HTTPUnauthorized()
    try:
        return web.json_response(request.app['state'].notifications.register(bearer(request),await request.json()))
    except (ValueError,KeyError,TypeError):raise web.HTTPBadRequest(text='Invalid notification registration')


async def asset(request):
    if request.headers.get('Origin'):raise web.HTTPForbidden()
    scope=publisher_scope(bearer(request))
    if request.method=='PUT':
        if not scope or not scope.get('metadata'):raise web.HTTPUnauthorized()
    elif not (scope and scope.get('metadata')) and not await viewer_authorized(request):raise web.HTTPUnauthorized()
    store=request.app['assets']
    try:
        path=store.path(request.match_info['digest'])
        if request.method=='PUT':
            if request.content_length is not None and request.content_length>MAX_BLOB:raise web.HTTPRequestEntityTooLarge(max_size=MAX_BLOB,actual_size=request.content_length)
            size=await store.receive(request.match_info['digest'],request.content.iter_chunked(128*1024))
            return web.json_response({'bytes':size})
        if not path.is_file():raise web.HTTPNotFound()
        return web.FileResponse(path,headers={'Cache-Control':'private, max-age=31536000, immutable','ETag':'"'+path.name+'"','Content-Type':'application/octet-stream'})
    except ValueError as error:raise web.HTTPBadRequest(text=str(error))


async def snapshot(request):
    if request.headers.get('Origin'):
        raise web.HTTPUnauthorized()
    access = await viewer_access(request)
    if access is None:
        return denied_studio_view(request)
    value = request.app['state'].snapshot_for(access)
    etag = '"' + value['revision'] + '"'
    if request.headers.get('If-None-Match') == etag:
        return web.Response(status=304, headers={'ETag': etag, 'Cache-Control': 'no-cache'})
    response = web.json_response(value, headers={'ETag': etag, 'Cache-Control': 'no-cache'})
    response.enable_compression()
    return response


async def history(request):
    if request.headers.get('Origin'):
        raise web.HTTPUnauthorized()
    if not await viewer_authorized(request):
        health = request.get('studio_identity_health')
        if isinstance(health,dict) and health.get('scope')=='hosted':
            return web.json_response({'error':'studio_read_only','message':'Private agent history requires an owner connection.'},status=403)
        raise web.HTTPUnauthorized()
    agent=request.match_info.get('agent','maestro')
    if agent!='maestro' and agent not in request.app['state'].data.get('agents',{}):raise web.HTTPNotFound()
    value = request.app['state'].history(agent)
    if value is None:
        return web.json_response({'error': 'Waiting for the Mac to publish Maestro history.'}, status=503)
    response = web.json_response(value, headers={'Cache-Control': 'no-store'})
    response.enable_compression()
    return response


async def connect(request):
    if request.headers.get('Origin'):
        raise web.HTTPForbidden()
    publishing = request.query.get('role') == 'publisher'
    scope=publisher_scope(bearer(request)) if publishing else None
    access = None
    if publishing:
        if scope is None:raise web.HTTPUnauthorized()
    else:
        access = await viewer_access(request)
        if access is None:
            return denied_studio_view(request)
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=2 * 1024 * 1024, compress=False)
    await ws.prepare(request)
    state = request.app['state']
    if publishing:
        state.publishers += 1
        state.notifications.reset(scope["agents"])
    ready = {'type': 'ready', 'revision': state.revision, 'sequence': state.sequence, 'epoch': state.epoch, 'eventSequence': state.wire_sequence}
    if access is not None and not access.owner:
        initial = state.snapshot_for(access)
        ready.update(revision=initial['revision'], sequence=initial['sequence'], epoch=initial['epoch'], eventSequence=initial['wireSequence'])
    await ws.send_json(ready)
    queue = asyncio.Queue(maxsize=64)
    if publishing: state.publisher_channels[ws] = queue;state.publisher_scopes[ws]=scope
    else:
        state.clients.add(queue)
        state.client_access[queue] = access
    async def write():
        while True:
            text = await queue.get()
            if text is None:
                await ws.close(code=1013, message=b'Reconnect to recover current state')
                return
            if access is not None and not access.owner and await viewer_access(request) != access:
                await ws.close(code=1008, message=b'Studio access changed or was revoked')
                return
            await ws.send_str(text)
    writer = asyncio.create_task(write())
    async def authorize_again():
        while not ws.closed:
            await asyncio.sleep(30)
            valid = publisher_scope(bearer(request)) == scope if publishing else await viewer_access(request) == access
            if not valid:
                await ws.close(code=1008, message=b'Connection authorization revoked')
                return
    authorization = asyncio.create_task(authorize_again())
    try:
        async for message in ws:
            if message.type != WSMsgType.TEXT:
                continue
            if not publishing:
                try:
                    value = json.loads(message.data)
                    if not isinstance(value, dict):raise ValueError('Invalid request')
                    identity, operation, body = value.get('id'), value.get('operation'), value.get('body', {})
                    agent=value.get('agentId','maestro')
                    if not isinstance(agent,str) or not 0<len(agent)<=64:raise ValueError('Invalid agent')
                    if value.get('type') != 'request' or not isinstance(identity, str) or str(uuid.UUID(identity)) != identity.lower() or operation not in ('send', 'stop', 'inspect') or not isinstance(body, dict):
                        raise ValueError('Unsupported request')
                    if not access.owner:
                        queue.put_nowait(json.dumps({'type':'rpcResult','id':identity,'status':403,'body':{'error':'studio_read_only','message':'This Studio invitation allows reading tasks and crew, not private history or agent controls.'}}))
                        continue
                    if operation == 'send':
                        content = body.get('content', {})
                        if (body.get('request_id') != identity or body.get('idempotency_token') != identity or body.get('work_approved') is not True or not isinstance(content, dict) or content.get('attachments') != [] or not isinstance(content.get('text'), str) or not content['text'].strip() or len(content['text']) > 12000):
                            raise ValueError('Invalid explicit message')
                    elif body:
                        raise ValueError('Stop and inspect take no fields')
                    if operation == 'inspect' and state.data.get('agents',{}).get(agent,{}).get('capabilities',{}).get('inspect') is not True:
                        queue.put_nowait(json.dumps({'type':'rpcResult','id':identity,'status':501,'body':{'error':'This publisher does not support read-only inspection.'}}))
                        continue
                    if identity in state.requests:
                        queue.put_nowait(json.dumps({'type':'rpcResult','id':identity,'status':409,'body':{'error':'This request is already in progress.'}}))
                        continue
                    publishers = [p for p in state.publisher_channels if not p.closed and agent in state.publisher_scopes[p]['agents']]
                    if not publishers:
                        queue.put_nowait(json.dumps({'type':'rpcResult','id':identity,'status':503,'body':{'error':'This agent’s server is offline. Nothing was queued.'}}))
                        continue
                    publisher = publishers[-1]
                    state.requests[identity] = (queue, publisher)
                    state.publisher_channels[publisher].put_nowait(json.dumps({'type':'request','id':identity,'operation':operation,'body':body,'agentId':agent}))
                    async def timeout(identity=identity, owner=queue):
                        await asyncio.sleep(30)
                        waiting = state.requests.get(identity)
                        if waiting and waiting[0] is owner:
                            state.requests.pop(identity, None)
                            try: owner.put_nowait(json.dumps({'type':'rpcResult','id':identity,'status':504,'body':{'error':'Delivery could not be confirmed. No automatic retry was made.'}}))
                            except asyncio.QueueFull: pass
                    asyncio.create_task(timeout())
                except (ValueError, TypeError, KeyError, asyncio.QueueFull):
                    await ws.close(code=1008, message=b'Invalid explicit request')
                    break
                continue
            try:
                value = json.loads(message.data)
                if value.get('type') == 'publish':
                    changes=value.get('changes')
                    if not isinstance(changes,dict) or (not scope.get('metadata') and not set(changes)<={'agents'}):raise ValueError('Publisher scope')
                    if 'agents' in changes and (not isinstance(changes['agents'],dict) or not set(changes['agents'])<=set(scope['agents'])):raise ValueError('Agent scope')
                    delta = state.publish(changes)
                    if delta:
                        wire=dict(delta)
                        if 'work' in wire:wire['work']=changes['work']
                        if 'agents' in wire:wire['agents']=state.agents()
                        elif 'maestroHistory' in wire:wire['agents']={'maestro':{'relayOnline':True}}
                        state.broadcast({'type':'update','revision':state.revision,'changes':wire})
                elif value.get('type') == 'rpcResult':
                    identity=value.get('id');waiting=state.requests.get(identity)
                    if waiting and waiting[1] is ws:
                        state.requests.pop(identity,None)
                        waiting[0].put_nowait(json.dumps(value))
                elif value.get('type') in ('maestroDelta','agentDelta'):
                    identity, text = value.get('id'), value.get('delta')
                    if not isinstance(identity, str) or len(identity) > 128 or not isinstance(text, str) or len(text) > 32768:
                        raise ValueError('Invalid visible message delta')
                    agent=value.get('agentId','maestro')
                    if agent not in scope['agents']:raise ValueError('Agent scope')
                    state.append_delta(identity,text,agent)
                    state.broadcast({'type':'maestroDelta' if agent=='maestro' else 'agentDelta','agentId':agent,'id':identity,'delta':text})
                else:
                    raise ValueError('Unknown publisher operation')
                queue.put_nowait(json.dumps({'type': 'accepted', 'revision': state.revision}))
            except (ValueError, TypeError, KeyError):
                await ws.close(code=1008, message=b'Invalid publication')
                break
    finally:
        authorization.cancel()
        await asyncio.gather(authorization, return_exceptions=True)
        if publishing:
            state.publishers -= 1
            state.notifications.reset(scope["agents"])
            state.publisher_channels.pop(ws,None)
            state.publisher_scopes.pop(ws,None)
            state.broadcast({'type':'update','revision':state.revision,'changes':{'agents':{identity:{'relayOnline':any(identity in s['agents'] for s in state.publisher_scopes.values())} for identity in scope['agents']}}})
        for identity,(owner,publisher) in list(state.requests.items()):
            if owner is queue or publisher is ws:
                state.requests.pop(identity,None)
                if owner is not queue:
                    try: owner.put_nowait(json.dumps({'type':'rpcResult','id':identity,'status':502,'body':{'error':'The Mac connection ended. Delivery is unconfirmed; no automatic retry was made.'}}))
                    except asyncio.QueueFull: pass
        state.clients.discard(queue)
        state.client_access.pop(queue, None)
        if writer:
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
    return ws


async def lifecycle(app):
    app['http'] = ClientSession(timeout=ClientTimeout(total=5))
    push=asyncio.create_task(app['state'].notifications.run())
    yield
    push.cancel()
    await asyncio.gather(push,return_exceptions=True)
    await app['http'].close()
    app['state'].close()


def application(path=DATA):
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app['state'] = State(path)
    app['assets'] = AssetStore(Path(path).parent/'vmfactory-assets')
    app.cleanup_ctx.append(lifecycle)
    app.router.add_post('/v1/vmfactory/notifications/device',register_notifications)
    app.router.add_get('/v1/vmfactory/assets/{digest}',asset)
    app.router.add_put('/v1/vmfactory/assets/{digest}',asset)
    app.router.add_get('/v1/vmfactory/snapshot', snapshot)
    app.router.add_get('/v1/vmfactory/maestro', history)
    app.router.add_get('/v1/vmfactory/agents/{agent}/history',history)
    app.router.add_get('/v1/vmfactory/connect', connect)
    return app


if __name__ == '__main__':
    web.run_app(application(), host='127.0.0.1', port=18771, access_log=None, print=None, shutdown_timeout=2)
