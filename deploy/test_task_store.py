import json
from pathlib import Path
import tempfile
import unittest
from vmfactory_hub import State

class TaskStoreTests(unittest.TestCase):
 def test_relational_migration_roundtrip_and_atomic_rejection(self):
  plan={'schema':'fmvision.vfactory-tasks/1','updated':'2026-10-31','tasks':[{'id':'one','title':'One','status':'done','owner':'Crew','next':'Verify','acceptance':'Receipt','dependsOn':[],'references':['docs/one'],'note':'preserve'},{'id':'two','title':'Two','status':'next','owner':'Crew','next':'Build','acceptance':'Works','dependsOn':['one'],'references':[]}]}
  worker={'task':'two','phase':'candidate','updated':'2026-10-30T20:00:00Z','events':[{'task':'two','phase':'candidate','at':'2026-10-30T20:00:00Z','summary':'Historical observation'}]}
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'state.sqlite';state=State(path)
   state.publish({'tasks':plan,'worker':worker})
   self.assertEqual(state.db.execute('select count(*) from tasks').fetchone()[0],2)
   self.assertEqual(state.db.execute('select task,dependency from task_dependencies').fetchone(),('two','one'))
   self.assertEqual(state.db.execute("select count(*) from records where key in ('tasks','worker')").fetchone()[0],0)
   bad=json.loads(json.dumps(plan));bad['tasks'][1]['dependsOn']=['missing']
   with self.assertRaises(ValueError):state.publish({'tasks':bad})
   self.assertEqual(state.data['tasks'],plan)
   # Simulate the previous blob layout; reopening migrates without loss.
   state.db.execute('INSERT OR REPLACE INTO records VALUES(?,?)',('tasks',json.dumps(plan)))
   state.db.execute('DELETE FROM task_plan');state.db.commit()
   state.close();state=State(path)
   self.assertEqual(state.data['tasks'],plan);self.assertEqual(state.data['worker'],worker)
   state.publish({'worker':dict(worker,phase='review')})
   self.assertEqual(state.db.execute('select count(*) from worker_events').fetchone()[0],1)
   state.close()
