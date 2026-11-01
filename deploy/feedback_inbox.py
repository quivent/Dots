"""@purpose Persist explicit crew questions before notifying the operator.
@owns Auth-scoped inbox records, retry identities, read/handled state and existing push-queue integration.
No model calls, native answers, chat injection, new daemon or activity inference.
"""
import hashlib
import json
import math
import re
import time
import uuid
from agent_notifications import AgentNotifications

SCHEMA = 'vmfactory.feedback-inbox/1'

class FeedbackConflict(ValueError):
    pass

def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)

def public_text(value, maximum, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise ValueError('Invalid public request text')
    return value

def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value):
        raise ValueError('A stable request or action identity is required')
    return value

def native_id(value):
    if not isinstance(value,str):raise ValueError('A native session UUID is required')
    return str(uuid.UUID(value))

class FeedbackInbox:
    def __init__(self, db):
        self.db = db
        db.executescript('''CREATE TABLE IF NOT EXISTS feedback_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback_requests(id TEXT PRIMARY KEY,agent TEXT NOT NULL,session TEXT NOT NULL,client TEXT NOT NULL,canonical TEXT NOT NULL,payload TEXT NOT NULL,received REAL NOT NULL,UNIQUE(agent,session,client));
        CREATE TABLE IF NOT EXISTS feedback_changes(seq INTEGER PRIMARY KEY AUTOINCREMENT,request TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback_actions(id TEXT PRIMARY KEY,request TEXT NOT NULL,canonical TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS feedback_agent_received ON feedback_requests(agent,received);''')
        with db:
            db.execute("INSERT OR IGNORE INTO feedback_meta VALUES('studio',?)", (str(uuid.uuid4()),))
        self.studio = db.execute("SELECT value FROM feedback_meta WHERE key='studio'").fetchone()[0]

    def get(self, identity):
        row = self.db.execute('SELECT payload FROM feedback_requests WHERE id=?', (identity,)).fetchone()
        if not row:
            raise KeyError('Request not found')
        return json.loads(row[0])

    def summary(self):
        revision = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM feedback_changes').fetchone()[0]
        opened,unseen=self.db.execute("SELECT COALESCE(SUM(json_extract(payload,'$.state')='open'),0), COALESCE(SUM(json_extract(payload,'$.state')='open' AND json_extract(payload,'$.seenAt') IS NULL),0) FROM feedback_requests").fetchone()
        return {'schema': SCHEMA, 'studioId': self.studio, 'revision': revision, 'openCount': opened, 'unseenCount': unseen}

    def _save(self, record):
        cursor = self.db.execute('INSERT INTO feedback_changes(request,payload) VALUES(?,?)', (record['id'], '{}'))
        record = dict(record, revision=cursor.lastrowid)
        payload = compact(record)
        self.db.execute('UPDATE feedback_requests SET payload=? WHERE id=?', (payload, record['id']))
        self.db.execute('UPDATE feedback_changes SET payload=? WHERE seq=?', (payload, record['revision']))
        return record

    def submit(self, body, scope, names=None, on_create=None, now=None):
        allowed = {'clientRequestId','agentId','nativeSessionId','question','subject','category','turnId','itemId','questionId','sourceCreatedAt','source','options'}
        if not isinstance(body, dict) or set(body) - allowed:
            raise ValueError('Unsupported feedback fields; submit public questions only')
        agent = body.get('agentId')
        if not isinstance(scope, dict) or agent not in scope.get('agents', []):
            raise PermissionError('Publisher does not own this agent')
        public_text(agent,64)
        client = identifier(body.get('clientRequestId'))
        session = native_id(body.get('nativeSessionId'))
        source = body.get('source', 'direct')
        if source not in ('direct','native','recovered'):
            raise ValueError('Unknown feedback source')
        created = body.get('sourceCreatedAt')
        if created is not None and (type(created) not in (int,float) or not math.isfinite(created) or created <= 0 or created > 64092211200):
            raise ValueError('Invalid source time')
        options = body.get('options', [])
        if not isinstance(options, list) or len(options) > 32:
            raise ValueError('Invalid public choices')
        clean_options = []
        for option in options:
            if not isinstance(option, dict) or set(option) != {'label','description'} or not isinstance(option['description'],str) or len(option['description'].encode()) > 4096:
                raise ValueError('Invalid public choices')
            clean_options.append({'label':public_text(option['label'],1024),'description':option['description']})
        canonical = {'clientRequestId':client,'agentId':agent,'nativeSessionId':session,
            'question':public_text(body.get('question'),32000),'subject':public_text(body.get('subject','Feedback requested'),240),
            'category':public_text(body.get('category','feedback'),120),'source':source,'sourceCreatedAt':created,'options':clean_options}
        for key in ('turnId','itemId','questionId'):
            canonical[key] = public_text(body.get(key),1024,optional=True)
        encoded = compact(canonical)
        identity = hashlib.sha256(compact([agent,session,client]).encode()).hexdigest()
        existing = self.db.execute('SELECT canonical FROM feedback_requests WHERE id=?',(identity,)).fetchone()
        if existing:
            previous=json.loads(existing[0]);candidate=dict(canonical)
            for key in ('source','sourceCreatedAt'):previous.pop(key,None);candidate.pop(key,None)
            if previous != candidate:
                raise FeedbackConflict('This request identity already has different content; retain it and create a new identity for a new question')
            return self.get(identity), False
        now = time.time() if now is None else now
        if source != 'recovered' and self.db.execute('SELECT count(*) FROM feedback_requests WHERE agent=? AND received>?',(agent,now-60)).fetchone()[0] >= 10:
            raise FeedbackConflict('Feedback submission rate reached; retry the same saved request later')
        name=(names or {}).get(agent)
        if not isinstance(name,str) or not name.strip() or len(name.encode())>128:name=agent
        record = dict(canonical,id=identity,agentName=name,receivedAt=now,
            seenAt=None,state='open',statusVersion=0,resolvedAt=None,resolutionSource=None,studioId=self.studio)
        with self.db:
            self.db.execute('INSERT INTO feedback_requests VALUES(?,?,?,?,?,?,?)',(identity,agent,session,client,encoded,'{}',now))
            record = self._save(record)
            if on_create and source != 'recovered':
                on_create(record)
        return record, True

    def change(self, identity, body, now=None):
        if not isinstance(body, dict) or set(body) - {'actionId','operation','expectedStatusVersion'}:
            raise ValueError('Invalid inbox action')
        action = identifier(body.get('actionId'))
        operation = body.get('operation')
        if operation not in ('seen','handle','reopen'):
            raise ValueError('Unknown inbox action')
        encoded = compact(dict(body,request=identity))
        previous = self.db.execute('SELECT canonical FROM feedback_actions WHERE id=?',(action,)).fetchone()
        if previous:
            if previous[0] != encoded:
                raise FeedbackConflict('Action identity was reused for a different change')
            return self.get(identity)
        record = self.get(identity)
        if operation != 'seen':
            expected = body.get('expectedStatusVersion')
            if type(expected) is not int or expected != record['statusVersion']:
                raise FeedbackConflict('The request status changed on another device; review it before changing it again')
        updated = dict(record)
        now = time.time() if now is None else now
        if operation == 'seen':
            if updated['seenAt'] is None:
                updated['seenAt'] = now
        else:
            state = 'handled' if operation == 'handle' else 'open'
            if state != updated['state']:
                updated.update(state=state,statusVersion=updated['statusVersion']+1,
                    resolvedAt=now if state=='handled' else None,resolutionSource='operator' if state=='handled' else None)
        with self.db:
            self.db.execute('INSERT INTO feedback_actions VALUES(?,?,?)',(action,identity,encoded))
            if updated != record:
                updated = self._save(updated)
        return updated

    def source_resolved(self, identity, scope, session, now=None):
        record = self.get(identity)
        if record['agentId'] not in scope.get('agents',[]) or native_id(session) != record['nativeSessionId']:
            raise PermissionError('Publisher does not own this request source')
        key = 'source:'+identity
        if self.db.execute('SELECT 1 FROM feedback_actions WHERE id=?',(key,)).fetchone():
            return record
        updated = dict(record)
        if updated['state']=='open':
            updated.update(state='handled',statusVersion=updated['statusVersion']+1,
                resolvedAt=time.time() if now is None else now,resolutionSource='source')
        with self.db:
            self.db.execute('INSERT INTO feedback_actions VALUES(?,?,?)',(key,identity,'source-resolved'))
            if updated != record:
                updated=self._save(updated)
        return updated

    def sync(self, after=0, through=None, limit=20):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Invalid inbox cursor')
        summary=self.summary()
        if through is None:through=summary['revision']
        if type(through) is not int or not after <= through <= summary['revision']:
            raise ValueError('Invalid inbox revision range')
        rows=self.db.execute('SELECT seq,payload FROM feedback_changes WHERE seq>? AND seq<=? ORDER BY seq LIMIT ?',(after,through,limit)).fetchall()
        cursor=rows[-1][0] if rows else through
        return {'schema':SCHEMA,'studioId':self.studio,'changes':[json.loads(r[1]) for r in rows],
            'nextAfter':cursor,'throughRevision':through,'hasMore':cursor<through,'summary':summary}

