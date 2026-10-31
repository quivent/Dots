#!/usr/bin/env python3
"""Authenticated renderer gateway. Streams the existing world's HTML, modules and assets unchanged."""
import asyncio
import secrets
import time
import ssl
import signal
from aiohttp import web,ClientSession,ClientTimeout,ClientError
UPSTREAM='http://127.0.0.1:18772'
ORIGIN='https://dots.kosmos.institute:8444'
async def authorized(request):
 header=request.headers.get('Authorization','')
 token=header[7:] if header.startswith('Bearer ') else ''
 identity=request.cookies.get('vmfactory_world')
 session=request.app['sessions'].get(identity)
 if not token and session and session['expires']>time.time():token=session['token']
 if not token:return None
 if session and session['token']==token and session['checked']>time.time()-30:return identity
 try:
  async with request.app['http'].get('http://127.0.0.1:18770/v1/health',headers={'Authorization':'Bearer '+token}) as r:
   if r.status!=200 or (await r.json()).get('scope')!='owner':return None
 except Exception:return None
 now=time.time()
 request.app['sessions']={k:v for k,v in request.app['sessions'].items() if v['expires']>now}
 if len(request.app['sessions'])>128:return None
 identity=next((k for k,v in request.app['sessions'].items() if secrets.compare_digest(v['token'],token)),None) or secrets.token_urlsafe(32)
 request.app['sessions'][identity]={'token':token,'expires':now+3600,'checked':now}
 return identity
async def proxy(request):
 if request.headers.get('Origin') not in (None,ORIGIN):raise web.HTTPForbidden()
 identity=await authorized(request)
 if not identity:raise web.HTTPUnauthorized(text='Open this world from your paired VMFactory app.')
 if request.method not in ('GET','HEAD','POST'):raise web.HTTPMethodNotAllowed(request.method,['GET','HEAD','POST'])
 if request.method=='POST' and not request.path.startswith(('/__fmvision/','/api/')):raise web.HTTPForbidden()
 headers={k:v for k,v in request.headers.items() if k.lower() in ('accept','accept-encoding','content-type','range','if-none-match','if-modified-since')}
 headers['Host']='127.0.0.1:5176'
 body=await request.read() if request.method=='POST' else None
 try:
  async with request.app['http'].request(request.method,UPSTREAM+request.raw_path,headers=headers,data=body,allow_redirects=False) as upstream:
   headers={k:v for k,v in upstream.headers.items() if k.lower() in ('content-type','content-length','content-encoding','cache-control','etag','last-modified','accept-ranges','content-range','cross-origin-opener-policy','cross-origin-embedder-policy','cross-origin-resource-policy','location')}
   headers['Referrer-Policy']='same-origin'
   response=web.StreamResponse(status=upstream.status,headers=headers)
   if upstream.status==200 and 'Content-Encoding' not in headers and any(value in headers.get('Content-Type','') for value in ('text/','javascript','json','wasm')):response.enable_compression()
   response.set_cookie('vmfactory_world',identity,secure=True,httponly=True,samesite='Strict',max_age=3600)
   await response.prepare(request)
   async for chunk in upstream.content.iter_chunked(128*1024):await response.write(chunk)
   await response.write_eof();return response
 except (ClientError,ConnectionError,asyncio.TimeoutError):raise web.HTTPServiceUnavailable(text='The studio renderer is reconnecting. Try opening this world again.')
async def lifecycle(app):
 app['http']=ClientSession(timeout=ClientTimeout(total=None,sock_connect=8,sock_read=60),auto_decompress=False)
 yield
 await app['http'].close()
app=web.Application(client_max_size=1024*1024);app['sessions']={};app.cleanup_ctx.append(lifecycle);app.router.add_route('*','/{path:.*}',proxy)
if __name__=='__main__':
 context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
 base='/var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/dots.kosmos.institute/dots.kosmos.institute'
 def reload_certificate(*args):context.load_cert_chain(base+'.crt',base+'.key')
 reload_certificate();signal.signal(signal.SIGHUP,reload_certificate)
 web.run_app(app,host='0.0.0.0',port=8444,ssl_context=context,access_log=None,print=None,shutdown_timeout=2)
