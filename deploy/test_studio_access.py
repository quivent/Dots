import asyncio
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import vmfactory_hub as hub
from chat_router import Hub
from studio_access import StudioAccess, migrate_grants, normalize_grant, view_digest

GRANT = {'project': 'fmvisual', 'capabilities': ['crew.read', 'tasks.read']}


def source():
    return {'schema': 'vmfactory.mobile-snapshot/1',
        'work': {'schema': 'vmfactory.shared-work/1', 'snapshot': True, 'revision': 1,
            'tables': {'tasks': {
                'FMV-748': {'text': 'Partner access', 'owner': 'tamsin',
                    'depends_on': ['secret'], 'delivery_evidence': 'PRIVATE'},
                'secret': {'text': 'PRIVATE', 'ownerOnly': True}},
                'runs': {}, 'lanes': {}, 'workers': {'private-host': {'token': 'PRIVATE'}}}},
        'roster': {'crew': [{'id': 'tamsin', 'name': 'Tamsin', 'role': 'Task Manager'}]},
        'agents': {'tamsin': {'history': {'items': [{'id': 'private', 'content': {'text': 'PRIVATE'}}]}, 'capabilities': {'inspect': True}}},
        'feedback': {'text': 'PRIVATE'}}


class GrantTests(unittest.TestCase):
    def test_legacy_migration_preserves_rows_without_grant(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('CREATE TABLE invitations(id TEXT); CREATE TABLE devices(id TEXT);'
                         "INSERT INTO devices VALUES('old');")
        migrate_grants(db); migrate_grants(db)
        self.assertEqual(db.execute('SELECT * FROM devices').fetchall(), [('old', None)])

    def test_grants_fail_closed(self):
        for value in ({}, {'project': 'other', 'capabilities': ['tasks.read']},
                      {'project': 'fmvisual', 'capabilities': ['owner']},
                      dict(GRANT, owner=True), {'project': 'fmvisual', 'capabilities': ['tasks.read'] * 2}):
            with self.subTest(value=value), self.assertRaises(ValueError): normalize_grant(value)
        self.assertIsNone(StudioAccess.from_health({'scope': 'hosted'}))
        self.assertIsNone(StudioAccess.from_health({'scope': 'owner', 'studio_access': GRANT}))

    def test_existing_invite_single_use_grant_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = Hub(Path(directory), registry={})
            self.addCleanup(auth.conn.close)
            old = auth.redeem_invitation(auth.invitation('owner')['code'], 'Old')
            self.assertIsNone(auth.studio_access(old['token']))
            invite = auth.invitation('owner', GRANT)
            device = auth.redeem_invitation(invite['code'], 'Partner')
            self.assertEqual(device['scope'], 'hosted')
            self.assertEqual(auth.studio_access(device['token']), GRANT)
            self.assertIsNone(auth.redeem_invitation(invite['code'], 'Replay'))
            auth.set_studio_access(device['device_id'], None)
            self.assertIsNone(auth.studio_access(device['token']))
            auth.set_studio_access(device['device_id'], GRANT)
            auth.db('UPDATE devices SET revoked=1 WHERE id=?', (device['device_id'],))
            self.assertIsNone(auth.studio_access(device['token']))

    def test_projection_excludes_private_content_and_references(self):
        access = StudioAccess.from_health({'scope': 'hosted', 'studio_access': GRANT})
        projected = access.snapshot(source())
        self.assertNotIn('PRIVATE', json.dumps(projected))
        self.assertEqual(projected['work']['tables']['workers'], {})
        self.assertEqual(projected['work']['tables']['tasks']['FMV-748']['depends_on'], [])
        self.assertFalse(projected['agents']['tamsin']['capabilities']['inspect'])
        changed = source(); changed['feedback']['text'] = 'NEW PRIVATE'
        changed['work']['revision'] = 2
        self.assertEqual(view_digest(projected), view_digest(access.snapshot(changed)))


class ReaderStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.health = {'reader': {'scope': 'hosted', 'studio_access': GRANT},
                       'owner': {'scope': 'owner'}, 'ungranted': {'scope': 'hosted'}}
        async def health(request):
            return copy.deepcopy(self.health.get(hub.bearer(request)))
        self.auth = patch.object(hub, 'identity_health', new=health)
        self.auth.start()
        self.client = TestClient(TestServer(hub.application(Path(self.directory.name) / 'state.sqlite')))
        await self.client.start_server()
        self.state = self.client.server.app['state']
        self.state.notifications.config = Path(self.directory.name) / 'no-push-config'
        self.state.publish({k: v for k, v in source().items() if k in hub.KEYS})
        self.headers = {'Authorization': 'Bearer reader'}

    async def asyncTearDown(self):
        await self.client.close(); self.auth.stop(); self.directory.cleanup()

    async def test_statuses_and_owner_snapshot_unchanged(self):
        self.assertEqual((await self.client.get('/v1/vmfactory/snapshot')).status, 401)
        self.assertEqual((await self.client.get('/v1/vmfactory/snapshot', headers={'Authorization': 'Bearer ungranted'})).status, 403)
        owner = await self.client.get('/v1/vmfactory/snapshot', headers={'Authorization': 'Bearer owner'})
        self.assertIn('PRIVATE', json.dumps(await owner.json()))
        history = await self.client.get('/v1/vmfactory/agents/tamsin/history', headers=self.headers)
        self.assertEqual(history.status, 403)

    async def test_live_filtered_updates_contiguous_cursor_and_reconnect(self):
        ws = await self.client.ws_connect('/v1/vmfactory/connect', headers=self.headers)
        ready = await ws.receive_json()
        snap = await self.client.get('/v1/vmfactory/snapshot', headers=self.headers)
        etag = snap.headers['ETag']; initial = await snap.json()
        self.assertEqual(ready['epoch'], initial['epoch'])
        self.state.publish({'worker': {'text': 'NEW PRIVATE'}})
        self.state.broadcast({'type': 'update', 'changes': {'worker': {'text': 'NEW PRIVATE'}}})
        unchanged = await self.client.get('/v1/vmfactory/snapshot', headers=dict(self.headers, **{'If-None-Match': etag}))
        self.assertEqual(unchanged.status, 304)
        work = source()['work']; work['revision'] = 2
        work['tables']['tasks']['FMV-748']['text'] = 'Public progress'
        self.state.publish({'work': work})
        self.state.broadcast({'type': 'update', 'changes': {'work': work}})
        event = await asyncio.wait_for(ws.receive_json(), 2)
        self.assertEqual(event['eventSequence'], ready['eventSequence'] + 1)
        self.assertNotIn('PRIVATE', json.dumps(event))
        self.assertEqual(event['changes']['work']['tables']['tasks']['FMV-748']['text'], 'Public progress')
        latest = await (await self.client.get('/v1/vmfactory/snapshot', headers=self.headers)).json()
        self.assertEqual(latest['wireSequence'], event['eventSequence'])
        self.assertEqual(latest['revision'], event['revision'])
        await ws.close()

    async def test_capability_subsets_and_denied_rpc(self):
        self.health['reader']['studio_access'] = {'project': 'fmvisual', 'capabilities': ['tasks.read']}
        value = await (await self.client.get('/v1/vmfactory/snapshot', headers=self.headers)).json()
        self.assertNotIn('roster', value); self.assertIn('work', value)
        ws = await self.client.ws_connect('/v1/vmfactory/connect', headers=self.headers)
        await ws.receive_json()
        for operation in ('send', 'stop', 'inspect'):
            await ws.send_json({'type': 'request', 'id': str(uuid.uuid4()), 'operation': operation, 'body': {}})
            self.assertEqual((await ws.receive_json())['status'], 403)
        self.assertEqual(self.state.requests, {})
        await ws.close()
        self.health['reader']['studio_access']['capabilities'] = ['crew.read']
        value = await (await self.client.get('/v1/vmfactory/snapshot', headers=self.headers)).json()
        self.assertNotIn('work', value); self.assertIn('roster', value)

    async def test_revoke_before_next_public_frame(self):
        ws = await self.client.ws_connect('/v1/vmfactory/connect', headers=self.headers)
        await ws.receive_json()
        self.health.pop('reader')
        work = source()['work']; work['revision'] = 2
        work['tables']['tasks']['FMV-748']['text'] = 'Must not leak'
        self.state.publish({'work': work})
        self.state.broadcast({'type': 'update', 'changes': {'work': work}})
        frame = await asyncio.wait_for(ws.receive(), 2)
        self.assertEqual(frame.type, WSMsgType.CLOSE)
        self.assertEqual(frame.data, 1008)

    async def test_owner_wrong_original_session_is_rejected_before_dispatch(self):
        ws = await self.client.ws_connect('/v1/vmfactory/connect', headers={'Authorization': 'Bearer owner'})
        await ws.receive_json()
        await ws.send_json({'type': 'request', 'id': str(uuid.uuid4()), 'operation': 'stop',
                           'agentId': 'tamsin', 'expectedNativeSessionId': 'different-thread', 'body': {}})
        result = await ws.receive_json()
        self.assertEqual(result['status'], 409)
        self.assertEqual(self.state.requests, {})
        await ws.close()
