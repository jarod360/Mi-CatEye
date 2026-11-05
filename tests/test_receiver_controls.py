import asyncio,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'custom_components'))
from mi_cateye import receivers
class Response:
 def __init__(self,data=None):self.data=data
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 def raise_for_status(self):pass
 async def json(self):return self.data
class Tests(unittest.IsolatedAsyncioTestCase):
 async def test_normal_tv_popup_has_remote_controls_and_keeps_same_video(self):
  sent=[]
  def post(url,**kw):sent.append(kw['json']);return Response()
  runtime=SimpleNamespace(entry=SimpleNamespace(options={'tv_host':'192.168.1.2'}),prime=AsyncMock(),client=SimpleNamespace(post=post,get=lambda *a,**kw:Response({'doorbellTalk':True})))
  with patch.object(receivers,'signed_url',side_effect=lambda r,p,*a:'signed:'+p):await receivers.show_tv(runtime)
  self.assertEqual([b['id'] for b in sent[0]['buttons']],['doorbell-talk','doorbell-reply'])
  self.assertTrue(sent[0]['talkEndpoint'].endswith('?action=authorize'))
  self.assertEqual(sent[0]['media']['video']['width'],640)
  self.assertTrue(sent[0]['media']['video']['muted'])
 async def test_xiaoai_keeps_crop_and_restores_volume(self):
  sent=[];level=25
  def request(method,url,**kwargs):
   nonlocal level
   if '/volume?level=' in url:level=int(url.split('level=')[1].split('&')[0])
   if method=='POST' and url.endswith('/notify'):sent.append(kwargs['json'])
   if url.endswith('/volume'):return Response({'level':level})
   return Response({'lastPopup':{'id':'doorbell-shared-live','firstFrameMs':1},'popups':[{'id':'doorbell-shared-live'}]})
  runtime=SimpleNamespace(entry=SimpleNamespace(options={'xiaoai_host':'192.168.1.3'}),ensure_video=AsyncMock(),client=SimpleNamespace(request=request,get=lambda *a,**kw:Response({'doorbellTalk':True})),xiaoai_lock=asyncio.Lock(),closed=False)
  with patch.object(receivers,'signed_url',side_effect=lambda r,p,*a:'signed:'+p),patch.object(receivers.asyncio,'sleep',new=AsyncMock()):await receivers.show_xiaoai(runtime)
  self.assertEqual(level,25);self.assertEqual(sent[0]['media']['video']['width'],854)
  self.assertEqual(len(sent),1);self.assertTrue(sent[0]['fullscreen'])
  self.assertEqual(len(sent[0]['buttons']),2)
 async def test_legacy_receiver_fallback_keeps_video_without_dead_buttons(self):
  probes=[]
  def get(url,**kw):probes.append(url);return Response({})
  runtime=SimpleNamespace(client=SimpleNamespace(get=get))
  ready=await receivers.supports_talk(runtime,'http://192.168.1.3:7979')
  self.assertFalse(ready);self.assertEqual(len(probes),1)
 async def test_cold_receiver_probe_recovers_once(self):
  calls=[]
  def get(url,**kw):
   calls.append(url)
   if len(calls)==1:raise TimeoutError()
   return Response({'doorbellTalk':True})
  runtime=SimpleNamespace(client=SimpleNamespace(get=get))
  self.assertTrue(await receivers.supports_talk(runtime,'http://192.168.1.3:7980'))
  self.assertEqual(len(calls),2)
if __name__=='__main__':unittest.main()
