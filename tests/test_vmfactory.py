import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cli.api import ApiError
from cli.vmfactory import factory_request

class FactoryBridgeTests(unittest.TestCase):
 def test_explicit_private_configuration_and_fixed_read_catalog(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);root=base/'project';runtime=root/'runtime/engine/vfactory';runtime.mkdir(parents=True)
   (runtime/'tasks.json').write_text('{"tasks":[]}')
   config=base/'vmfactory.json';config.write_text(json.dumps({'project':str(root)}));config.chmod(0o600)
   with patch('cli.vmfactory.Path.home',return_value=base):
    result=factory_request('GET','/vmfactory/snapshot',{}, {},base)
   self.assertEqual(result['tasks'],{'tasks':[]})
   self.assertEqual(result['schema'],'vmfactory.mobile-snapshot/1')
   for method,path in [('POST','/vmfactory/snapshot'),('GET','/vmfactory/../../auth.json'),('GET','/vmfactory/run')]:
    with self.assertRaises(ValueError):factory_request(method,path,{}, {},base)
   config.chmod(0o644)
   with self.assertRaises(ApiError):factory_request('GET','/vmfactory/snapshot',{}, {},base)
 def test_missing_configuration_does_not_discover_other_projects(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ApiError):factory_request('GET','/vmfactory/snapshot',{}, {},d)
