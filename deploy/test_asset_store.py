import hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
from aiohttp.test_utils import TestClient,TestServer
import vmfactory_hub as hub
class AssetTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.client=TestClient(TestServer(hub.application(Path(self.temp.name)/'state.sqlite')))
  self.auth=patch('vmfactory_hub.viewer_authorized',new=AsyncMock(side_effect=lambda r:r.headers.get('Authorization')=='Bearer owner'))
  self.scope=patch('vmfactory_hub.publisher_scope',side_effect=lambda t:{'metadata':True} if t=='publisher' else ({'metadata':False} if t=='crew' else None))
  self.auth.start();self.scope.start();await self.client.start_server()
 async def asyncTearDown(self):
  await self.client.close();self.auth.stop();self.scope.stop();self.temp.cleanup()
 async def test_immutable_upload_integrity_auth_and_recovery(self):
  data=b'original shader and wasm bytes';digest=hashlib.sha256(data).hexdigest();url='/v1/vmfactory/assets/'+digest
  for auth in ['', 'crew','owner']:
   r=await self.client.put(url,data=data,headers={'Authorization':'Bearer '+auth});self.assertEqual(r.status,401)
  r=await self.client.put(url,data=b'tampered',headers={'Authorization':'Bearer publisher'});self.assertEqual(r.status,400)
  r=await self.client.get(url,headers={'Authorization':'Bearer owner'});self.assertEqual(r.status,404)
  r=await self.client.put(url,data=data,headers={'Authorization':'Bearer publisher'});self.assertEqual(r.status,200)
  r=await self.client.get(url);self.assertEqual(r.status,401)
  r=await self.client.get(url,headers={'Authorization':'Bearer owner'});self.assertEqual(await r.read(),data)
  r=await self.client.get(url,headers={'Authorization':'Bearer owner','Range':'bytes=0-7'});self.assertEqual(r.status,206);self.assertEqual(await r.read(),data[:8])
  r=await self.client.put(url,data=b'changed',headers={'Authorization':'Bearer publisher'});self.assertEqual(r.status,400)
  r=await self.client.get(url,headers={'Authorization':'Bearer owner'});self.assertEqual(await r.read(),data)
  self.assertFalse(list((Path(self.temp.name)/'vmfactory-assets').glob('.upload-*')))
