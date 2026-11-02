#!/usr/bin/env python3
"""@purpose Submit real public feedback requests through the existing studio hub.
@owns Private retry-safe outbox, scoped HTTPS submission and CLI receipts; never writes to native sessions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlparse

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def private_config(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:raise ValueError('Use a private 0600 connector configuration')
    return json.loads(path.read_text())

class FeedbackClient:
    def __init__(self, config, database=None):
        self.config=Path(config);self.spec=private_config(config)
        url=urlparse(self.spec['url'])
        if url.scheme not in ('https','wss') and not(url.scheme=='http' and url.hostname in ('127.0.0.1','localhost')):raise ValueError('Feedback requires HTTPS')
        if url.username or url.password:raise ValueError('Do not put credentials in the URL')
        self.base=('http' if url.scheme=='http' else 'https')+'://'+url.netloc+'/v1/vmfactory/feedback/requests'
        self.entries={row['id']:row for row in self.spec['agents']}
        path=Path(database) if database else self.config.with_suffix('.feedback.sqlite')
        if path.is_symlink():raise ValueError('Feedback outbox must not be a symlink')
        descriptor=os.open(path,os.O_CREAT|os.O_RDWR,0o600);os.close(descriptor);os.chmod(path,0o600)
        self.db=sqlite3.connect(path,check_same_thread=False);self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,body TEXT NOT NULL,server_id TEXT,resolved INTEGER NOT NULL DEFAULT 0,sent_resolution INTEGER NOT NULL DEFAULT 0,attempted INTEGER NOT NULL DEFAULT 0)');self.db.commit()
        self.lock=threading.RLock();self.ready=threading.Event();self.stop=threading.Event()
        self.opener=build_opener(NoRedirect())

    def enqueue(self, body):
        agent=body.get('agentId')
        if agent not in self.entries:raise ValueError('The connector does not own this agent')
        if not isinstance(body.get('question'),str) or not body['question'].strip() or len(body['question'].encode())>32000:raise ValueError('Use a bounded public question')
        uuid.UUID(body['nativeSessionId'])
        key=hashlib.sha256(json.dumps([agent,body['nativeSessionId'],body['clientRequestId']],separators=(',',':')).encode()).hexdigest()
        encoded=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        with self.lock,self.db:
            existing=self.db.execute('SELECT body FROM outbox WHERE id=?',(key,)).fetchone()
            if not existing:self.db.execute('INSERT INTO outbox(id,body) VALUES(?,?)',(key,encoded))
            else:
                old=json.loads(existing[0]);candidate=dict(body)
                for field in ('source','sourceCreatedAt'):old.pop(field,None);candidate.pop(field,None)
                if old != candidate:raise ValueError('The saved question identity has different content; use a new request identity')
            # Existing source identity is immutable. A recovered copy cannot replace a live request.
        self.ready.set();return key

    def resolve(self,key):
        with self.lock,self.db:self.db.execute('UPDATE outbox SET resolved=1 WHERE id=?',(key,))
        self.ready.set()

    def request(self,path='',body=None):
        url=self.base+path
        if not path and body is not None and self.spec.get('recovery') is True:url=self.base.removesuffix('/requests')+'/recover'
        request=Request(url,headers={'Authorization':'Bearer '+self.spec['token'],'Content-Type':'application/json'},method='POST' if body is not None else 'GET',data=json.dumps(body,separators=(',',':')).encode() if body is not None else None)
        with self.opener.open(request,timeout=15) as response:
            raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('Feedback acknowledgement exceeds its bound')
            return json.loads(raw)

    def flush(self):
        with self.lock:rows=self.db.execute('SELECT id,body,server_id,resolved,sent_resolution,attempted FROM outbox WHERE server_id IS NULL OR(resolved=1 AND sent_resolution=0) LIMIT 20').fetchall()
        for key,encoded,server_id,resolved,sent_resolution,attempted in rows:
            body=json.loads(encoded)
            if server_id is None:
                if resolved and not attempted:
                    body['source']='recovered';encoded=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False)
                with self.lock,self.db:self.db.execute('UPDATE outbox SET attempted=1,body=? WHERE id=?',(encoded,key))
                result=self.request(body=body);record=result.get('record',{})
                if result.get('saved') is not True or record.get('agentId')!=body['agentId'] or record.get('nativeSessionId')!=str(uuid.UUID(body['nativeSessionId'])) or not isinstance(record.get('id'),str):raise ValueError('Feedback acknowledgement has a different source')
                server_id=record['id']
                with self.lock,self.db:self.db.execute('UPDATE outbox SET server_id=? WHERE id=?',(server_id,key))
            if resolved and not sent_resolution:
                self.request('/'+server_id+'/source-resolved',{'nativeSessionId':body['nativeSessionId']})
                with self.lock,self.db:self.db.execute('UPDATE outbox SET sent_resolution=1 WHERE id=?',(key,))
        with self.lock:return self.db.execute('SELECT count(*) FROM outbox WHERE server_id IS NULL OR(resolved=1 AND sent_resolution=0)').fetchone()[0]

    def run(self):
        delay=None
        while not self.stop.is_set():
            self.ready.wait(delay);self.ready.clear()
            if self.stop.is_set():return
            try:pending=self.flush();delay=15 if pending else None
            except Exception:delay=30 # Retry only inbox delivery; never poll native activity or replay agent input.

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    sub=parser.add_subparsers(dest='operation',required=True)
    create=sub.add_parser('create');create.add_argument('--agent',required=True);create.add_argument('--question-file',required=True);create.add_argument('--subject',default='Feedback requested');create.add_argument('--out',required=True)
    send=sub.add_parser('send');send.add_argument('--file',required=True)
    status=sub.add_parser('status');status.add_argument('--id',required=True)
    resolved=sub.add_parser('resolved');resolved.add_argument('--file',required=True)
    args=parser.parse_args();client=FeedbackClient(args.config)
    if args.operation=='create':
        entry=client.entries[args.agent];question=Path(args.question_file).read_text()
        if not question.strip() or len(question.encode())>32000:raise ValueError('Use a public question of at most 32000 UTF-8 bytes')
        body={'clientRequestId':str(uuid.uuid4()),'agentId':args.agent,'nativeSessionId':str(uuid.UUID(entry['thread_id'])),'subject':args.subject,'question':question,'sourceCreatedAt':time.time(),'source':'direct'}
        output=Path(args.out)
        with output.open('x',opener=lambda path,flags:os.open(path,flags,0o600)) as file:json.dump(body,file,ensure_ascii=False)
        print(json.dumps({'savedLocally':True,'file':str(output),'next':'send this exact file; reuse it after an uncertain acknowledgement'}));return
    if args.operation=='status':
        row=client.request('/'+args.id)['record'];print(json.dumps({key:row[key] for key in ['id','state','seenAt','statusVersion']}));return
    body=json.loads(Path(args.file).read_text());key=client.enqueue(body)
    if args.operation=='resolved':client.resolve(key)
    try:
        client.flush()
        with client.lock:row=client.db.execute('SELECT server_id,resolved,sent_resolution FROM outbox WHERE id=?',(key,)).fetchone()
        print(json.dumps({'savedAtHub':row[0] is not None,'id':row[0],'sourceResolutionConfirmed':bool(row[2])}))
    except Exception:
        print(json.dumps({'savedLocally':True,'delivery':'unconfirmed','retry':'send the same saved file; do not create a new request identity'}));raise SystemExit(1)
if __name__=='__main__':main()
