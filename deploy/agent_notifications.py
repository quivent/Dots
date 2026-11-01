"""Transition-triggered iOS alerts. No model calls, chat messages or activity polling."""
import asyncio,base64,hashlib,json,re,secrets,subprocess,time
from pathlib import Path
class AgentNotifications:
 def __init__(self,db,config=Path('/etc/dots-hub/vmfactory-apns.json'),grace_seconds=30,clock=time.monotonic,stop_policy=Path('/etc/dots-hub/agent-notification-policy.json')):
  if not 0<=grace_seconds<=300:raise ValueError("Invalid stopped-work grace period")
  self.db=db;self.config=Path(config);self.stop_policy=Path(stop_policy);self.reply_seen={};self.activity={};self.stops={};self.stop_events={};self.grace_seconds=grace_seconds;self.clock=clock;self.ready=asyncio.Event();self.jwt=None;self.jwt_time=0
  db.executescript('CREATE TABLE IF NOT EXISTS push_devices(id TEXT PRIMARY KEY,owner_hash TEXT NOT NULL,token TEXT NOT NULL,environment TEXT NOT NULL,enabled INTEGER NOT NULL,updated REAL NOT NULL,UNIQUE(token,environment)); CREATE TABLE IF NOT EXISTS agent_stops(id TEXT PRIMARY KEY,agent TEXT NOT NULL,name TEXT NOT NULL,at REAL NOT NULL); CREATE TABLE IF NOT EXISTS push_deliveries(event TEXT,device TEXT,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(event,device));')
  if 'topic' not in {row[1] for row in db.execute('PRAGMA table_info(push_devices)')}:
   with db:db.execute("ALTER TABLE push_devices ADD COLUMN topic TEXT NOT NULL DEFAULT 'pictures.influx.vmfactory.mobile'")
 def stop_alert_enabled(self,agent):
  # Operator-owned policy is separate from publisher-controlled activity/roles.
  # Re-read for each boundary so a changed exemption also cancels queued retries.
  try:
   policy=json.loads(self.stop_policy.read_text())
   if policy.get('responseOnly') is True:return False
   disabled=policy.get('stopAlertsDisabledFor',[])
  except (OSError,ValueError,AttributeError):disabled=[]
  return not (isinstance(disabled,list) and agent in disabled)
 def register(self,owner,body):
  import uuid
  id=str(uuid.UUID(body['id']));token=body['token'];environment=body.get('environment','sandbox');enabled=body.get('enabled');topic=body.get('topic','pictures.influx.vmfactory.mobile')
  if topic not in ('pictures.influx.vmfactory.mobile','influx.vision.fmvision'):raise ValueError('Unknown app notification topic')
  if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{32,512}',token) or environment not in ('sandbox','production') or type(enabled) is not bool:raise ValueError('Invalid push registration')
  digest=hashlib.sha256(owner.encode()).hexdigest()
  existing=self.db.execute('SELECT owner_hash FROM push_devices WHERE id=?',(id,)).fetchone()
  if existing and existing[0]!=digest:raise ValueError('Push installation belongs to another pairing')
  with self.db:self.db.execute('INSERT OR REPLACE INTO push_devices(id,owner_hash,token,environment,enabled,updated,topic) VALUES(?,?,?,?,?,?,?)',(id,digest,token,environment,int(enabled),time.time(),topic))
  return {'registered':True,'pushConfigured':self.config.is_file()}
 def cancel_stop(self,agent):
  self.stops.pop(agent,None);self.stop_events.pop(agent,None)
  # Explicit feedback requests have separate identities and remain immediate.
  with self.db:self.db.execute("UPDATE push_deliveries SET state='cancelled' WHERE state='pending' AND event IN (SELECT id FROM agent_stops WHERE agent=? AND id NOT LIKE 'fb:%' AND id NOT LIKE 'badge:%' AND id NOT LIKE 'reply:%')",(agent,))
 def reset(self,agents):
  for id in agents:self.activity.pop(id,None);self.cancel_stop(id)
  self.ready.set()
 def observe(self,agents):
  for id,row in agents.items():
   if not self.stop_alert_enabled(id):
    self.reset([id]);continue
   current=row.get('working')
   if row.get('activityKnown') is not True or row.get('relayOnline') is False or type(current) is not bool:
    self.reset([id]);continue
   previous=self.activity.get(id);self.activity[id]=current
   if current:
    if previous is not True or id in self.stops:self.cancel_stop(id)
    continue
   if previous is True:
    name=row.get('name') or ('Maestro' if id=='maestro' else id)
    self.stops[id]=(secrets.token_hex(16),id,name,time.time(),self.clock()+self.grace_seconds)
    self.stop_events[id]=self.stops[id][0]
  self.ready.set()
 def flush_stops(self):
  now=self.clock()
  for id,candidate in list(self.stops.items()):
   if not self.stop_alert_enabled(id):
    self.reset([id]);continue
   if candidate[4]>now:continue
   self.stops.pop(id,None)
   if self.activity.get(id) is not False or self.stop_events.get(id)!=candidate[0]:continue
   with self.db:
    self.db.execute('INSERT INTO agent_stops VALUES(?,?,?,?)',candidate[:4])
    self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT ?,id,'pending' FROM push_devices WHERE enabled=1",(candidate[0],))
 def token(self,config):
  if self.jwt and time.time()-self.jwt_time<1200:return self.jwt
  from cryptography.hazmat.primitives import hashes,serialization
  from cryptography.hazmat.primitives.asymmetric import ec,utils
  encode=lambda v:base64.urlsafe_b64encode(v).rstrip(b'=').decode()
  self.jwt_time=int(time.time());unsigned=encode(json.dumps({'alg':'ES256','kid':config['key_id']},separators=(',',':')).encode())+'.'+encode(json.dumps({'iss':config['team_id'],'iat':self.jwt_time},separators=(',',':')).encode())
  key=serialization.load_pem_private_key(Path(config['key_path']).read_bytes(),None);r,s=utils.decode_dss_signature(key.sign(unsigned.encode(),ec.ECDSA(hashes.SHA256())))
  self.jwt=unsigned+'.'+encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'));return self.jwt
 def payload(self,event):
  identity,agent,name,at=event
  badge=max(0,int(self.badge_count())) if hasattr(self,'badge_count') else 0
  if identity.startswith('badge:'):return {'aps':{'badge':badge},'kind':'badge','eventId':identity}
  if identity.startswith('reply:'):return {'aps':{'alert':{'title':name+' replied','body':'Open the conversation to read the reply.'},'sound':'default','thread-id':'crew-'+agent,'badge':badge},'kind':'reply','agentId':agent,'eventId':identity}
  return {'aps':{'alert':{'title':name+' stopped working','body':'Open the conversation to see why.'},'sound':'default','thread-id':'crew-'+agent,'badge':badge},'agentId':agent,'eventId':identity}
 def observe_replies(self,agents,roster):
  from crew_badges import CrewBadges
  active=set()
  for agent,(session,row) in CrewBadges.members(agents,roster).items():
   key=(agent,session);active.add(key);current=CrewBadges.incoming(row)
   previous=self.reply_seen.get(key);self.reply_seen[key]=current
   if previous is None:continue # Baseline/reconnect never re-alerts existing history.
   for message in sorted(current-previous):
    identity='reply:'+hashlib.sha256(json.dumps([agent,session,message],separators=(',',':')).encode()).hexdigest()
    with self.db:
     created=self.db.execute('INSERT OR IGNORE INTO agent_stops VALUES(?,?,?,?)',(identity,agent,row.get('name') or agent,time.time())).rowcount
     if created:self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT ?,id,'pending' FROM push_devices WHERE enabled=1",(identity,))
    if created:self.ready.set()
  self.reply_seen={key:value for key,value in self.reply_seen.items() if key in active}
 def enqueue_badge(self,count):
  identity='badge:'+secrets.token_hex(16)
  with self.db:
   self.db.execute("UPDATE push_deliveries SET state='cancelled' WHERE state='pending' AND event LIKE 'badge:%'")
   self.db.execute('INSERT INTO agent_stops VALUES(?,?,?,?)',(identity,'__badge__','Conversation badge',time.time()))
   self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT ?,id,'pending' FROM push_devices WHERE enabled=1",(identity,))
  self.ready.set()
 def send(self,config,device,event):
  if not event[0].startswith(('fb:','badge:','reply:')) and not self.stop_alert_enabled(event[1]):return 'cancelled'
  if not event[0].startswith(('fb:','badge:','reply:')) and (self.activity.get(event[1]) is not False or self.stop_events.get(event[1])!=event[0]):return "cancelled"
  id,owner,token,environment=device[:4];topic=device[4] if len(device)>4 else 'pictures.influx.vmfactory.mobile';identity,agent,name,at=event
  try:allowed=json.loads(Path(config.get('owner_hashes','/etc/dots-hub/device-hashes.json')).read_text())
  except (OSError,ValueError):return 'retry'
  if owner not in allowed:return 'revoked'
  host='api.sandbox.push.apple.com' if environment=='sandbox' else 'api.push.apple.com'
  payload=self.payload(event)
  lines={'url':'https://'+host+'/3/device/'+token,'request':'POST','header':['authorization: bearer '+self.token(config),'apns-topic: '+topic,'apns-push-type: alert','apns-priority: 10','apns-expiration: '+str(int(at)+3600),'apns-collapse-id: '+('crew-badge' if identity.startswith('badge:') else identity)],'data':json.dumps(payload,separators=(',',':')),'write-out':'\n%{http_code}'}
  text='\n'.join(k+' = '+json.dumps(v) for k,value in lines.items() for v in (value if isinstance(value,list) else [value]))
  r=subprocess.run(['curl','--http2','--silent','--show-error','--max-time','10','--config','-'],input=text,capture_output=True,text=True,timeout=15)
  code=r.stdout.strip().split('\n')[-1]
  if r.returncode or code in ('429','500','503'):return 'retry'
  if code=='200':return 'sent'
  if code=='410' or 'BadDeviceToken' in r.stdout or 'Unregistered' in r.stdout:
   return 'invalid-device'
  return 'provider-error'
 async def run(self):
  self.ready.set()
  while True:
   delay=max(0,min(row[4] for row in self.stops.values())-self.clock()) if self.stops else None
   try:await asyncio.wait_for(self.ready.wait(),timeout=delay)
   except asyncio.TimeoutError:pass
   self.ready.clear();self.flush_stops()
   if not self.config.is_file():continue
   try:config=json.loads(self.config.read_text())
   except (OSError,ValueError):continue
   rows=self.db.execute("SELECT e.id,e.agent,e.name,e.at,d.id,d.owner_hash,d.token,d.environment,p.attempts,d.topic FROM push_deliveries p JOIN agent_stops e ON e.id=p.event JOIN push_devices d ON d.id=p.device WHERE p.state='pending' AND d.enabled=1 ORDER BY e.at LIMIT 100").fetchall()
   retry=False
   for row in rows:
    event=row[:4];device=row[4:8]+(row[9],);attempts=row[8]
    if not event[0].startswith(('fb:','badge:','reply:')) and (not self.stop_alert_enabled(event[1]) or self.activity.get(event[1]) is not False or self.stop_events.get(event[1])!=event[0]):state='cancelled'
    elif time.time()-event[3]>3600:state='expired'
    elif attempts>=6:state='failed'
    else:
     try:state=await asyncio.to_thread(self.send,config,device,event)
     except Exception:state='retry'
    with self.db:
     self.db.execute("UPDATE push_deliveries SET state=?,attempts=attempts+1 WHERE event=? AND device=? AND state='pending'",('pending' if state=='retry' else state,event[0],device[0]))
     if state=='invalid-device':self.db.execute('UPDATE push_devices SET enabled=0 WHERE id=?',(device[0],))
    retry=retry or state=='retry'
   if retry:asyncio.get_running_loop().call_later(15,self.ready.set)
