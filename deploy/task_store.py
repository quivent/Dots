"""@purpose Store the authored task plan and observed worker events in SQLite.
@owns Relational tasks/dependencies/references and provenance, never infers activity.
"""
import hashlib
import json
import time

FIELDS=('title','status','owner','next','acceptance','workstream')
class TaskStore:
 def __init__(self,db):
  self.db=db
  db.executescript('''
  CREATE TABLE IF NOT EXISTS task_plan(id INTEGER PRIMARY KEY CHECK(id=1),metadata TEXT NOT NULL,received REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,title TEXT,status TEXT,owner TEXT,next TEXT,acceptance TEXT,workstream TEXT,position INTEGER NOT NULL,extras TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS task_dependencies(task TEXT NOT NULL,dependency TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(task,dependency));
  CREATE TABLE IF NOT EXISTS task_references(task TEXT NOT NULL,reference TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(task,position));
  CREATE TABLE IF NOT EXISTS worker_current(id INTEGER PRIMARY KEY CHECK(id=1),task TEXT,phase TEXT,updated TEXT,extras TEXT NOT NULL,received REAL NOT NULL);
  CREATE TABLE IF NOT EXISTS worker_window(position INTEGER PRIMARY KEY,event TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS worker_events(id TEXT PRIMARY KEY,task TEXT,phase TEXT,observed TEXT,summary TEXT,extras TEXT NOT NULL,received REAL NOT NULL);
  ''')
 def save_tasks(self,plan):
  rows=plan.get('tasks')
  if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):raise ValueError('Invalid task plan')
  ids=[r['id'] for r in rows]
  if len(set(ids))!=len(ids):raise ValueError('Duplicate task identities')
  for r in rows:
   if any(d not in ids or d==r['id'] for d in r.get('dependsOn',[])):raise ValueError('Invalid task dependency')
  self.db.execute('INSERT OR REPLACE INTO task_plan VALUES(1,?,?)',(json.dumps({k:v for k,v in plan.items() if k!='tasks'}),time.time()))
  for table in ('tasks','task_dependencies','task_references'):self.db.execute('DELETE FROM '+table)
  for position,row in enumerate(rows):
   extras={k:v for k,v in row.items() if k not in ('id','dependsOn','references',*FIELDS)}
   self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',(row['id'],*(row.get(k) for k in FIELDS),position,json.dumps(extras)))
   self.db.executemany('INSERT INTO task_dependencies VALUES(?,?,?)',[(row['id'],d,i) for i,d in enumerate(row.get('dependsOn',[]))])
   self.db.executemany('INSERT INTO task_references VALUES(?,?,?)',[(row['id'],r,i) for i,r in enumerate(row.get('references',[]))])
 def tasks(self):
  plan=self.db.execute('SELECT metadata FROM task_plan WHERE id=1').fetchone()
  if not plan:return None
  rows=[]
  for row in self.db.execute('SELECT id,title,status,owner,next,acceptance,workstream,extras FROM tasks ORDER BY position'):
   task={'id':row[0],**{k:v for k,v in zip(FIELDS,row[1:7]) if v is not None},**json.loads(row[7])}
   task['dependsOn']=[r[0] for r in self.db.execute('SELECT dependency FROM task_dependencies WHERE task=? ORDER BY position',(row[0],))]
   task['references']=[r[0] for r in self.db.execute('SELECT reference FROM task_references WHERE task=? ORDER BY position',(row[0],))]
   rows.append(task)
  return dict(json.loads(plan[0]),tasks=rows)
 def save_worker(self,worker):
  extras={k:v for k,v in worker.items() if k not in ('task','phase','updated') and (k!='events' or not v)}
  self.db.execute('INSERT OR REPLACE INTO worker_current VALUES(1,?,?,?,?,?)',(worker.get('task'),worker.get('phase'),worker.get('updated'),json.dumps(extras),time.time()))
  self.db.execute('DELETE FROM worker_window')
  for position,event in enumerate(worker.get('events',[])):
   digest=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
   self.db.execute('INSERT INTO worker_window VALUES(?,?)',(position,digest))
   extra={k:v for k,v in event.items() if k not in ('task','phase','at','summary')}
   self.db.execute('INSERT OR IGNORE INTO worker_events VALUES(?,?,?,?,?,?,?)',(digest,event.get('task'),event.get('phase'),event.get('at'),event.get('summary'),json.dumps(extra),time.time()))
 def worker(self):
  row=self.db.execute('SELECT task,phase,updated,extras FROM worker_current WHERE id=1').fetchone()
  if not row:return None
  result=dict(json.loads(row[3]),**{k:v for k,v in zip(('task','phase','updated'),row[:3]) if v is not None})
  events=[]
  for task,phase,at,summary,extra in self.db.execute('SELECT e.task,e.phase,e.observed,e.summary,e.extras FROM worker_window w JOIN worker_events e ON e.id=w.event ORDER BY w.position'):
   events.append(dict(json.loads(extra),**{k:v for k,v in zip(('task','phase','at','summary'),(task,phase,at,summary)) if v is not None}))
  if events:result['events']=events
  return result