class FeedbackNotifications(AgentNotifications):
    def __init__(self, db, **kwargs):
        super().__init__(db, **kwargs)
        self.inbox=FeedbackInbox(db)
        self.contexts={}
        rows=db.execute("SELECT DISTINCT e.id,f.payload FROM push_deliveries p JOIN agent_stops e ON e.id=p.event JOIN feedback_requests f ON e.id='fb:' || substr(f.id,1,61) WHERE p.state='pending'").fetchall()
        for identity,payload in rows:self.remember(json.loads(payload))

    @staticmethod
    def queue_id(record):return 'fb:'+record['id'][:61]

    def remember(self, record):
        context={key:record[key] for key in ('id','agentId','agentName','nativeSessionId','state','studioId')}
        context['preview']=record['question'][:180]
        self.contexts[self.queue_id(record)]=context

    def enqueue_sql(self, record):
        identity=self.queue_id(record)
        self.db.execute('INSERT OR IGNORE INTO agent_stops VALUES(?,?,?,?)',(identity,record['agentId'],record['agentName'],record['receivedAt']))
        self.db.execute("INSERT OR IGNORE INTO push_deliveries(event,device,state) SELECT ?,id,'pending' FROM push_devices WHERE enabled=1",(identity,))

    def submit_feedback(self, body, scope, names=None):
        record,created=self.inbox.submit(body,scope,names,on_create=self.enqueue_sql)
        self.remember(record)
        if created:self.ready.set()
        return record,created

    def changed_feedback(self, record):
        self.remember(record)
        if record['state'] != 'open':
            with self.db:self.db.execute("UPDATE push_deliveries SET state='handled' WHERE event=? AND state='pending'",(self.queue_id(record),))

    def payload(self, event):
        identity,agent,name,at=event
        if not identity.startswith('fb:'):return super().payload(event)
        record=self.contexts.get(identity)
        if not record or record['state']!='open':raise ValueError('Feedback request is unavailable or handled')
        return {'aps':{'alert':{'title':record['agentName']+' asks for feedback','body':record['preview']},'sound':'default','thread-id':'crew-'+agent,'badge':max(0,int(self.badge_count())) if hasattr(self,'badge_count') else 0},
            'kind':'feedback','agentId':record['agentId'],'eventId':record['id'],
            'nativeSessionId':record['nativeSessionId'],'studioId':record['studioId']}

    def send(self,config,device,event):
        if event[0].startswith('fb:'):
            record=self.contexts.get(event[0])
            if not record:return 'retry'
            if record['state']!='open':return 'handled'
        return super().send(config,device,event)
