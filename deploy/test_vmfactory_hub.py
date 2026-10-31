import asyncio
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch, AsyncMock
from aiohttp import WSMsgType
from aiohttp.test_utils import TestServer, TestClient
import vmfactory_hub as hub


class StateTests(unittest.TestCase):
    def test_private_wal_state_recovers_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.sqlite'
            state = hub.State(path)
            delta = {'discoveries': {'revision': 'one'}}
            self.assertEqual(state.publish(delta), delta)
            revision = state.revision
            self.assertEqual(state.publish(delta), {})
            self.assertEqual(state.sequence, 1)
            self.assertEqual(state.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            state.close()
            state = hub.State(path)
            self.assertEqual(state.revision, revision)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            for invalid in ({'command': {}}, {'tasks': []}, None):
                with self.assertRaises(ValueError): state.publish(invalid)
            state.close()


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.client = TestClient(TestServer(hub.application(Path(self.directory.name) / 'state.sqlite')))
        self.auth = patch('vmfactory_hub.viewer_authorized', new=AsyncMock(side_effect=lambda request: request.headers.get('Authorization') == 'Bearer viewer'))
        self.publisher = patch('vmfactory_hub.publisher_authorized', side_effect=lambda token: token == 'publisher')
        self.auth.start(); self.publisher.start()
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.auth.stop(); self.publisher.stop(); self.directory.cleanup()

    async def test_persistent_push_recovery_and_compression(self):
        viewer = await self.client.ws_connect('/v1/vmfactory/connect', headers={'Authorization': 'Bearer viewer'})
        self.assertEqual((await viewer.receive_json())['type'], 'ready')
        publisher = await self.client.ws_connect('/v1/vmfactory/connect?role=publisher', headers={'Authorization': 'Bearer publisher'})
        await publisher.receive_json()
        for number in range(3):
            await publisher.send_json({'type': 'publish', 'changes': {'worker': {'sequence': number}}})
            event = await asyncio.wait_for(viewer.receive_json(), 2)
            self.assertEqual(event['changes']['worker']['sequence'], number)
            await publisher.receive_json()
        await publisher.send_json({'type': 'maestroDelta', 'id': 'message', 'delta': 'Visible text'})
        self.assertEqual((await viewer.receive_json())['delta'], 'Visible text')
        await publisher.receive_json()
        response = await self.client.get('/v1/vmfactory/snapshot', headers={'Authorization': 'Bearer viewer', 'Accept-Encoding': 'gzip'})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers['Content-Encoding'], 'gzip')
        etag = response.headers['ETag']
        self.assertEqual((await response.json())['worker']['sequence'], 2)
        response = await self.client.get('/v1/vmfactory/snapshot', headers={'Authorization': 'Bearer viewer', 'If-None-Match': etag})
        self.assertEqual(response.status, 304)
        await publisher.close(); await viewer.close()

    async def test_unauthenticated_reads_and_phone_publications_fail(self):
        response = await self.client.get('/v1/vmfactory/snapshot')
        self.assertEqual(response.status, 401)
        viewer = await self.client.ws_connect('/v1/vmfactory/connect', headers={'Authorization': 'Bearer viewer'})
        await viewer.receive_json()
        await viewer.send_json({'type': 'publish', 'changes': {'worker': {'bad': True}}})
        result = await viewer.receive()
        self.assertEqual(result.type, WSMsgType.CLOSE)
        self.assertEqual(result.data, 1008)
        self.assertNotIn('worker', self.client.server.app['state'].data)

    async def test_explicit_requests_cross_existing_socket_without_offline_queue(self):
        viewer = await self.client.ws_connect('/v1/vmfactory/connect', headers={'Authorization': 'Bearer viewer'})
        await viewer.receive_json()
        identity = str(uuid.uuid4())
        message = {'type': 'request', 'id': identity, 'operation': 'stop', 'body': {}}
        await viewer.send_json(message)
        response = await viewer.receive_json()
        self.assertEqual(response['status'], 503)
        self.assertEqual(self.client.server.app['state'].requests, {})
        publisher = await self.client.ws_connect('/v1/vmfactory/connect?role=publisher', headers={'Authorization': 'Bearer publisher'})
        await publisher.receive_json()
        await viewer.send_json(message)
        forwarded = await publisher.receive_json()
        self.assertEqual(forwarded, dict(message,agentId="maestro"))
        await publisher.send_json({'type': 'rpcResult', 'id': identity, 'status': 200, 'body': {'ok': True}})
        self.assertEqual((await viewer.receive_json())['body'], {'ok': True})
        self.assertEqual(self.client.server.app['state'].requests, {})
        await publisher.receive_json()
        await publisher.close(); await viewer.close()

    async def test_two_servers_route_and_isolate_agents(self):
        def scope(token):
            return {'agents':['maestro' if token=='publisher' else 'remote-worker'],'metadata':token=='publisher'} if token in ('publisher','remote') else None
        with patch('vmfactory_hub.publisher_scope',side_effect=scope):
            viewer=await self.client.ws_connect('/v1/vmfactory/connect',headers={'Authorization':'Bearer viewer'});await viewer.receive_json()
            mac=await self.client.ws_connect('/v1/vmfactory/connect?role=publisher',headers={'Authorization':'Bearer publisher'});await mac.receive_json()
            remote=await self.client.ws_connect('/v1/vmfactory/connect?role=publisher',headers={'Authorization':'Bearer remote'});await remote.receive_json()
            await remote.send_json({'type':'publish','changes':{'agents':{'remote-worker':{'name':'Worker','server':'Other server','history':{'items':[]}}}}})
            self.assertIn('remote-worker',(await viewer.receive_json())['changes']['agents']);await remote.receive_json()
            request={'type':'request','id':str(uuid.uuid4()),'agentId':'remote-worker','operation':'stop','body':{}}
            await viewer.send_json(request)
            self.assertEqual(await remote.receive_json(),request)
            await remote.send_json({'type':'rpcResult','id':request['id'],'status':200,'body':{'ok':True}})
            self.assertTrue((await viewer.receive_json())['body']['ok']);await remote.receive_json()
            await remote.send_json({'type':'agentDelta','agentId':'remote-worker','id':'text','delta':'Hello'})
            self.assertEqual((await viewer.receive_json())['agentId'],'remote-worker');await remote.receive_json()
            response=await self.client.get('/v1/vmfactory/agents/remote-worker/history',headers={'Authorization':'Bearer viewer'})
            self.assertEqual((await response.json())['items'][0]['content']['text'],'Hello')
            await remote.send_json({'type':'publish','changes':{'agents':{'maestro':{'name':'Imposter'}}}})
            self.assertEqual((await remote.receive()).data,1008)
            self.assertNotIn('maestro',self.client.server.app['state'].data['agents'])
            await mac.close();await viewer.close()
