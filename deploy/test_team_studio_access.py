import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from chat_router import Hub

MEMBER = 'apple-17b4234e-cf4a-4431-af8e-c77060aca954'

class TeamStudioAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'central.sqlite'
        self.central = sqlite3.connect(self.database)
        self.central.execute('CREATE TABLE records(key TEXT PRIMARY KEY,payload TEXT)')
        self.member = dict(id=MEMBER, kind='human', source='apple-development-team', lifecycle='active')
        self.save_member()
        self.env = patch.dict(os.environ, FMVISION_DATABASE=str(self.database)); self.env.start()
        self.hub = Hub(Path(self.temp.name) / 'auth', registry={})
        self.grant = dict(project='fmvisual', capabilities=['crew.read'], crew_member_id=MEMBER)
    def save_member(self):
        self.central.execute('INSERT OR REPLACE INTO records VALUES(?,?)', ('roster',json.dumps({'crew':[self.member]})))
        self.central.commit()
    def tearDown(self):
        self.hub.conn.close(); self.central.close(); self.env.stop(); self.temp.cleanup()
    def test_team_pairing_auto_grants_chat_without_control(self):
        invite = self.hub.invitation('owner',self.grant)
        joined = self.hub.redeem_invitation(invite['code'],'phone')
        self.assertEqual(set(self.hub.studio_access(joined['token'])['capabilities']), {'crew.read','crew.chat','tasks.read'})
        self.member['lifecycle']='retired'; self.save_member()
        self.assertIsNone(self.hub.studio_access(joined['token']))
    def test_revocation_explicit_denial_and_unbound_device_are_preserved(self):
        invite=self.hub.invitation('owner',self.grant)
        joined=self.hub.redeem_invitation(invite['code'],'Luke Ramsay')
        self.hub.set_studio_access(joined['device_id'],None)
        self.assertIsNone(self.hub.studio_access(joined['token']))
        self.assertEqual(self.hub.team_studio_grant(dict(self.grant,capabilities=[]))['capabilities'],[])
        unbound=self.hub.redeem_invitation(self.hub.invitation('owner')['code'],'Luke Ramsay')
        self.assertIsNone(self.hub.studio_access(unbound['token']))
    def test_membership_removed_before_redemption_and_missing_authority_fail_closed(self):
        invite=self.hub.invitation('owner',self.grant)
        self.central.execute('DELETE FROM records');self.central.commit()
        joined=self.hub.redeem_invitation(invite['code'],'phone')
        self.assertIsNone(joined['studio_access'])
        self.assertIsNone(self.hub.team_studio_grant(self.grant))

if __name__=='__main__': unittest.main()
