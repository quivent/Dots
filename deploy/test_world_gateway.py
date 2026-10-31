import unittest
from unittest.mock import patch,AsyncMock
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
import world_gateway as gateway
class GatewayTests(unittest.IsolatedAsyncioTestCase):
 async def test_owner_renderer_stream_preserves_modules_without_forwarding_credentials(self):
  async def asset(request):
   self.assertNotIn('Authorization',request.headers)
   self.assertNotIn('Cookie',request.headers)
   return web.Response(body=b'export const ready=true;',content_type='text/javascript')
  upstream=web.Application();upstream.router.add_get('/world.js',asset)
  server=TestServer(upstream);await server.start_server()
  app=web.Application();app['sessions']={};app.cleanup_ctx.append(gateway.lifecycle);app.router.add_route('*','/{path:.*}',gateway.proxy)
  client=TestClient(TestServer(app));await client.start_server()
  try:
   with patch.object(gateway,'UPSTREAM',str(server.make_url('')).rstrip('/')),patch.object(gateway,'authorized',new=AsyncMock(return_value='opaque-session')):
    response=await client.get('/world.js',headers={'Authorization':'Bearer private-device-token'})
    self.assertEqual(response.status,200);self.assertEqual(await response.text(),'export const ready=true;')
    self.assertTrue(response.cookies['vmfactory_world']['httponly']);self.assertTrue(response.cookies['vmfactory_world']['secure'])
    self.assertEqual((await client.post('/world.js',data=b'write')).status,403)
    self.assertEqual((await client.get('/world.js',headers={'Origin':'https://unrelated.test'})).status,403)
   with patch.object(gateway,'authorized',new=AsyncMock(return_value=None)):
    self.assertEqual((await client.get('/world.js')).status,401)
  finally:await client.close();await server.close()
