"""No provider traffic: exercise exact-session reply transitions and durable dedup."""
import sqlite3,tempfile,unittest,uuid,json
from pathlib import Path
from agent_notifications import AgentNotifications
class ReplyNotifications(unittest.TestCase):
 def test_replies_are_not_stops_and_repeat_history_does_not_realert(self):
  db=sqlite3.connect(':memory:')
  with tempfile.TemporaryDirectory() as directory:
   policy=Path(directory)/'policy';policy.write_text(json.dumps({'responseOnly':True,'stopAlertsDisabledFor':['aven']}))
   service=AgentNotifications(db,stop_policy=policy);service.badge_count=lambda:1
   service.register('owner',{'id':str(uuid.uuid4()),'token':'ab'*32,'enabled':True})
   session=str(uuid.uuid4());roster={'crew':[{'id':'aven','sessionId':session}]}
   def row(ids):return {'aven':{'nativeSessionId':session,'name':'Aven','history':{'items':[{'id':i,'role':'assistant','content':{'text':'same text'}} for i in ids]}}}
   service.observe_replies(row(['old']),roster)
   self.assertEqual(db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],0)
   service.observe_replies(row(['old','new']),roster)
   service.observe_replies(row(['old','new']),roster)
   service.cancel_stop('aven')
   event=db.execute('SELECT id,agent,name,at FROM agent_stops').fetchone()
   self.assertTrue(service.reply_current(event));self.assertEqual(service.payload(event)['nativeSessionId'],session);self.assertEqual(service.payload(event)['kind'],'reply');self.assertEqual(service.payload(event)['aps']['badge'],1)
   self.assertEqual(db.execute('SELECT state FROM push_deliveries').fetchone()[0],'pending')
   service.observe_replies(row(['old','new','another']),roster)
   self.assertEqual(db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],2)
   service.observe_replies(row(['old','new']),roster);service.observe_replies(row(['old','new','another']),roster)
   self.assertEqual(db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],2)
   roster['crew'][0]['sessionId']=str(uuid.uuid4())
   service.observe_replies(row(['old','new','wrong-session']),roster)
   self.assertFalse(service.reply_current(event))
   self.assertEqual(db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],2)
  db.close()

 def test_hub_publish_emits_new_reply_even_when_unread_count_stays_one(self):
  from vmfactory_hub import State
  with tempfile.TemporaryDirectory() as directory:
   state=State(Path(directory)/'hub.sqlite')
   session=str(uuid.uuid4())
   state.publish({'roster':{'crew':[{'id':'aven','sessionId':session}]},'agents':{'aven':{'nativeSessionId':session,'name':'Aven','history':{'items':[]}}}})
   state.notifications.register('owner',{'id':str(uuid.uuid4()),'token':'ab'*32,'enabled':True})
   def rows(ids):return {'agents':{'aven':{'nativeSessionId':session,'history':{'items':[{'id':i,'role':'assistant','content':{'text':'same'}} for i in ids]}}}}
   state.publish(rows(['one']));state.publish(rows(['one','two']));state.publish(rows(['one','two']))
   self.assertEqual(state.db.execute("SELECT count(*) FROM agent_stops WHERE id LIKE 'reply:%'").fetchone()[0],2)
   state.close()
if __name__=='__main__':unittest.main()
