import json
import secrets
import uuid
import unittest
from test_team_studio_access import TeamStudioAccessTests, MEMBER
import install_enrollment as enrollment

class InstallationEnrollmentTests(TeamStudioAccessTests):
    def setUp(self):
        super().setUp()
        self.token=secrets.token_urlsafe(32)
        self.body=dict(id=str(uuid.uuid4()),name='iPhone',platform='iOS',build='2026.11.8')
    def test_pending_has_no_auth_or_grant_and_no_secret_in_owner_listing(self):
        result=enrollment.register(self.hub,self.token,self.body)
        self.assertEqual(result['state'],'pending')
        self.assertFalse(self.hub.authorized(self.token))
        self.assertIsNone(self.hub.studio_access(self.token))
        self.assertNotIn(self.token,json.dumps(enrollment.listing(self.hub)))
        self.assertNotIn('token_hash',json.dumps(enrollment.listing(self.hub)))
        self.assertEqual(enrollment.register(self.hub,self.token,self.body),result)
    def test_only_owner_bound_team_attachment_enables_same_token(self):
        enrollment.register(self.hub,self.token,self.body)
        bound=enrollment.attach(self.hub,self.body['id'],MEMBER)
        self.assertTrue(self.hub.authorized(self.token))
        result=enrollment.status(self.hub,self.token)
        self.assertEqual(result['state'],'approved')
        self.assertEqual(set(result['studio_access']['capabilities']),{'tasks.read','crew.read','crew.chat'})
        self.assertNotIn('crew.control',result['studio_access']['capabilities'])
        self.assertEqual(enrollment.attach(self.hub,self.body['id'],MEMBER),bound)
        self.hub.db('UPDATE devices SET revoked=1 WHERE id=?',(bound['device_id'],))
        self.assertEqual(enrollment.status(self.hub,self.token)['state'],'denied')
        with self.assertRaises(PermissionError):enrollment.attach(self.hub,self.body['id'],MEMBER)
    def test_team_retirement_and_explicit_deny_remain_effective(self):
        enrollment.register(self.hub,self.token,self.body)
        bound=enrollment.attach(self.hub,self.body['id'],MEMBER)
        self.hub.set_studio_access(bound['device_id'],None)
        self.assertEqual(enrollment.status(self.hub,self.token)['state'],'denied')
        with self.assertRaises(PermissionError):enrollment.attach(self.hub,self.body['id'],MEMBER)
        self.member['lifecycle']='retired';self.save_member()
        with self.assertRaises(ValueError):enrollment.attach(self.hub,self.body['id'],MEMBER)
    def test_spoofed_name_and_stolen_installation_id_grant_nothing(self):
        self.body['name']='Luke Ramsay'
        enrollment.register(self.hub,self.token,self.body)
        self.assertFalse(self.hub.authorized(self.token))
        with self.assertRaises(PermissionError):enrollment.register(self.hub,secrets.token_urlsafe(32),self.body)
        with self.assertRaises(PermissionError):enrollment.status(self.hub,secrets.token_urlsafe(32))
        with self.assertRaises(ValueError):enrollment.attach(self.hub,self.body['id'],'Luke Ramsay')
    def test_existing_revoked_token_cannot_register_again(self):
        enrollment.register(self.hub,self.token,self.body)
        bound=enrollment.attach(self.hub,self.body['id'],MEMBER)
        self.hub.db('UPDATE devices SET revoked=1 WHERE id=?',(bound['device_id'],))
        with self.assertRaises(PermissionError):enrollment.register(self.hub,self.token,dict(self.body,id=str(uuid.uuid4())))


class InstallationHTTPTests(InstallationEnrollmentTests):
    def test_http_pending_cannot_read_or_self_attach(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from chat_router import Handler
        original=self.hub.authorized
        self.hub.authorized=lambda token:token=='test-owner' or original(token)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.hub=self.hub
        threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(method,path,token,body=None):
            req=Request('http://127.0.0.1:'+str(server.server_port)+'/v1'+path,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
            try:
                with urlopen(req,timeout=5) as r:return r.status,json.load(r)
            except HTTPError as e:return e.code,json.load(e)
        try:
            self.assertEqual(request('POST','/installations',self.token,self.body)[0],200)
            self.assertEqual(request('GET','/health',self.token)[0],401)
            self.assertEqual(request('GET','/hosted/installations',self.token)[0],401)
            path='/hosted/installations/'+self.body['id']+'/attach'
            self.assertEqual(request('POST',path,self.token,{'crew_member_id':MEMBER})[0],401)
            self.assertEqual(request('POST',path,'test-owner',{'crew_member_id':MEMBER})[0],200)
            self.assertEqual(request('GET','/installations/current',self.token)[1]['state'],'approved')
            self.assertEqual(request('GET','/health',self.token)[1]['scope'],'hosted')
            self.assertEqual(request('GET','/hosted/installations',self.token)[0],403)
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
