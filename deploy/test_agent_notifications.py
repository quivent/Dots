import hashlib,sqlite3,tempfile,unittest,uuid
from pathlib import Path
from agent_notifications import AgentNotifications
class StopNotificationTests(unittest.TestCase):
 def test_only_known_live_working_to_idle_transitions_create_alerts(self):
  db=sqlite3.connect(':memory:');service=AgentNotifications(db)
  service.register('owner',{'id':str(uuid.uuid4()),'token':'ab'*32,'environment':'sandbox','enabled':True})
  def emit(working,known=True):service.observe({'rowan':{'name':'Rowan','working':working,'activityKnown':known}})
  count=lambda:db.execute('SELECT count(*) FROM agent_stops').fetchone()[0]
  emit(False);self.assertEqual(count(),0)
  emit(True);emit(False);self.assertEqual(count(),1)
  emit(False);self.assertEqual(count(),1)
  emit(True);emit(False,False);emit(False);self.assertEqual(count(),1)
  emit(True);service.reset(['rowan']);emit(False);self.assertEqual(count(),1)
  emit(True);emit(False);self.assertEqual(count(),2)
  self.assertEqual(db.execute('SELECT count(*) FROM push_deliveries').fetchone()[0],2)
 def test_unregistered_devices_get_no_delivery_and_pairings_are_isolated(self):
  db=sqlite3.connect(':memory:');service=AgentNotifications(db)
  service.observe({'a':{'activityKnown':True,'working':True}});service.observe({'a':{'activityKnown':True,'working':False}})
  self.assertEqual(db.execute('SELECT count(*) FROM push_deliveries').fetchone()[0],0)
  id=str(uuid.uuid4());body={'id':id,'token':'cd'*32,'enabled':True};service.register('first',body)
  with self.assertRaises(ValueError):service.register('other',body)
