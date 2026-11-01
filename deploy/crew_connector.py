#!/usr/bin/env python3
"""@purpose Join existing, explicitly shared Codex workers to the studio hub.
@owns Outbound authenticated WebSockets and native visible-chat observation.
No agent is created, no configuration is changed, no input is replayed.
Run from a Dots checkout with websocket-client installed.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import struct
import sys
import threading
import time
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import websocket
from cli.local_codex import LocalCodexBridge, DaemonRPC, PREFIX
from crew_work_report import read_report

def working_status(status):
 if not isinstance(status,dict):return {'working':False,'activityKnown':False,'activityObservedAt':time.time()}
 kind=status.get('type');flags=status.get('activeFlags',[])
 return {'working':kind=='active' and not any(f in ('waitingOnApproval','waitingOnUserInput') for f in flags),'activityKnown':kind in ('active','idle','notLoaded','systemError'),'activityObservedAt':time.time()}

class Connector:
 def __init__(self,path):
  path=Path(path)
  if path.is_symlink() or path.stat().st_mode & 0o077:raise ValueError('Connector configuration must be private (0600)')
  self.spec=json.loads(path.read_text())
  if urlparse(self.spec['url']).scheme!='wss':raise ValueError('Use an authenticated WSS studio hub')
  self.entries={e['id']:e for e in self.spec['agents']}
  if not self.entries or len(self.entries)!=len(self.spec['agents']):raise ValueError('Unique agent identities required')
  self.bridge=LocalCodexBridge([{'thread_id':e['thread_id'],'name':e['name']} for e in self.entries.values()],path.with_suffix('.sqlite'),DaemonRPC(Path(self.spec.get('codex_home',str(Path.home()/'.codex'))).expanduser()))
  self.socket=None;self.lock=threading.Lock();self.refresh=threading.Event()
 def send(self,value):
  with self.lock:
   if not self.socket:raise ConnectionError('Hub disconnected')
   self.socket.send(json.dumps(value,separators=(',',':')))
 def history(self):
  while True:
   self.refresh.wait();self.refresh.clear()
   for identity,entry in self.entries.items():
    try:
     with self.bridge.rpc.connection() as call:
      loaded=entry['thread_id'] in call('thread/loaded/list',{})['data']
      activity=working_status(call('thread/read',{'threadId':entry['thread_id'],'includeTurns':False})['thread'].get('status'))
     history=self.bridge.request('GET','/messaging/rooms/'+PREFIX+entry['thread_id']+'/messages',{},None)
     report=read_report(Path(self.spec.get('work_reports','/workspace/FMVisual/telemetry')),identity)
     self.send({'type':'publish','changes':{'agents':{identity:{'id':identity,'name':entry['name'],'nativeSessionId':entry['thread_id'],'server':self.spec['server'],'sessionLoaded':loaded,**activity,'capabilities':{'inspect':True},'workReport':report,'history':history}}}})
    except Exception:pass # Last-good central history survives host outages.
 def observe(self):
  delay=1
  while True:
   ws=None
   try:
    sock=socket.socket(socket.AF_UNIX);sock.settimeout(10);sock.connect(str(self.bridge.rpc.path))
    ws=websocket.create_connection('ws://localhost/',socket=sock,suppress_origin=True,timeout=15)
    sequence=0
    def call(method,params):
     nonlocal sequence
     sequence+=1;ws.send(json.dumps({'id':sequence,'method':method,'params':params}))
     while True:
      row=json.loads(ws.recv())
      if 'method' not in row and row.get('id')==sequence:
       if 'error' in row:raise RuntimeError('Native request rejected')
       return row['result']
    call('initialize',{'clientInfo':{'name':'vmfactory-crew','version':'1.0.0'},'capabilities':{'experimentalApi':True}})
    ws.send(json.dumps({'method':'initialized','params':{}}))
    loaded=call('thread/loaded/list',{})['data'];threads={e['thread_id']:i for i,e in self.entries.items()}
    if not set(threads)<=set(loaded):raise RuntimeError('Open the shared sessions on this server first')
    for thread in threads:call('thread/resume',{'threadId':thread,'excludeTurns':True})
    self.refresh.set();delay=1;ws.settimeout(None)
    while True:
     row=json.loads(ws.recv());params=row.get('params',{});identity=threads.get(params.get('threadId'))
     if not identity:continue
     if row.get('method')=='thread/status/changed':self.send({'type':'publish','changes':{'agents':{identity:working_status(params.get('status'))}}})
     elif row.get('method')=='item/agentMessage/delta':self.send({'type':'agentDelta','agentId':identity,'id':params['itemId'],'delta':params['delta']})
     elif row.get('method') in ('turn/started','turn/completed','item/completed'):self.refresh.set()
   except Exception:
    try:self.send({'type':'publish','changes':{'agents':{id:working_status(None) for id in self.entries}}})
    except Exception:pass
    time.sleep(delay);delay=min(15,delay*2)
   finally:
    if ws:ws.close()
 def watch_reports(self):
  if not sys.platform.startswith('linux'):return
  root=Path(self.spec.get('work_reports','/workspace/FMVisual/telemetry'));root.mkdir(parents=True,exist_ok=True)
  libc=ctypes.CDLL(None,use_errno=True);fd=libc.inotify_init1(os.O_CLOEXEC)
  if fd<0:return
  try:
   if libc.inotify_add_watch(fd,os.fsencode(root),0x8|0x80|0x200)<0:return
   while True:
    data=os.read(fd,65536);offset=0
    while offset+16<=len(data):
     _,_,_,length=struct.unpack_from('iIII',data,offset);name=data[offset+16:offset+16+length].split(b'\0',1)[0];offset+=16+length
     if name.endswith(b'.json'):self.refresh.set()
  finally:os.close(fd)
 def request(self,row):
  try:
   entry=self.entries[row['agentId']];operation=row['operation']
   if operation not in ('send','stop','inspect'):raise ValueError('Unsupported operation')
   if operation=='inspect':
    with self.bridge.rpc.connection() as call:
     thread=call('thread/read',{'threadId':entry['thread_id'],'includeTurns':False})['thread']
    result={'agentId':row['agentId'],'threadId':entry['thread_id'],'observedAt':time.time(),'observationId':row['id'],'status':thread.get('status',{}),'workReport':read_report(Path(self.spec.get('work_reports','/workspace/FMVisual/telemetry')),row['agentId'])};status=200
   else:
    path=('/messaging/rooms/' if operation=='send' else '/tbo/')+PREFIX+entry['thread_id']+('/messages' if operation=='send' else '/runtime/pause')
    result=self.bridge.request('POST',path,{},row['body']);status=200
  except Exception as error:
   status=getattr(error,'status',None) or 502;result={'error':str(error).replace('on the Mac','on its server') if status==409 else 'Native request rejected or delivery unconfirmed. No automatic retry was made.'}
  try:self.send({'type':'rpcResult','id':row['id'],'status':status,'body':result})
  except Exception:pass
  self.refresh.set()
 def run(self):
  threading.Thread(target=self.history,daemon=True).start();threading.Thread(target=self.observe,daemon=True).start()
  threading.Thread(target=self.watch_reports,daemon=True).start()
  delay=1
  while True:
   try:
    ws=websocket.create_connection(self.spec['url'],header={'Authorization':'Bearer '+self.spec['token']},suppress_origin=True,timeout=15)
    self.socket=ws;ws.settimeout(None);self.refresh.set();delay=1
    while True:
     row=json.loads(ws.recv())
     if row.get('type')=='request':threading.Thread(target=self.request,args=(row,),daemon=True).start()
   except Exception:pass
   finally:
    self.socket=None
    try:ws.close()
    except Exception:pass
   time.sleep(delay);delay=min(15,delay*2)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('config');args=parser.parse_args();Connector(args.config).run()
