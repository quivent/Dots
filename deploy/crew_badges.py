"""Owner-only conversation attention: durable exact-session read markers, never activity inference."""
import hashlib
import json
import uuid
import math
import re


def native(value):
    try:return str(uuid.UUID(value))
    except (ValueError,TypeError,AttributeError):return None


class CrewBadges:
    def __init__(self, db):
        self.db=db
        db.execute('CREATE TABLE IF NOT EXISTS crew_read_markers(agent TEXT,session TEXT,message TEXT,PRIMARY KEY(agent,session,message))')
        db.commit()

    @staticmethod
    def members(agents, roster):
        result={}
        for row in roster.get('crew',[]):
            identity=row.get('id');session=native(row.get('sessionId'))
            if not isinstance(identity,str) or not session or row.get('lifecycle') in ('historical','revoked','retired','on-hold','held') or row.get('revoked') is True:continue
            agent=agents.get(identity,{})
            if native(agent.get('nativeSessionId'))!=session:continue
            result[identity]=(session,agent)
        return result

    @staticmethod
    def incoming(agent):
        return {row['id'] for row in agent.get('history',{}).get('items',[])
                if isinstance(row.get('id'),str) and len(row['id'])<=256
                and row.get('role')=='assistant' and row.get('sender_is_self') is not True
                and isinstance(row.get('content',{}).get('text'),str) and row['content']['text'].strip()}

    @staticmethod
    def explicit_attention(value,identity,session):
        if not isinstance(value,dict) or value.get('schema')!='vmfactory.attention/1' or value.get('agentId')!=identity or native(value.get('nativeSessionId'))!=session:return False
        events=value.get('events')
        if not isinstance(events,list) or len(events)>2048:return False
        for row in events:
            if not isinstance(row,dict) or row.get('status')!='recorded' or row.get('agentId')!=identity or native(row.get('nativeSessionId'))!=session:continue
            kind=row.get('kind')
            if kind not in ('question','blocker','submission','verificationFailed','worldReady'):continue
            if not isinstance(row.get('id'),str) or not re.fullmatch('[a-fA-F0-9]{64}',row['id']):continue
            when=row.get('occurredAt');text=row.get('question' if kind=='question' else 'message')
            if type(when) not in (float,int) or not math.isfinite(when) or when<=0 or not isinstance(text,str) or not text.strip() or len(text.encode())>32000:continue
            if 'isSecret' in row and row['isSecret'] is not False:continue
            if kind=='question' and (type(row.get('isBlocking')) is not bool or not all(isinstance(row.get(k),str) and row[k].strip() for k in ('turnId','itemId','questionId'))):continue
            return True
        return False

    def summary(self, agents, roster):
        conversations={}
        opened={}
        for (payload,) in self.db.execute("SELECT payload FROM feedback_requests WHERE json_extract(payload,'$.state')='open'"):
            row=json.loads(payload);opened.setdefault((row['agentId'],native(row['nativeSessionId'])),set()).add(row['id'])
        for identity,(session,agent) in self.members(agents,roster).items():
            seen={r[0] for r in self.db.execute('SELECT message FROM crew_read_markers WHERE agent=? AND session=?',(identity,session))}
            unread=bool(self.incoming(agent)-seen)
            legacy=self.explicit_attention(agent.get('attention'),identity,session)
            response=bool(opened.get((identity,session))) or legacy
            conversations[identity]={'nativeSessionId':session,'unread':unread,'requiresResponse':response,'needsAttention':unread or response}
        count=sum(row['needsAttention'] for row in conversations.values())
        encoded=json.dumps(conversations,sort_keys=True,separators=(',',':'))
        return {'schema':'vmfactory.conversation-badges/1','revision':hashlib.sha256(encoded.encode()).hexdigest(),
                'count':count,'conversations':conversations,'countMeaning':'Active conversations with unread assistant messages or explicit unresolved attention; one per conversation'}

    def mark_read(self, body, agents, roster):
        if not isinstance(body,dict) or set(body)!={'agentId','nativeSessionId','messageIds'}:raise ValueError('Invalid read marker')
        identity=body['agentId'];session=native(body['nativeSessionId']);members=self.members(agents,roster)
        if identity not in members or not session or members[identity][0]!=session:raise ValueError('Original conversation session is unavailable')
        messages=body['messageIds']
        if not isinstance(messages,list) or len(messages)>512 or not all(isinstance(i,str) and 0<len(i)<=256 for i in messages):raise ValueError('Invalid visible message identities')
        known=self.incoming(members[identity][1])
        if not set(messages)<=known:raise ValueError('Read identities do not belong to published assistant history')
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO crew_read_markers VALUES(?,?,?)',[(identity,session,i) for i in messages])
        return self.summary(agents,roster)
