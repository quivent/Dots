"""Partial crew availability must not suppress live observations. No native sockets or turns."""
import ast
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'deploy/crew_connector.py'
tree=ast.parse(path.read_text())
definition=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='subscribe_loaded')
scope={}
exec(compile(ast.fix_missing_locations(ast.Module(body=[definition],type_ignores=[])),str(path),'exec'),scope)

class Subscription(unittest.TestCase):
 def test_unloaded_peer_does_not_block_active_engineer(self):
  calls=[]
  def call(method,params):
   calls.append((method,params))
   return {'data':['live-session']}if method=='thread/loaded/list'else {}
  result=scope['subscribe_loaded'](call,{'engineer':{'thread_id':'live-session'},'legacy':{'thread_id':'unloaded-session'}})
  self.assertEqual(result,{'live-session':'engineer'})
  self.assertEqual(calls,[('thread/loaded/list',{}),('thread/resume',{'threadId':'live-session','excludeTurns':True})])
 def test_no_loaded_sessions_never_resumes_or_starts_one(self):
  def call(method,params):
   self.assertEqual(method,'thread/loaded/list');return {'data':[]}
  self.assertEqual(scope['subscribe_loaded'](call,{'missing':{'thread_id':'unloaded-session'}}),{})

if __name__=='__main__':unittest.main()
