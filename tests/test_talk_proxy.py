import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from aiohttp import web,ClientSession
from aiohttp.test_utils import TestClient,TestServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'custom_components'))
from mi_cateye.talk import TalkView

class Tests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.calls=[];self.token='1'*48;self.busy=False
  async def backend(request):
   action=request.query['action'];self.calls.append(action)
   if action=='begin' and self.busy:return web.Response(status=409)
   if action=='begin':return web.json_response({'session':self.token,'frame_bytes':480,'sample_rate':8000})
   if action=='audio':self.received=await request.read()
   return web.Response(status=204)
  app=web.Application();app.router.add_post('/api/doorbell/talk',backend)
  self.backend=TestServer(app);await self.backend.start_server()
  self.session=ClientSession()
  self.runtime=SimpleNamespace(closed=False,video_enabled=True,media=SimpleNamespace(process=SimpleNamespace(returncode=None),base_url=str(self.backend.make_url('')).rstrip('/')),client=self.session)
  hass=SimpleNamespace(data={'mi_cateye':{'runtime':self.runtime}})
  @web.middleware
  async def auth(request,handler):
   if request.headers.get('X-Test-User')!='none':request['hass_user']=SimpleNamespace(id=request.headers.get('X-Test-User','owner'))
   return await handler(request)
  app=web.Application(middlewares=[auth]);view=TalkView(hass);app.router.add_post('/api/mi_cateye/talk',view.post);app.router.add_get('/api/mi_cateye/talk',view.get)
  self.client=TestClient(TestServer(app));await self.client.start_server()
 async def asyncTearDown(self):
  await self.client.close();await self.session.close();await self.backend.close()
 async def test_short_lived_talk_capability(self):
  r=await self.client.get('/api/mi_cateye/talk?action=authorize',headers={'X-Test-User':'none'});self.assertEqual(r.status,401)
  r=await self.client.get('/api/mi_cateye/talk?action=authorize');self.assertEqual(r.status,200)
  cap=(await r.json())['access'];self.assertEqual(len(cap),64)
  headers={'X-Test-User':'none','X-Talk-Access':cap}
  r=await self.client.post('/api/mi_cateye/talk?action=begin',headers=headers);self.assertEqual(r.status,200)
  session=(await r.json())['session'];headers['X-Talk-Session']=session
  r=await self.client.post('/api/mi_cateye/talk?action=end',headers=headers);self.assertEqual(r.status,204)
  self.runtime.talk_access[cap]=('owner',0)
  r=await self.client.post('/api/mi_cateye/talk?action=begin',headers=headers);self.assertEqual(r.status,401)
 async def test_fixed_reply_is_paced_and_closed(self):
  import time
  started=time.monotonic()
  r=await self.client.post('/api/mi_cateye/talk?action=reply',headers={'X-Talk-Preset':'wait'})
  self.assertEqual(r.status,204);self.assertEqual(self.calls,['begin','audio','end'])
  self.assertGreaterEqual(time.monotonic()-started,len(self.received)/8000-0.05)
  self.assertEqual(len(self.received)%480,0)
 async def test_reply_rejects_unknown_and_does_not_close_other_call(self):
  r=await self.client.post('/api/mi_cateye/talk?action=reply',headers={'X-Talk-Preset':'../secret'})
  self.assertEqual(r.status,400);self.assertEqual(self.calls,[])
  self.busy=True
  r=await self.client.post('/api/mi_cateye/talk?action=reply',headers={'X-Talk-Preset':'wait'})
  self.assertEqual(r.status,409);self.assertEqual(self.calls,['begin'])
 async def test_requires_user_and_active_video(self):
  r=await self.client.post('/api/mi_cateye/talk?action=begin',headers={'X-Test-User':'none'});self.assertEqual(r.status,401)
  self.runtime.video_enabled=False
  r=await self.client.post('/api/mi_cateye/talk?action=begin');self.assertEqual(r.status,409)
  self.assertEqual(self.calls,[])
 async def test_owner_and_content_type_are_checked(self):
  await self.client.post('/api/mi_cateye/talk?action=begin')
  r=await self.client.post('/api/mi_cateye/talk?action=end',headers={'X-Test-User':'other','X-Talk-Session':self.token});self.assertEqual(r.status,404)
  r=await self.client.post('/api/mi_cateye/talk?action=audio',headers={'X-Talk-Session':self.token},data=b'x');self.assertEqual(r.status,415)
  self.assertEqual(self.calls,['begin'])
 async def test_audio_relay_always_ends_and_removes_owner(self):
  await self.client.post('/api/mi_cateye/talk?action=begin')
  audio=b'\xd5'*960
  r=await self.client.post('/api/mi_cateye/talk?action=audio',headers={'X-Talk-Session':self.token,'Content-Type':'audio/pcma'},data=audio)
  self.assertEqual(r.status,204);self.assertEqual(self.received,audio);self.assertEqual(self.calls,['begin','audio','end'])
  self.assertEqual(self.runtime.talk_owners,{})
if __name__=='__main__':unittest.main()
