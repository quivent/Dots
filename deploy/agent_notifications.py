"""Transition-triggered iOS alerts. No model calls, chat messages or activity polling."""
import asyncio,base64,hashlib,json,re,secrets,subprocess,time
from pathlib import Path
class AgentNotifications:
 def __init__(self,db,config=Path('/etc/dots-hub/vmfactory-apns.json')):
  self.db=db;self.config=Path(config);self.activity={};self.ready=asyncio.Event();self.jwt=None;self.jwt_time=0
  db.executescript('CREATE TABLE IF NOT EXISTS push_devices(id TEXT PRIMARY KEY,owner_hash TEXT NOT NULL,token TEXT NOT NULL,environment TEXT NOT NULL,enabled INTEGER NOT NULL,updated REAL NOT NULL,UNIQUE(token,environment)); CREATE TABLE IF NOT EXISTS agent_stops(id TEXT PRIMARY KEY,agent TEXT NOT NULL,name TEXT NOT NULL,at REAL NOT NULL); CREATE TABLE IF NOT EXISTS push_deliveries(event TEXT,device TEXT,state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(event,device));')
 def register(self,owner,body):
  import uuid
  id=str(uuid.UUID(body['id']));token=body['token'];environment=body.get('environment','sandbox');enabled=body.get('enabled')
  if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{32,512}',token) or environment not in ('sandbox','production') or type(enabled) is not bool:raise ValueError('Invalid push registration')
  digest=hashlib.sha256(owner.encode()).hexdigest()
  existing=self.db.execute('SELECT owner_hash FROM push_devices WHERE id=?',(id,)).fetchone()
  if existing and existing[0]!=digest:raise ValueError('Push installation belongs to another pairing')
  with self.db:self.db.execute('INSERT OR REPLACE INTO push_devices VALUES(?,?,?,?,?,?)',(id,digest,token,environment,int(enabled),time.time()))
  return {'registered':True,'pushConfigured':self.config.is_file()}
 def reset(self,agents):
  for id in agents:self.activity.pop(id,None)
 def observe(self,agents):
  for id,row in agents.items():
   if row.get('activityKnown') is not True:self.activity.pop(id,None);continue
   current=row.get('working')
   if type(current) is not bool:continue
   previous=self.activity.get(id);self.activity[id]=current
   if previous is not True or current is not False:continue
   event=secrets.token_hex(16);name=row.get('name') or ('Maestro' if id=='maestro' else id);now=time.time()
   with self.db:
    self.db.execute('INSERT INTO agent_stops VALUES(?,?,?,?)',(event,id,name,now))
    self.db.execute("INSERT INTO push_deliveries(event,device,state) SELECT ?,id,'pending' FROM push_devices WHERE enabled=1",(event,))
   self.ready.set()
 def token(self,config):
  if self.jwt and time.time()-self.jwt_time<1200:return self.jwt
  from cryptography.hazmat.primitives import hashes,serialization
  from cryptography.hazmat.primitives.asymmetric import ec,utils
  encode=lambda v:base64.urlsafe_b64encode(v).rstrip(b'=').decode()
  self.jwt_time=int(time.time());unsigned=encode(json.dumps({'alg':'ES256','kid':config['key_id']},separators=(',',':')).encode())+'.'+encode(json.dumps({'iss':config['team_id'],'iat':self.jwt_time},separators=(',',':')).encode())
  key=serialization.load_pem_private_key(Path(config['key_path']).read_bytes(),None);r,s=utils.decode_dss_signature(key.sign(unsigned.encode(),ec.ECDSA(hashes.SHA256())))
  self.jwt=unsigned+'.'+encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'));return self.jwt
 def send(self,config,device,event):
  id,owner,token,environment=device;identity,agent,name,at=event
  try:allowed=json.loads(Path(config.get('owner_hashes','/etc/dots-hub/device-hashes.json')).read_text())
  except (OSError,ValueError):return 'retry'
  if owner not in allowed:return 'revoked'
  host='api.sandbox.push.apple.com' if environment=='sandbox' else 'api.push.apple.com'
  payload={'aps':{'alert':{'title':name+' stopped working','body':'Open the conversation to see why.'},'sound':'default','thread-id':'crew-'+agent},'agentId':agent,'eventId':identity}
  lines={'url':'https://'+host+'/3/device/'+token,'request':'POST','header':['authorization: bearer '+self.token(config),'apns-topic: pictures.influx.vmfactory.mobile','apns-push-type: alert','apns-priority: 10','apns-expiration: '+str(int(at)+3600),'apns-collapse-id: '+identity],'data':json.dumps(payload,separators=(',',':')),'write-out':'\n%{http_code}'}
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
   await self.ready.wait();self.ready.clear()
   if not self.config.is_file():continue
   try:config=json.loads(self.config.read_text())
   except (OSError,ValueError):continue
   rows=self.db.execute("SELECT e.id,e.agent,e.name,e.at,d.id,d.owner_hash,d.token,d.environment,p.attempts FROM push_deliveries p JOIN agent_stops e ON e.id=p.event JOIN push_devices d ON d.id=p.device WHERE p.state='pending' AND d.enabled=1 ORDER BY e.at LIMIT 100").fetchall()
   retry=False
   for row in rows:
    event=row[:4];device=row[4:8];attempts=row[8]
    if time.time()-event[3]>3600:state='expired'
    elif attempts>=6:state='failed'
    else:
     try:state=await asyncio.to_thread(self.send,config,device,event)
     except Exception:state='retry'
    with self.db:
     self.db.execute('UPDATE push_deliveries SET state=?,attempts=attempts+1 WHERE event=? AND device=?',('pending' if state=='retry' else state,event[0],device[0]))
     if state=='invalid-device':self.db.execute('UPDATE push_devices SET enabled=0 WHERE id=?',(device[0],))
    retry=retry or state=='retry'
   if retry:asyncio.get_running_loop().call_later(15,self.ready.set)
