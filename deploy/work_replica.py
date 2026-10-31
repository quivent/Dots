"""Read replica of Maestro's shared task database. Never grants or mutates claims."""
import json
TABLES=('tasks','runs','lanes','workers')
class WorkReplica:
 def __init__(self,db):
  self.db=db
  db.executescript('CREATE TABLE IF NOT EXISTS shared_work_meta(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);'+''.join('CREATE TABLE IF NOT EXISTS shared_work_'+t+'(key TEXT PRIMARY KEY,data TEXT NOT NULL);' for t in TABLES))
 def snapshot(self):
  row=self.db.execute('SELECT data FROM shared_work_meta WHERE id=1').fetchone()
  if not row:return None
  return dict(json.loads(row[0]),tables={t:{k:json.loads(d) for k,d in self.db.execute('SELECT key,data FROM shared_work_'+t)} for t in TABLES})
 def apply(self,message,current):
  if message.get('snapshot',True):
   if not isinstance(message.get('tables'),dict) or set(message['tables'])!=set(TABLES):raise ValueError('Invalid shared snapshot')
   result=dict(message,snapshot=True)
  else:
   if not current or message.get('base_revision')!=current.get('revision') or message.get('revision',-1)<=current.get('revision',0):raise ValueError('Shared revision gap; reconnect for a snapshot')
   result=dict(current,revision=message['revision'],updated_epoch=message['updated_epoch'],tables={t:dict(current['tables'][t]) for t in TABLES})
   if not set(message.get('changes',{}))<=set(TABLES) or not set(message.get('deletes',{}))<=set(TABLES):raise ValueError('Invalid shared table')
   for t,rows in message.get('changes',{}).items():result['tables'][t].update(rows)
   for t,keys in message.get('deletes',{}).items():
    for key in keys:result['tables'][t].pop(key,None)
  for t,rows in result['tables'].items():
   if not isinstance(rows,dict) or any(not isinstance(k,str) or not isinstance(v,dict) for k,v in rows.items()):raise ValueError('Invalid shared records')
  return result
 def save(self,value):
  self.db.execute('INSERT OR REPLACE INTO shared_work_meta VALUES(1,?)',(json.dumps({k:v for k,v in value.items() if k!='tables'}),))
  for t,rows in value['tables'].items():
   known=dict(self.db.execute('SELECT key,data FROM shared_work_'+t))
   for key,row in rows.items():
    data=json.dumps(row,sort_keys=True,separators=(',',':'))
    if known.get(key)!=data:self.db.execute('INSERT OR REPLACE INTO shared_work_'+t+' VALUES(?,?)',(key,data))
   self.db.executemany('DELETE FROM shared_work_'+t+' WHERE key=?',[(k,) for k in set(known)-set(rows)])
