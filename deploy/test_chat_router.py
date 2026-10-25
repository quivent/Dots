import json
from pathlib import Path
import tempfile
import unittest
import uuid
import hashlib
import threading
import time
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from chat_router import Hub, Handler


class ChatRouterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.hub = Hub(Path(self.temp.name), registry={n: {'name': n, 'profile': n.lower(), 'thread_id': str(uuid.uuid4()), 'workspace': self.temp.name} for n in ['Wavesmith', 'Belle']})
        self.dispatched = []
        self.hub.dispatch = lambda job, text: self.dispatched.append(job)
        self.room = self.hub.db('SELECT * FROM rooms WHERE id=?', ('hub-wavesmith',), one=True)

    def tearDown(self):
        self.hub.conn.close()
        self.temp.cleanup()

    def message(self, approved=False):
        identity = str(uuid.uuid4())
        return {'request_id': identity, 'idempotency_token': identity, 'content': {'text': 'Hello', 'attachments': []}, 'work_approved': approved}

    def test_no_credit_consuming_turn_without_approval(self):
        with self.assertRaises(PermissionError): self.hub.submit(self.room, self.message())
        self.assertEqual(self.hub.db('SELECT * FROM requests'), [])
        self.assertEqual(self.hub.db('SELECT * FROM messages'), [])
        self.assertEqual(self.dispatched, [])

    def test_people_only_chat_has_named_senders_and_no_agent_jobs(self):
        joined = self.hub.redeem_invitation(self.hub.invitation('owner-token')['code'], 'Alex')
        owner, friend = self.hub.person('owner-token'), self.hub.person(joined['token'])
        self.hub.db('UPDATE people SET name=? WHERE id=?', ('Jay', owner))
        body = {'name': 'Jay & Alex', 'members': [], 'people': [friend], 'request_id': str(uuid.uuid4())}
        profile = self.hub.create_room(body, owner)
        self.assertTrue(profile['human_only']); self.assertFalse(profile['is_paused'])
        self.assertEqual(self.hub.create_room(body, owner), profile)
        room = self.hub.resolve_profile(profile['id'])
        outgoing = self.message()
        self.hub.submit(room, outgoing, owner)
        self.hub.submit(room, self.message(), friend)
        self.assertEqual(self.hub.db('SELECT * FROM jobs'), [])
        self.assertEqual(self.dispatched, [])
        ours = self.hub.history(room['id'], person=owner)['items']
        theirs = self.hub.history(room['id'], person=friend)['items']
        self.assertEqual([m['sender_is_self'] for m in ours], [True, False])
        self.assertEqual([m['sender_is_self'] for m in theirs], [False, True])
        self.assertEqual([m['sender_display_name'] for m in ours], ['Jay', 'Alex'])
        self.assertTrue(all(m['role'] == 'user' for m in ours))
        with self.assertRaises(ValueError): self.hub.submit(room, outgoing, friend)
        self.hub.submit(room, outgoing, owner)
        self.assertEqual(len(self.hub.history(room['id'])['items']), 2)

    def test_private_room_http_excludes_nonparticipants_everywhere(self):
        guests = [self.hub.redeem_invitation(self.hub.invitation('owner-token')['code'], name) for name in ('Alex', 'Sam', 'Outsider')]
        first, second, outsider = [self.hub.person(g['token']) for g in guests]
        profile = self.hub.create_room({'name': 'Private', 'members': ['hosted-belle'], 'people': [second], 'request_id': str(uuid.uuid4())}, first)
        room = self.hub.resolve_profile(profile['id'])
        self.hub.submit(room, self.message(True), first)
        job = self.hub.db('SELECT * FROM jobs', one=True)
        self.hub.db('INSERT INTO approvals VALUES(?,?,?,?,?,?)', ('fixture-approval', job['id'], 'belle', '1', '{}', 'pending'))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.hub = self.hub
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def call(path, body=None, token=guests[2]['token']):
            req = Request('http://127.0.0.1:' + str(server.server_port) + '/v1' + path,
                headers={'Authorization': 'Bearer ' + token}, data=json.dumps(body).encode() if body is not None else None)
            try:
                with urlopen(req) as r: return r.status, json.load(r)
            except HTTPError as e: return e.code, json.load(e)
        try:
            self.assertNotIn(profile['id'], [p['id'] for p in call('/tbo')[1]['items']])
            self.assertNotIn(profile['id'], [p['id'] for p in call('/hosted/rooms')[1]['items']])
            self.assertIn(profile['id'], [p['id'] for p in call('/hosted/rooms', token=guests[1]['token'])[1]['items']])
            self.assertEqual(call('/tbo/' + profile['id'])[0], 403)
            self.assertEqual(call('/tbo/' + profile['id'] + '/tasks')[0], 403)
            self.assertEqual(call('/tbo/' + profile['id'] + '/runtime/pause', {})[0], 403)
            self.assertEqual(call('/hosted/rooms/' + room['id'] + '/approvals')[0], 403)
            self.assertEqual(call('/hosted/approvals/fixture-approval', {'accept': True})[0], 403)
            path = '/messaging/rooms/' + room['id'] + '/messages'
            self.assertEqual(call(path)[0], 403)
            self.assertEqual(call(path, self.message(True))[0], 403)
            self.assertEqual(call(path, token=guests[1]['token'])[0], 200)
            self.assertEqual(call('/hosted/people/me', {'name': 'Sam renamed'}, token=guests[1]['token'])[0], 200)
            self.assertIn('Sam renamed', [p['name'] for p in call('/hosted/people')[1]['items']])
            self.assertEqual(call('/hosted/rooms', {'name': 'Unknown', 'members': [], 'people': ['missing'], 'request_id': str(uuid.uuid4())})[0], 400)
        finally:
            server.shutdown(); server.server_close(); worker.join()

    def test_hosted_room_list_does_not_wait_for_mac_or_provider(self):
        class NoMacHandler(Handler):
            def upstream(self, *args, **kwargs):
                raise AssertionError('Hosted discovery must not call the Mac')
        server = ThreadingHTTPServer(('127.0.0.1', 0), NoMacHandler); server.hub = self.hub
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with patch.object(self.hub, 'authorized', return_value=True):
                req = Request('http://127.0.0.1:' + str(server.server_port) + '/v1/hosted/rooms', headers={'Authorization': 'Bearer owner-fixture'})
                with urlopen(req, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(len(json.load(response)['items']), 2)
        finally:
            server.shutdown(); server.server_close(); worker.join()

    def test_people_only_room_requires_another_person_and_survives_restart(self):
        owner = self.hub.person('owner-token')
        body = {'name': 'Empty', 'members': [], 'people': [], 'request_id': str(uuid.uuid4())}
        with self.assertRaises(ValueError): self.hub.create_room(body, owner)
        friend = self.hub.redeem_invitation(self.hub.invitation('owner-token')['code'], 'Friend')
        person = self.hub.person(friend['token']); body['people'] = [person]
        profile = self.hub.create_room(body, owner)
        self.assertFalse(self.hub.can_access(profile['messaging_room_id'], 'outsider'))
        self.hub.conn.close()
        self.hub = Hub(Path(self.temp.name), registry={n: a.entry for n, a in self.hub.agents.items()})
        self.assertTrue(self.hub.can_access(profile['messaging_room_id'], person))
        self.assertFalse(self.hub.can_access(profile['messaging_room_id'], 'outsider'))

    def test_same_request_is_not_dispatched_twice(self):
        body = self.message(True)
        result = self.hub.submit(self.room, body)
        self.assertEqual(self.hub.submit(self.room, body), result)
        self.assertEqual(len(self.hub.db('SELECT * FROM jobs')), 1)
        body['content']['text'] = 'Different work'
        with self.assertRaises(ValueError): self.hub.submit(self.room, body)

    def test_shared_chat_targets_only_selected_members(self):
        self.hub.db('INSERT INTO rooms VALUES(?,?,?)', ('hub-group', 'Together', json.dumps(['wavesmith', 'belle'])))
        room = self.hub.db('SELECT * FROM rooms WHERE id=?', ('hub-group',), one=True)
        self.hub.submit(room, self.message(True))
        self.assertEqual({j['agent'] for j in self.hub.db('SELECT * FROM jobs')}, {'wavesmith', 'belle'})
        self.assertEqual(self.hub.profile(room)['member_names'], ['Wavesmith', 'Belle'])

    def test_paused_and_context_reserve_block_new_turns(self):
        self.hub.db('INSERT INTO flags VALUES(?,?)', ('wavesmith', 1))
        with self.assertRaises(ValueError): self.hub.submit(self.room, self.message(True))
        self.hub.db('DELETE FROM flags')
        self.hub.db('INSERT INTO usage VALUES(?,?,?)', ('wavesmith', 900_000, 1_050_000))
        with self.assertRaises(ValueError): self.hub.submit(self.room, self.message(True))
        self.assertEqual(self.hub.db('SELECT * FROM jobs'), [])

    def test_router_restart_preserves_history_and_never_replays_uncertain_jobs(self):
        self.hub.submit(self.room, self.message(True))
        self.hub.conn.close()
        self.hub = Hub(Path(self.temp.name), registry={n: a.entry for n, a in self.hub.agents.items()})
        self.assertEqual(self.hub.db('SELECT status FROM jobs'), [{'status': 'unknown'}])
        self.assertEqual(len(self.hub.history('hub-wavesmith')['items']), 1)
        with self.assertRaises(ValueError): self.hub.decide(str(uuid.uuid4()), True)

    def test_context_guard_counts_forwarded_history(self):
        self.hub.add_message('hub-wavesmith', 'Wavesmith', 'x' * 12000)
        self.hub.db('INSERT INTO usage VALUES(?,?,?)', ('wavesmith', 898_000, 1_000_000))
        with self.assertRaises(ValueError): self.hub.submit(self.room, self.message(True))
        self.assertEqual(self.hub.db('SELECT * FROM jobs'), [])

    def test_quiet_listener_does_not_emit_a_chat_message_or_start_more_jobs(self):
        self.hub.submit(self.room, self.message(True))
        agent = self.hub.agents['wavesmith']
        agent.job = self.hub.db('SELECT * FROM jobs', one=True)
        agent.reply_items = ['An intermediate acknowledgement.', '[[DOTS_QUIET]]']
        self.hub.finish(agent, 'completed')
        self.assertEqual(self.hub.db('SELECT status,reply_outcome FROM jobs'), [{'status': 'completed', 'reply_outcome': 'quiet'}])
        self.assertEqual(len(self.hub.history('hub-wavesmith')['items']), 1)
        self.assertEqual(len(self.hub.db('SELECT * FROM jobs')), 1)

    def test_relevant_response_is_saved_once_after_completion(self):
        self.hub.submit(self.room, self.message(True))
        agent = self.hub.agents['wavesmith']
        agent.job = self.hub.db('SELECT * FROM jobs', one=True)
        agent.reply_items = ['A useful contribution.']
        self.hub.finish(agent, 'completed'); self.hub.finish(agent, 'completed')
        self.assertEqual(self.hub.db('SELECT reply_outcome FROM jobs'), [{'reply_outcome': 'replied'}])
        self.assertEqual([m['content']['text'] for m in self.hub.history('hub-wavesmith')['items']], ['Hello', 'A useful contribution.'])

    def test_group_turn_includes_relevance_policy_without_unapproved_followups(self):
        self.hub.db('INSERT INTO rooms VALUES(?,?,?)', ('hub-group', 'Together', json.dumps(['wavesmith', 'belle'])))
        room = self.hub.db('SELECT * FROM rooms WHERE id=?', ('hub-group',), one=True)
        self.hub.submit(room, self.message(True))
        job = self.hub.db('SELECT * FROM jobs WHERE agent=?', ('wavesmith',), one=True)
        agent = self.hub.agents['wavesmith']; agent.connect = lambda: None
        calls = []
        agent.call = lambda method, params: calls.append((method, params)) or {'turn': {'id': 'test-turn'}}
        Hub.dispatch(self.hub, job, 'Hello')
        self.assertEqual(len(calls), 1)
        self.assertIn('GROUP LISTENING POLICY', calls[0][1]['input'][0]['text'])
        self.assertIn('[[DOTS_QUIET]]', calls[0][1]['input'][0]['text'])
        self.assertEqual(len(self.hub.db('SELECT * FROM jobs')), 2)

    def test_server_invites_work_without_mac_and_are_single_use_expiring_and_revocable(self):
        invitation = self.hub.invitation('owner-token')
        self.assertEqual(len(invitation['code']), 8)
        joined = self.hub.redeem_invitation(invitation['code'], 'Android phone')
        self.assertTrue(self.hub.authorized(joined['token']))
        self.assertTrue(self.hub.is_member(joined['token']))
        self.assertIsNone(self.hub.redeem_invitation(invitation['code'], 'Duplicate'))
        self.hub.db('UPDATE devices SET revoked=1 WHERE id=?', (joined['device_id'],))
        self.assertFalse(self.hub.authorized(joined['token']))
        expired = self.hub.invitation('owner-token')
        self.hub.db('UPDATE invitations SET expires=0 WHERE id=?', (expired['id'],))
        self.assertIsNone(self.hub.redeem_invitation(expired['code'], 'Expired'))
        prior = self.hub.invitation('owner-token')
        self.hub.invitation('owner-token')
        self.assertIsNone(self.hub.redeem_invitation(prior['code'], 'Replaced'))

    def test_invited_phone_cannot_invite_revoke_or_access_mac_account(self):
        invitation = self.hub.invitation('owner-token')
        joined = self.hub.redeem_invitation(invitation['code'], 'Member phone')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.hub = self.hub
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def call(path, body=None):
            req = Request('http://127.0.0.1:' + str(server.server_port) + '/v1' + path,
                headers={'Authorization': 'Bearer ' + joined['token']}, data=json.dumps(body).encode() if body is not None else None)
            try:
                with urlopen(req) as r: return r.status, json.load(r)
            except HTTPError as e: return e.code, json.load(e)
        try:
            self.assertEqual(call('/hosted/invitations', {})[0], 403)
            self.assertEqual(call('/hosted/devices')[0], 403)
            self.assertEqual(call('/tbo/account-pocket')[0], 403)
            status, catalog = call('/tbo')
            self.assertEqual(status, 200)
            self.assertTrue(all(p['source'] == 'hosted' for p in catalog['items']))
            self.assertEqual(call('/health')[1]['scope'], 'hosted')
        finally:
            server.shutdown(); server.server_close(); worker.join()

    def test_operation_approval_is_once_and_cannot_be_replayed(self):
        body = self.message(True)
        self.hub.submit(self.room, body)
        agent = self.hub.agents['wavesmith']
        agent.job = self.hub.db('SELECT * FROM jobs', one=True)
        agent.ws = object()
        sent = []
        agent.send = sent.append
        self.hub.approval(agent, {'id': 17, 'params': {'command': 'ls'}})
        approval = self.hub.db('SELECT * FROM approvals', one=True)
        self.hub.decide(approval['id'], True)
        self.assertEqual(sent, [{'id': 17, 'result': {'decision': 'accept'}}])
        with self.assertRaises(ValueError): self.hub.decide(approval['id'], True)
        self.assertEqual(len(sent), 1)

    def test_new_phone_pairing_needs_code_not_an_existing_credential(self):
        paired_token = 'test-new-phone-credential-value'
        class PairHandler(Handler):
            def upstream(self, method, token, body=None, raw=False):
                if self.path == '/v1/pair' and body == {'code': '123456'} and token == '' and raw:
                    return 200, {'token': paired_token, 'name': 'Test Mac'}
                return 403, {'error': 'Invalid code'}
        server = ThreadingHTTPServer(('127.0.0.1', 0), PairHandler); server.hub = self.hub
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def call(path, body=None, token=None):
            request = Request('http://127.0.0.1:' + str(server.server_port) + path,
                              data=json.dumps(body).encode() if body is not None else None,
                              headers={'Authorization': 'Bearer ' + token} if token else {})
            try:
                with urlopen(request) as response: return response.status, json.load(response)
            except HTTPError as error: return error.code, json.load(error)
        try:
            with patch('chat_router.Path.read_text', return_value='[]'):
                self.assertEqual(call('/v1/health')[0], 401)
                self.assertEqual(call('/v1/pair', {'code': 'bad'})[0], 400)
                self.assertEqual(call('/v1/pair', {'code': '000000'})[0], 403)
                self.assertEqual(call('/v1/pair', {'code': '123456'})[1]['token'], paired_token)
                self.assertEqual(call('/v1/health', token=paired_token)[0], 200)
                self.hub.new_device_hashes[hashlib.sha256(paired_token.encode()).hexdigest()] = time.monotonic() - 1
                self.assertEqual(call('/v1/health', token=paired_token)[0], 401)
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__': unittest.main()
