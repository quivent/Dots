import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid
from aiohttp.test_utils import TestClient, TestServer
import vmfactory_hub as hub
from feedback_inbox import FeedbackInbox, FeedbackNotifications, FeedbackConflict

SESSION='00000000-0000-4000-8000-000000000001'
SCOPE={'agents':['alder'],'source':'test-host'}
def request(key='same-request',**changes):
    value=dict(clientRequestId=key,agentId='alder',nativeSessionId=SESSION,question='  What feels alive? 🌿\nWhat needs the next push?  ',subject='Art direction')
    value.update(changes);return value

class FeedbackStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'hub.sqlite';self.db=sqlite3.connect(self.path);self.store=FeedbackInbox(self.db)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def test_exact_question_survives_restart_and_retry_never_reopens_handled_work(self):
        row,created=self.store.submit(request(),SCOPE,now=1000);self.assertTrue(created);self.assertEqual(row['question'],request()['question'])
        self.store.change(row['id'],dict(actionId='resolve-1',operation='handle',expectedStatusVersion=0),now=1100)
        self.db.close();self.db=sqlite3.connect(self.path);self.store=FeedbackInbox(self.db)
        restored,created=self.store.submit(request(),SCOPE,now=1200);self.assertFalse(created);self.assertEqual(restored['state'],'handled');self.assertEqual(restored['receivedAt'],1000)
        with self.assertRaises(FeedbackConflict):self.store.submit(request(question='Changed content'),SCOPE)
    def test_seen_is_separate_from_handled_and_old_status_cannot_overwrite_reopening(self):
        row,_=self.store.submit(request(),SCOPE)
        seen=self.store.change(row['id'],dict(actionId='seen-1',operation='seen'));self.assertEqual(seen['state'],'open');self.assertIsNotNone(seen['seenAt'])
        handled=self.store.change(row['id'],dict(actionId='handle-1',operation='handle',expectedStatusVersion=0))
        reopened=self.store.change(row['id'],dict(actionId='reopen-1',operation='reopen',expectedStatusVersion=handled['statusVersion']))
        self.assertEqual(reopened['state'],'open')
        with self.assertRaises(FeedbackConflict):self.store.change(row['id'],dict(actionId='late-offline',operation='handle',expectedStatusVersion=0))
        replay=self.store.change(row['id'],dict(actionId='handle-1',operation='handle',expectedStatusVersion=0));self.assertEqual(replay['state'],'open')
    def test_source_resolution_is_scoped_idempotent_and_never_reverses_operator_reopening(self):
        row,_=self.store.submit(request(),SCOPE)
        with self.assertRaises(PermissionError):self.store.source_resolved(row['id'],{'agents':['other']},SESSION)
        done=self.store.source_resolved(row['id'],SCOPE,SESSION);self.assertEqual(done['resolutionSource'],'source')
        self.store.change(row['id'],dict(actionId='reopen',operation='reopen',expectedStatusVersion=done['statusVersion']))
        self.assertEqual(self.store.source_resolved(row['id'],SCOPE,SESSION)['state'],'open')
    def test_paged_change_feed_can_resume_without_losing_seen_or_status_changes(self):
        first,_=self.store.submit(request('one'),SCOPE);second,_=self.store.submit(request('two'),SCOPE)
        self.store.change(first['id'],dict(actionId='seen',operation='seen'))
        page=self.store.sync(limit=1);through=page['throughRevision'];records={};cursor=0
        while True:
            page=self.store.sync(after=cursor,through=through,limit=1)
            for record in page['changes']:records[record['id']]=record
            cursor=page['nextAfter']
            if not page['hasMore']:break
        self.assertEqual(set(records),{first['id'],second['id']});self.assertIsNotNone(records[first['id']]['seenAt'])
        self.assertEqual(cursor,through);self.assertEqual(page['summary']['openCount'],2);self.assertEqual(page['summary']['unseenCount'],1)
    def test_auth_and_private_or_malformed_fields_do_not_create_requests(self):
        for body in [request(agentId='other'),request(nativeSessionId='bad'),request(question='x'*32001),request(isSecret=True),request(toolArguments='private'),request(sourceCreatedAt=True),request(options=[{'label':'x','description':1}])]:
            with self.assertRaises((ValueError,PermissionError)):self.store.submit(body,SCOPE)
        self.assertEqual(self.store.summary()['revision'],0)
    def test_atomic_failure_keeps_inbox_and_notification_queue_consistent(self):
        def broken(record):raise OSError('fixture queue failure')
        with self.assertRaises(OSError):self.store.submit(request(),SCOPE,on_create=broken)
        self.assertEqual(self.store.summary()['openCount'],0);self.assertEqual(self.store.summary()['revision'],0)
    def test_existing_push_queue_gets_exact_semantic_payload_and_cancels_handled_requests(self):
        service=FeedbackNotifications(self.db)
        owner='fixture-owner';service.register(owner,dict(id=str(uuid.uuid4()),token='ab'*32,environment='sandbox',enabled=True))
        row,_=service.submit_feedback(request(),SCOPE,{'alder':'Alder'})
        event=self.db.execute('SELECT * FROM agent_stops').fetchone();payload=service.payload(event)
        self.assertEqual(payload['kind'],'feedback');self.assertEqual(payload['eventId'],row['id']);self.assertEqual(payload['nativeSessionId'],SESSION)
        self.assertEqual(payload['aps']['alert']['title'],'Alder asks for feedback');self.assertNotIn('stopped',payload['aps']['alert']['title'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM push_deliveries').fetchone()[0],1)
        service.submit_feedback(request(),SCOPE);self.assertEqual(self.db.execute('SELECT count(*) FROM push_deliveries').fetchone()[0],1)
        handled=service.inbox.change(row['id'],dict(actionId='handle',operation='handle',expectedStatusVersion=0));service.changed_feedback(handled)
        self.assertEqual(self.db.execute('SELECT state FROM push_deliveries').fetchone()[0],'handled')
        self.assertEqual(service.send({},(),event),'handled')
    def test_recovered_questions_enter_inbox_without_a_burst_of_historical_pushes(self):
        service=FeedbackNotifications(self.db);row,_=service.submit_feedback(request(source='recovered'),SCOPE)
        self.assertEqual(row['state'],'open');self.assertEqual(self.db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],0)

class FeedbackHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        async def owner(request):return request.headers.get('Authorization')=='Bearer owner'
        self.auth=patch.object(hub,'viewer_authorized',owner);self.auth.start()
        self.scope=patch.object(hub,'publisher_scope',lambda token:SCOPE if token=='publisher' else {'agents':['maestro'],'metadata':True,'source':'mac'} if token=='metadata' else {'agents':['other']} if token=='other' else None);self.scope.start()
        self.client=TestClient(TestServer(hub.application(Path(self.temp.name)/'hub.sqlite')));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.scope.stop();self.auth.stop();self.temp.cleanup()
    async def test_submission_auth_scope_and_snapshot_revision(self):
        owner={'Authorization':'Bearer owner'};pub={'Authorization':'Bearer publisher'}
        first=await self.client.get('/v1/vmfactory/snapshot',headers=owner);etag=first.headers['ETag'];await first.read()
        denied=await self.client.post('/v1/vmfactory/feedback/requests',json=request(),headers=owner);self.assertEqual(denied.status,401)
        created=await self.client.post('/v1/vmfactory/feedback/requests',json=request(),headers=pub);self.assertEqual(created.status,201);record=(await created.json())['record']
        updated=await self.client.get('/v1/vmfactory/snapshot',headers=dict(owner,**{'If-None-Match':etag}));self.assertEqual(updated.status,200);self.assertNotEqual(updated.headers['ETag'],etag)
        summary=(await updated.json())['feedbackInbox'];self.assertEqual(summary['openCount'],1)
        blocked=await self.client.get('/v1/vmfactory/feedback/requests/'+record['id'],headers={'Authorization':'Bearer other'});self.assertEqual(blocked.status,403)
        feed=await self.client.get('/v1/vmfactory/feedback/requests?after=0',headers=owner);self.assertEqual(len((await feed.json())['changes']),1)
        seen=await self.client.post('/v1/vmfactory/feedback/requests/'+record['id']+'/actions',json=dict(actionId='seen',operation='seen'),headers=owner)
        self.assertEqual((await seen.json())['record']['state'],'open')
    async def test_recovery_requires_primary_scope_and_exact_canonical_roster_binding(self):
        self.client.server.app['state'].publish({'roster':{'crew':[{'id':'alder','name':'Alder','sessionId':SESSION}]}})
        body=request(source='recovered')
        denied=await self.client.post('/v1/vmfactory/feedback/recover',json=body,headers={'Authorization':'Bearer publisher'});self.assertEqual(denied.status,403)
        accepted=await self.client.post('/v1/vmfactory/feedback/recover',json=body,headers={'Authorization':'Bearer metadata'});self.assertEqual(accepted.status,201)
        self.assertEqual((await accepted.json())['record']['agentName'],'Alder')
        wrong=await self.client.post('/v1/vmfactory/feedback/recover',json=request('wrong',source='recovered',nativeSessionId='00000000-0000-4000-8000-000000000002'),headers={'Authorization':'Bearer metadata'});self.assertEqual(wrong.status,403)

    async def test_origins_and_invalid_cursors_fail_closed(self):
        denied=await self.client.post('/v1/vmfactory/feedback/requests',json=request(),headers={'Authorization':'Bearer publisher','Origin':'https://untrusted.example'});self.assertEqual(denied.status,401)
        invalid=await self.client.get('/v1/vmfactory/feedback/requests?after=-1',headers={'Authorization':'Bearer owner'});self.assertEqual(invalid.status,400)

if __name__=='__main__':unittest.main()
