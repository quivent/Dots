import unittest
from crew_connector import working_status
class AgentActivityTests(unittest.TestCase):
 def test_running_idle_waiting_and_unknown_are_distinct(self):
  self.assertTrue(working_status({'type':'active','activeFlags':[]})['working'])
  self.assertFalse(working_status({'type':'idle'})['working'])
  for flag in ['waitingOnApproval','waitingOnUserInput']:
   self.assertFalse(working_status({'type':'active','activeFlags':[flag]})['working'])
  self.assertFalse(working_status(None)['activityKnown'])
