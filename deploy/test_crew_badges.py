import json
import sqlite3
import tempfile
import unittest
import asyncio
from pathlib import Path
from crew_badges import CrewBadges
from feedback_inbox import FeedbackInbox,FeedbackNotifications
from vmfactory_hub import State

SESSION='00000000-0000-4000-8000-000000000001'
OTHER='00000000-0000-4000-8000-000000000002'
def message(i,role='assistant'):return {'id':i,'role':role,'sender_is_self':role=='user','content':{'text':'visible reply'}}

class BadgeTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');FeedbackInbox(self.db);self.badges=CrewBadges(self.db)
  self.agents={'aven':{'nativeSessionId':SESSION,'history':{'items':[message('first'),message('own','user')]}}}
  self.roster={'crew':[{'id':'aven','sessionId':SESSION}]}
 def summary(self):return self.badges.summary(self.agents,self.roster)
 def mark(self,ids,session=SESSION):return self.badges.mark_read({'agentId':'aven','nativeSessionId':session,'messageIds':ids},self.agents,self.roster)
 def tearDown(self):self.db.close()
 def test_counts_conversations_not_messages_or_idle(self):
  self.agents['aven']['working']=False;self.agents['aven']['history']['items']+= [message('second')]
  self.assertEqual(self.summary()['count'],1)
  self.assertEqual(self.mark(['first','second'])['count'],0)
  self.assertEqual(self.summary()['count'],0)
 def test_replay_does_not_reopen_read_conversation_but_new_message_does(self):
  self.mark(['first']);self.agents['aven']['history']['items']+=[message('first')]
  self.assertEqual(self.summary()['count'],0)
  self.agents['aven']['history']['items']+=[message('second')]
  self.assertEqual(self.summary()['count'],1)
 def test_read_race_never_clears_unobserved_new_message(self):
  self.agents['aven']['history']['items']+=[message('second')]
  self.assertEqual(self.mark(['first'])['count'],1)
 def test_binding_rejects_old_session_and_fabricated_or_own_ids(self):
  for ids,session in [(['first'],OTHER),(['unknown'],SESSION),(['own'],SESSION)]:
   with self.assertRaises(ValueError):self.mark(ids,session)
  self.assertEqual(self.summary()['count'],1)
 def test_removed_roster_and_held_members_are_not_counted(self):
  self.roster={'crew':[]};self.assertEqual(self.summary()['count'],0)
  self.roster={'crew':[{'id':'aven','sessionId':SESSION,'lifecycle':'on-hold'}]};self.assertEqual(self.summary()['count'],0)
 def test_rebound_session_has_separate_read_markers(self):
  self.mark(['first']);self.agents['aven']['nativeSessionId']=OTHER;self.roster['crew'][0]['sessionId']=OTHER
  self.assertEqual(self.summary()['count'],1)
 def test_explicit_open_feedback_survives_read_until_handled(self):
  inbox=FeedbackInbox(self.db)
  row,_=inbox.submit({'clientRequestId':'request','agentId':'aven','nativeSessionId':SESSION,'question':'Review this work?'},{'agents':['aven']})
  self.mark(['first']);self.assertEqual(self.summary()['count'],1)
  inbox.change(row['id'],{'operation':'handle','actionId':'handle-once','expectedStatusVersion':row['statusVersion']})
  self.assertEqual(self.summary()['count'],0)
 def test_read_markers_survive_store_reopen(self):
  self.mark(['first']);self.badges=CrewBadges(self.db);self.assertEqual(self.summary()['count'],0)
 def test_untyped_stopped_secret_or_wrong_source_records_are_not_attention(self):
  self.mark(['first'])
  row={'id':'a'*64,'kind':'question','agentId':'aven','nativeSessionId':SESSION,'status':'recorded','occurredAt':1,'question':'Review?','turnId':'t','itemId':'i','questionId':'q','isBlocking':True}
  envelope={'schema':'vmfactory.attention/1','agentId':'aven','nativeSessionId':SESSION,'events':[row]}
  self.agents['aven']['attention']=envelope;self.assertEqual(self.summary()['count'],1)
  for change in [{'kind':'stopped'},{'kind':'unknown'},{'isSecret':True},{'agentId':'other'},{'nativeSessionId':OTHER}]:
   envelope['events']=[dict(row,**change)];self.assertEqual(self.summary()['count'],0)

class HubBadgeTests(unittest.TestCase):
 def test_snapshot_read_and_restart_revision(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'hub.sqlite';s=State(p)
   s.publish({'roster':{'crew':[{'id':'aven','sessionId':SESSION}]},'agents':{'aven':{'nativeSessionId':SESSION,'history':{'items':[message('one')]}}}})
   original=s.viewer_revision();self.assertEqual(s.snapshot()['conversationBadges']['count'],1)
   s.badges.mark_read({'agentId':'aven','nativeSessionId':SESSION,'messageIds':['one']},s.badge_agents(),s.data['roster']);s.refresh_badges()
   self.assertNotEqual(s.viewer_revision(),original);self.assertEqual(s.snapshot()['conversationBadges']['count'],0)
   s.close();s=State(p);self.assertEqual(s.snapshot()['conversationBadges']['count'],0);s.close()
 def test_push_payload_uses_same_canonical_count_and_badge_updates_are_silent(self):
  db=sqlite3.connect(':memory:');n=FeedbackNotifications(db);n.badge_count=lambda:3
  self.assertEqual(n.payload(('badge:fixture','__badge__','',0)),{'aps':{'badge':3},'kind':'badge','eventId':'badge:fixture'})
  self.assertEqual(n.payload(('stop','iris','Iris',0))['aps']['badge'],3)
  db.close()

class ProviderThreadTests(unittest.IsolatedAsyncioTestCase):
 async def test_provider_payload_does_not_cross_sqlite_thread_boundary(self):
  with tempfile.TemporaryDirectory() as d:
   s=State(Path(d)/'hub.sqlite')
   s.publish({'roster':{'crew':[{'id':'aven','sessionId':SESSION}]},'agents':{'aven':{'nativeSessionId':SESSION,'history':{'items':[message('one')]}}}})
   payload=await asyncio.to_thread(s.notifications.payload,('badge:test','__badge__','',0))
   self.assertEqual(payload['aps']['badge'],1);s.close()

if __name__=='__main__':unittest.main()
