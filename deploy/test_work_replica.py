import tempfile
from pathlib import Path
import unittest
from vmfactory_hub import State

class WorkReplicaTests(unittest.TestCase):
 def test_revision_patch_delete_gap_and_recovery(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'hub.sqlite';s=State(path)
   work={'snapshot':True,'revision':4,'updated_epoch':10,'tables':{'tasks':{'T1':{'title':'One'},'T2':{'title':'Two'}},'runs':{},'lanes':{},'workers':{}}}
   s.publish({'work':work})
   patch={'snapshot':False,'base_revision':4,'revision':7,'updated_epoch':12,'changes':{'runs':{'run':{'task_id':'T1','phase':'running'}}},'deletes':{'tasks':['T2']}}
   s.publish({'work':patch});expected=s.data['work']
   self.assertEqual(set(expected['tables']['tasks']),{'T1'})
   with self.assertRaises(ValueError):s.publish({'work':patch})
   self.assertEqual(s.db.execute("select count(*) from records where key='work'").fetchone()[0],0)
   s.close();s=State(path);self.assertEqual(s.data['work'],expected);s.close()
