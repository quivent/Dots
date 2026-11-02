"""@purpose Recover/capture only explicit public user-input questions for the durable inbox.
@owns Question allowlist and connection-bound resolution map; never publishes arbitrary tool arguments or outputs.
"""
import hashlib
import json
import math
import uuid

def public_questions(agent,session,turn,item,questions,source='native',created=None,asynchronous=False):
    if not all(isinstance(x,str) and x and len(x.encode())<=1024 for x in (agent,session,turn,item)) or not isinstance(questions,list) or len(questions)>32:return []
    result=[]
    for index,q in enumerate(questions):
        if not isinstance(q,dict) or type(q.get('isSecret',False)) is not bool or q.get('isSecret',False):continue
        text=q.get('title') if asynchronous else q.get('question')
        if not isinstance(text,str) or not text.strip() or len(text.encode())>32000:continue
        qid=q.get('id',str(index)) if asynchronous else q.get('id')
        if not isinstance(qid,str) or len(qid.encode())>1024:continue
        options=q.get('options') or []
        if not isinstance(options,list) or len(options)>32:continue
        clean=[];valid=True
        for option in options:
            if isinstance(option,str) and asynchronous:option={'label':option,'description':''}
            if not isinstance(option,dict) or not isinstance(option.get('label'),str) or not option['label'] or len(option['label'].encode())>1024 or not isinstance(option.get('description',''),str) or len(option.get('description','').encode())>4096:valid=False;break
            clean.append({'label':option['label'],'description':option.get('description','')})
        if not valid:continue
        key=hashlib.sha256(json.dumps([session,turn,item,qid],separators=(',',':')).encode()).hexdigest()
        body={'clientRequestId':key,'agentId':agent,'nativeSessionId':str(uuid.UUID(session)),'turnId':turn,'itemId':item,'questionId':qid,'question':text,'subject':'Feedback requested','source':source,'options':clean}
        if type(created) in (int,float) and math.isfinite(created) and 0<created<=64092211200:body['sourceCreatedAt']=created
        result.append(body)
    return result

class FeedbackCapture:
    def __init__(self,client):self.client=client;self.pending={}
    def observe(self,message,connection):
        if not isinstance(message,dict) or not isinstance(message.get('params'),dict):return
        params=message['params'];thread=params.get('threadId')
        agent=next((key for key,entry in self.client.entries.items() if entry['thread_id']==thread),None)
        if not agent:return
        if message.get('method')=='serverRequest/resolved':
            request=params.get('requestId')
            if type(request) not in (str,int):return
            for key in self.pending.pop((connection,type(request).__name__,str(request)),[]):self.client.resolve(key)
        elif message.get('method')=='item/tool/requestUserInput' and type(message.get('id')) in (str,int) and type(params.get('isBlocking')) is bool:
            rows=public_questions(agent,thread,params.get('turnId'),params.get('itemId'),params.get('questions'))
            ids=[self.client.enqueue(row) for row in rows]
            self.pending[(connection,type(message['id']).__name__,str(message['id']))]=ids
    def end(self,connection):self.pending={key:value for key,value in self.pending.items() if key[0]!=connection}
    def recover(self,agent,entries):
        session=self.client.entries[agent]['thread_id'];count=0
        for entry in entries:
            if not isinstance(entry,dict):continue
            item=entry.get('item',{});turn=entry.get('turnId')
            if not isinstance(item,dict) or item.get('type')!='dynamicToolCall':continue
            tool=item.get('tool');namespace=item.get('namespace')
            if namespace not in (None,'functions'):continue
            if tool not in ('request_user_input_async','functions.request_user_input_async','request_user_input','functions.request_user_input'):continue
            args=item.get('arguments')
            if isinstance(args,str):
                if len(args.encode())>65536:continue
                try:args=json.loads(args)
                except ValueError:continue
            if not isinstance(args,dict):continue
            created=entry.get('startedAtMs');created=created/1000 if type(created) in (int,float) else None
            for body in public_questions(agent,session,turn,item.get('id'),args.get('questions'),source='recovered',created=created,asynchronous=tool.endswith('_async')):
                self.client.enqueue(body);count+=1
        return count
