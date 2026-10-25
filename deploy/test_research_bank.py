from pathlib import Path
import tempfile
import unittest
import os
import socket
import threading
from unittest.mock import patch
from types import SimpleNamespace
from research_bank import Bank, Server, Handler
import bank_client


class ResearchBankTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bank = Bank(Path(self.temp.name))

    def tearDown(self):
        self.bank.conn.close(); self.temp.cleanup()

    def payload(self, key='request-1'):
        return {'entry': {'title': 'Ocean research', 'synthesis': 'A synthesis with evidence and limitations.',
                         'sources': [{'title': 'Source', 'url': 'https://example.org/study'}], 'tags': ['oceans'], 'uncertainty': 'Preliminary'},
                'request_id': key, 'author': 'Wavesmith', 'room': 'hub-group', 'thread': 'thread-1'}

    def test_persistence_idempotency_and_attribution(self):
        body = self.payload()
        saved = self.bank.save(body)
        self.assertEqual(self.bank.save(body)['id'], saved['id'])
        self.bank.conn.close(); self.bank = Bank(Path(self.temp.name))
        self.assertEqual(self.bank.get(saved['id'])['author'], 'Wavesmith')
        self.assertEqual(self.bank.get(saved['id'])['sources'], body['entry']['sources'])
        body['entry']['synthesis'] = 'Changed'
        with self.assertRaises(ValueError): self.bank.save(body)

    def test_revision_preserves_original(self):
        original = self.bank.save(self.payload())
        revised = self.payload('revision'); revised['entry']['supersedes'] = original['id']
        revised['entry']['synthesis'] = 'Updated evidence.'
        newer = self.bank.save(revised)
        self.assertEqual(newer['supersedes'], original['id'])
        self.assertEqual(self.bank.get(original['id'])['synthesis'], original['synthesis'])

    def test_search_pagination_and_literal_query(self):
        for n in range(27): self.bank.save(self.payload(str(n)))
        first = self.bank.search('ocean evidence')
        self.assertEqual(len(first['items']), 25)
        self.assertNotIn('synthesis', first['items'][0])
        self.assertEqual(len(self.bank.search('', first['next_cursor'])['items']), 2)
        self.assertEqual(self.bank.search('%')['items'], [])

    def test_invalid_links_and_entries_are_rejected(self):
        for url in ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:pass@example.org']:
            body = self.payload(); body['entry']['sources'][0]['url'] = url
            with self.assertRaises(ValueError): self.bank.save(body)
        body = self.payload(); body['entry']['supersedes'] = 'missing'
        with self.assertRaises(ValueError): self.bank.save(body)
        self.assertEqual(self.bank.search()['items'], [])

    def test_tools_require_current_approved_job_and_identity_is_trusted(self):
        agent = SimpleNamespace(job=None, turn='turn-1', entry={'thread_id': 'thread-1', 'name': 'Belle'})
        params = {'tool': 'bank_save', 'arguments': self.payload()['entry'], 'callId': 'call-1', 'threadId': 'thread-1', 'turnId': 'turn-1'}
        with self.assertRaises(PermissionError): bank_client.execute(agent, params)
        agent.job = {'id': 'job-1', 'room': 'hub-group'}
        with patch.object(bank_client, 'request', side_effect=lambda method, path, body: self.bank.save(body)):
            saved = bank_client.execute(agent, params)
            self.assertEqual(bank_client.execute(agent, params)['id'], saved['id'])
            params['callId'] = 'retry-call'
            self.assertEqual(bank_client.execute(agent, params)['id'], saved['id'])
            self.assertEqual(self.bank.get(saved['id'])['author'], 'Belle')
            params['turnId'] = 'old-turn'
            with self.assertRaises(PermissionError): bank_client.execute(agent, params)

    @unittest.skipUnless(hasattr(socket, 'SO_PEERCRED'), 'Linux Unix peer credentials')
    def test_private_socket_transport_and_peer_identity(self):
        path = str(Path(self.temp.name) / 'bank.sock')
        server = Server(path, Handler); server.bank = self.bank; server.allowed_uid = os.getuid()
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with patch.object(bank_client, 'SOCKET_PATH', path):
                saved = bank_client.request('POST', '/entries', self.payload())
                self.assertEqual(bank_client.request('GET', '/entries/' + saved['id'])['title'], 'Ocean research')
                self.assertEqual(len(bank_client.request('GET', '/entries?q=Ocean')['items']), 1)
                body = self.payload('unicode'); body['entry']['synthesis'] = '海' * 50000
                unicode_entry = bank_client.request('POST', '/entries', body)
                self.assertEqual(bank_client.request('GET', '/entries/' + unicode_entry['id'])['synthesis'], body['entry']['synthesis'])
                if os.getuid() != 0:
                    server.allowed_uid = -1
                    with self.assertRaises(ValueError): bank_client.request('GET', '/entries')
        finally:
            server.shutdown(); server.server_close(); worker.join()


if __name__ == '__main__': unittest.main()
