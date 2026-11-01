import asyncio,json,sqlite3,tempfile,threading,time,unittest,uuid
from pathlib import Path
from agent_notifications import AgentNotifications

class StopNotificationTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.now=0
  self.service=AgentNotifications(self.db,clock=lambda:self.now)
  self.service.register('owner',{'id':str(uuid.uuid4()),'token':'ab'*32,'environment':'sandbox','enabled':True})
 def tearDown(self):self.db.close()
 def emit(self,working,known=True):self.service.observe({'rowan':{'name':'Rowan','working':working,'activityKnown':known}})
 def advance(self,seconds):self.now+=seconds;self.service.flush_stops()
 def count(self):return self.db.execute('SELECT count(*) FROM agent_stops').fetchone()[0]
 def test_only_sustained_known_idle_after_work_creates_one_alert(self):
  self.emit(False);self.advance(60);self.assertEqual(self.count(),0)
  self.emit(True);self.emit(False);self.advance(29);self.assertEqual(self.count(),0)
  self.emit(False);self.advance(1);self.assertEqual(self.count(),1)
  self.advance(60);self.emit(False);self.advance(60);self.assertEqual(self.count(),1)
  self.assertEqual(self.db.execute('SELECT count(*) FROM push_deliveries').fetchone()[0],1)
 def test_brief_pause_cancels_and_a_later_stop_gets_a_fresh_grace_period(self):
  self.emit(True);self.emit(False);self.advance(20);self.emit(True);self.advance(60)
  self.assertEqual(self.count(),0)
  self.emit(False);self.advance(29);self.assertEqual(self.count(),0)
  self.advance(1);self.assertEqual(self.count(),1)
 def test_unknown_invalid_and_disconnected_activity_cancel_stop_candidates(self):
  for reset in [lambda:self.emit(False,False),lambda:self.emit(None),lambda:self.service.observe({'rowan':{'working':False,'activityKnown':True,'relayOnline':False}}),lambda:self.service.reset(['rowan'])]:
   self.emit(True);self.emit(False);self.advance(10);reset();self.advance(60)
   self.emit(False);self.advance(60);self.assertEqual(self.count(),0)
 def test_resuming_cancels_queued_stop_retries_but_keeps_feedback(self):
  self.emit(True);self.emit(False);self.advance(30)
  with self.db:
   self.db.execute('INSERT INTO agent_stops VALUES(?,?,?,?)',('fb:question','rowan','Rowan',time.time()))
   self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT 'fb:question',id,'pending' FROM push_devices")
  self.emit(True)
  states=dict(self.db.execute('SELECT event,state FROM push_deliveries'))
  self.assertEqual(states['fb:question'],'pending')
  self.assertEqual([v for k,v in states.items() if not k.startswith('fb:')],['cancelled'])
 def test_unregistered_devices_get_no_delivery_and_pairings_are_isolated(self):
  db=sqlite3.connect(':memory:');service=AgentNotifications(db,clock=lambda:self.now)
  service.observe({'a':{'activityKnown':True,'working':True}});service.observe({'a':{'activityKnown':True,'working':False}})
  self.now+=30;service.flush_stops();self.assertEqual(db.execute('SELECT count(*) FROM push_deliveries').fetchone()[0],0)
  identity=str(uuid.uuid4());body={'id':identity,'token':'cd'*32,'enabled':True};service.register('first',body)
  with self.assertRaises(ValueError):service.register('other',body)
  db.close()
 def test_invalid_grace_is_rejected(self):
  for value in [-1,301]:
   with self.assertRaises(ValueError):AgentNotifications(self.db,grace_seconds=value)

class NotificationWorkerTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.directory=tempfile.TemporaryDirectory();self.db=sqlite3.connect(':memory:')
  self.config=Path(self.directory.name)/'push.json';self.config.write_text('{}')
  self.loop=asyncio.get_running_loop();self.sent=[];self.delivered=asyncio.Event();self.task=None
 async def asyncTearDown(self):
  if self.task:
   self.task.cancel();await asyncio.gather(self.task,return_exceptions=True)
  self.db.close();self.directory.cleanup()
 def start(self,grace):
  self.service=AgentNotifications(self.db,config=self.config,grace_seconds=grace)
  self.service.register('owner',{'id':str(uuid.uuid4()),'token':'ab'*32,'enabled':True})
  def fake_send(config,device,event):
   self.sent.append(event);self.loop.call_soon_threadsafe(self.delivered.set);return 'sent'
  self.service.send=fake_send;self.task=asyncio.create_task(self.service.run())
 def stop(self):
  self.service.observe({'rowan':{'activityKnown':True,'working':True}})
  self.service.observe({'rowan':{'activityKnown':True,'working':False}})
 async def test_deadline_wakes_worker_without_another_activity_event(self):
  self.start(.03);self.stop()
  self.assertEqual(self.db.execute('SELECT count(*) FROM agent_stops').fetchone()[0],0)
  await asyncio.wait_for(self.delivered.wait(),3)
  self.assertEqual(len(self.sent),1);self.assertEqual(self.sent[0][1],'rowan')
 async def test_feedback_is_immediate_while_stop_grace_is_pending(self):
  self.start(30);self.stop()
  with self.db:
   self.db.execute('INSERT INTO agent_stops VALUES(?,?,?,?)',('fb:question','rowan','Rowan',time.time()))
   self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT 'fb:question',id,'pending' FROM push_devices")
  self.service.ready.set();await asyncio.wait_for(self.delivered.wait(),3)
  self.assertEqual([row[0] for row in self.sent],['fb:question']);self.assertIn('rowan',self.service.stops)
 async def test_resuming_during_a_failed_send_cannot_requeue_the_cancelled_alert(self):
  self.start(0);released=threading.Event()
  def resume():
   self.service.observe({'rowan':{'activityKnown':True,'working':True}});released.set()
  def retry(config,device,event):
   self.loop.call_soon_threadsafe(resume);released.wait(2);self.loop.call_soon_threadsafe(self.delivered.set);return 'retry'
  self.service.send=retry;self.stop();await asyncio.wait_for(self.delivered.wait(),3)
  for _ in range(10):await asyncio.sleep(0)
  self.assertEqual(self.db.execute('SELECT state FROM push_deliveries').fetchone()[0],'cancelled')
 async def test_restart_drops_unqualified_old_stop_but_preserves_feedback(self):
  self.start(30)
  with self.db:
   for identity in ['old-stop','fb:question']:
    self.db.execute('INSERT INTO agent_stops VALUES(?,?,?,?)',(identity,'rowan','Rowan',time.time()))
    self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT ?,id,'pending' FROM push_devices",(identity,))
  self.service.ready.set();await asyncio.wait_for(self.delivered.wait(),3)
  self.assertEqual([row[0] for row in self.sent],['fb:question'])
  self.assertEqual(self.db.execute("SELECT state FROM push_deliveries WHERE event='old-stop'").fetchone()[0],'cancelled')
