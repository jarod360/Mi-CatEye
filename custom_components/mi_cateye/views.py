"""HA-authenticated, fixed-source media routes. No backend control proxy."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
import json
import time

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path

from .helpers import DOMAIN, ASSETS
from .media import MediaError


def runtime_for(hass):
    runtime = hass.data.get(DOMAIN, {}).get("runtime")
    if runtime is None or runtime.closed:
        raise web.HTTPServiceUnavailable(text="门铃服务暂不可用")
    return runtime


class RawView(HomeAssistantView):
    url = "/api/mi_cateye/raw.mp4"
    name = "api:mi_cateye:raw"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        runtime = runtime_for(self.hass)
        codec = request.query.get("codec", "h265")
        if codec not in {"h265", "h264"}:
            raise web.HTTPBadRequest()
        try:
            await runtime.ensure_video()
        except MediaError:
            raise web.HTTPConflict(text="视频尚未启用，请先完成原有猫眼接入的切换") from None
        source = "doorbell_live" if codec == "h265" else "doorbell_compatible"
        upstream = None
        output = web.StreamResponse(headers={"Content-Type": "video/mp4", "Cache-Control": "no-store"})
        try:
            async with asyncio.timeout(180):
                if codec == "h265" and request.remote == runtime.entry.options.get("tv_host") and runtime.raw_prime is not None:
                    task, runtime.raw_prime = runtime.raw_prime, None
                    if runtime.raw_expiry is not None:
                        runtime.raw_expiry.cancel()
                        runtime.raw_expiry = None
                    upstream = await task
                else:
                    upstream = await runtime.client.get(
                        runtime.media.base_url + f"/api/stream.mp4?src={source}&video={codec}",
                        timeout=aiohttp.ClientTimeout(total=None, sock_read=20),
                    )
                if upstream.status != 200:
                    raise web.HTTPBadGateway(text="视频源暂不可用")
                chunk = await upstream.content.read(32768)
                if not chunk:
                    raise web.HTTPBadGateway(text="视频源尚未就绪")
                await output.prepare(request)
                await output.write(chunk)
                async for chunk in upstream.content.iter_chunked(32768):
                    await output.write(chunk)
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, TimeoutError, ConnectionError, RuntimeError):
            if not output.prepared:
                raise web.HTTPBadGateway(text="视频连接暂不可用") from None
        finally:
            if upstream is not None:
                upstream.close()
        if output.prepared:
            with suppress(ConnectionError, RuntimeError):
                await output.write_eof()
        return output


class MseView(HomeAssistantView):
    url = "/api/mi_cateye/mse"
    name = "api:mi_cateye:mse"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        runtime = runtime_for(self.hass)
        try:
            await runtime.ensure_video()
        except MediaError:
            raise web.HTTPConflict(text="视频尚未启用") from None
        output = web.WebSocketResponse(heartbeat=15, max_msg_size=1024)
        await output.prepare(request)
        tasks = []
        try:
            async with asyncio.timeout(180):
                async with runtime.client.ws_connect(runtime.media.base_url + "/api/ws?src=doorbell_live",
                                                      heartbeat=15, max_msg_size=16 * 1024 * 1024) as upstream:
                    await upstream.send_json({"type": "mse", "value": "hvc1.1.6.L153.B0"})

                    async def relay():
                        async for message in upstream:
                            if message.type == aiohttp.WSMsgType.BINARY:
                                await output.send_bytes(message.data)
                            elif message.type == aiohttp.WSMsgType.TEXT:
                                value = json.loads(message.data)
                                if value.get("type") == "mse" and isinstance(value.get("value"), str):
                                    await output.send_json({"type": "mse", "value": value["value"][:180]})
                                elif value.get("type") == "error":
                                    await output.send_json({"type": "error", "value": "Stream unavailable"})
                                    return

                    async def watch_client():
                        async for message in output:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                continue
                            with suppress(ValueError, TypeError, AttributeError):
                                value = json.loads(message.data)
                                first = value.get("first_frame_ms")
                                if value.get("type") == "stats" and type(first) is int and 0 <= first <= 180000:
                                    runtime.data["phone_first_frame_ms"] = first
                            # Never forward client messages to go2rtc.

                    tasks = [asyncio.create_task(relay()), asyncio.create_task(watch_client())]
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except (aiohttp.ClientError, TimeoutError, ConnectionError, ValueError, RuntimeError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            with suppress(ConnectionError, RuntimeError):
                await output.close()
        return output


class PlayerView(HomeAssistantView):
    url = "/api/mi_cateye/player"
    name = "api:mi_cateye:player"
    requires_auth = True

    def __init__(self, hass, template):
        self.hass, self.template = hass, template

    async def get(self, request):
        runtime_for(self.hass)
        signed = async_sign_path(self.hass, "/api/mi_cateye/mse", timedelta(minutes=3), use_content_user=True)
        return web.Response(text=self.template.replace("__SOCKET__", json.dumps(signed)), content_type="text/html",
                            headers={"Cache-Control": "no-store"})


class PanelScriptView(HomeAssistantView):
    url = "/api/mi_cateye/phone-panel.js"
    name = "api:mi_cateye:panel-script"
    requires_auth = False

    async def get(self, request):
        return web.FileResponse(ASSETS / "phone-panel.js", headers={"Content-Type": "application/javascript", "Cache-Control": "no-store"})


class VoiceView(HomeAssistantView):
    url = "/api/mi_cateye/visitor.wav"
    name = "api:mi_cateye:voice"
    requires_auth = True

    async def get(self, request):
        return web.FileResponse(ASSETS / "visitor.wav", headers={"Content-Type": "audio/wav", "Cache-Control": "no-store"})


class CaptchaView(HomeAssistantView):
    url = "/api/mi_cateye/captcha/{nonce}"
    name = "api:mi_cateye:captcha"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request, nonce):
        item = self.hass.data.get(DOMAIN, {}).get("captchas", {}).get(nonce)
        if item is None or item[0] < time.monotonic():
            raise web.HTTPNotFound()
        return web.Response(body=item[1], content_type=item[2], headers={"Cache-Control": "no-store"})
