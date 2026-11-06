"""Human invitations and exact-session developer controls, isolated from production."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import WSMsgType
import vmfactory_hub as hub
from chat_router import Hub
from studio_access import StudioAccess, normalize_grant

MEMBER='apple-00000000-0000-4000-8000-000000000001'
GRANT={'project':'fmvisual','capabilities':['crew.chat','crew.control','crew.read','tasks.read'],'crew_member_id':MEMBER}
SESSION='00000000-0000-4000-8000-000000000002'

class HumanTests(unittest.TestCase):
    def test_named_invitation_single_use_revoke_and_no_agent_session(self):
        with tempfile.TemporaryDirectory() as directory:
            auth=Hub(Path(directory),registry={})
            try:
                invite=auth.invitation('owner-fixture',GRANT)
                joined=auth.redeem_invitation(invite['code'],'Luke phone')
                self.assertIsNone(auth.redeem_invitation(invite['code'],'Replay'))
                person=auth.person(joined['token'])
                people=auth.people('owner')
                self.assertEqual(next(p for p in people if p['id']==person)['crew_member_id'],MEMBER)
                body={'name':'Crew conversation','members':[],'people':[person],'request_id':str(uuid.uuid4())}
                room=auth.create_room(body,'owner')
                self.assertTrue(room['human_only'])
                self.assertEqual(auth.create_room(body,'owner'),room)
                self.assertEqual(auth.db('SELECT * FROM jobs'),[])
                auth.set_studio_access(joined['device_id'],None)
                self.assertIsNone(next(p for p in auth.people('owner') if p['id']==person)['crew_member_id'])
                auth.db('UPDATE devices SET revoked=1 WHERE id=?',(person,))
                self.assertNotIn(person,[p['id'] for p in auth.people('owner')])
            finally:auth.conn.close()

    def test_grants_and_projection_do_not_elevate_or_leak_private_members(self):
        for caps in (['crew.control'],['crew.chat'],['crew.read','crew.control'],['owner']):
            with self.assertRaises(ValueError):normalize_grant({'project':'fmvisual','capabilities':caps})
        developer=StudioAccess.from_health({'scope':'hosted','studio_access':GRANT})
        self.assertFalse(developer.owner)
        for op in ['send','stop','inspect','resume']:self.assertTrue(developer.allows(op))
        self.assertFalse(developer.allows('retire'))
        source={'roster':{'crew':[{'id':'agent'},{'id':'private','ownerOnly':True},{'id':MEMBER,'kind':'human','role':'Foreign Advisor'}]},'agents':{'agent':{'capabilities':{'boundInput':True},'history':{'items':[{'id':'m'}]}},'private':{'history':{'items':[{'id':'secret'}]}}},'privateAssets':'secret'}
        view=developer.snapshot(source)
        self.assertNotIn('privateAssets',view);self.assertNotIn('private',view['agents'])
        self.assertEqual(view['agents'][MEMBER]['kind'],'human')
        self.assertEqual(view['agents']['agent']['history']['items'][0]['id'],'m')
        reader=StudioAccess(frozenset({'crew.read'})).snapshot(source)
        self.assertNotIn('history',reader['agents']['agent']);self.assertFalse(reader['agents']['agent']['capabilities']['boundInput'])

class DeveloperStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.health={'scope':'hosted','studio_access':copy.deepcopy(GRANT)}
        async def health(request):return copy.deepcopy(self.health)
        self.auth=patch.object(hub,'identity_health',new=health);self.auth.start()
        self.client=TestClient(TestServer(hub.application(Path(self.directory.name)/'state.sqlite')))
        await self.client.start_server();self.state=self.client.server.app['state']
        self.state.notifications.config=Path(self.directory.name)/'no-push'
        self.state.publish({'roster':{'crew':[{'id':'agent','sessionId':SESSION,'lifecycle':'active'},{'id':'private','ownerOnly':True}]},'agents':{'agent':{'nativeSessionId':SESSION,'capabilities':{'boundInput':True,'inspect':True,'resume':True},'history':{'items':[{'id':'m'}]}},'private':{'nativeSessionId':SESSION,'history':{'items':[]}}}})
        self.headers={'Authorization':'Bearer isolated-developer'}
    async def asyncTearDown(self):
        await self.client.close();self.auth.stop();self.directory.cleanup()
    async def test_chat_history_scope_and_owner_endpoints(self):
        self.assertEqual((await self.client.get('/v1/vmfactory/agents/agent/history?nativeSessionId='+SESSION,headers=self.headers)).status,200)
        self.assertEqual((await self.client.get('/v1/vmfactory/agents/private/history',headers=self.headers)).status,404)
        self.assertEqual((await self.client.get('/v1/vmfactory/agents/agent/history?nativeSessionId=wrong',headers=self.headers)).status,409)
        self.health['studio_access']={'project':'fmvisual','capabilities':['crew.read']}
        self.assertEqual((await self.client.get('/v1/vmfactory/agents/agent/history',headers=self.headers)).status,403)
    async def test_control_exact_session_dispatch_and_immediate_revocation(self):
        ws=await self.client.ws_connect('/v1/vmfactory/connect',headers=self.headers);await ws.receive_json()
        class Publisher:closed=False
        publisher=Publisher();queue=asyncio.Queue()
        self.state.publisher_channels[publisher]=queue;self.state.publisher_scopes[publisher]={'agents':['agent']}
        async def request(op,session):
            identity=str(uuid.uuid4());body={}
            if op=='send':body={'request_id':identity,'idempotency_token':identity,'work_approved':True,'content':{'text':'isolated fixture','attachments':[]}}
            await ws.send_json({'type':'request','id':identity,'operation':op,'agentId':'agent','expectedNativeSessionId':session,'body':body})
            return identity
        for op in ('send','stop','inspect','resume'):
            identity=await request(op,SESSION)
            sent=json.loads(await asyncio.wait_for(queue.get(),2));self.assertEqual(sent['id'],identity);self.assertEqual(sent['expectedNativeSessionId'],SESSION)
            self.state.requests.pop(identity)
        await request('send','wrong');self.assertEqual((await ws.receive_json())['status'],409);self.assertTrue(queue.empty())
        self.health['studio_access']=None
        await request('stop',SESSION)
        rejected=await ws.receive()
        self.assertTrue((rejected.type==WSMsgType.CLOSE and rejected.data==1008) or (rejected.type==WSMsgType.TEXT and json.loads(rejected.data)['status']==403));self.assertTrue(queue.empty())
        await ws.close();self.state.publisher_channels.pop(publisher);self.state.publisher_scopes.pop(publisher)
