"""Authenticated fixed-source talk proxy. Audio is relayed and never persisted."""
from __future__ import annotations
import asyncio
import json
import re
import time
import secrets
import logging
import hashlib
from pathlib import Path
from contextlib import suppress
import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from .views import runtime_for

class TalkView(HomeAssistantView):
    url = "/api/mi_cateye/talk"
    name = "api:mi_cateye:talk"
    # Signed HA URLs authenticate GET/HEAD only. Exchange one for a short-lived,
    # talk-only capability; POST never accepts the URL signature as authorization.
    requires_auth = False

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request):
        runtime = runtime_for(self.hass)
        user = request.get("hass_user")
        if user is None:
            raise web.HTTPUnauthorized()
        if request.query.get("action") != "authorize":
            raise web.HTTPBadRequest()
        now = time.monotonic()
        caps = getattr(runtime, "talk_access", {})
        runtime.talk_access = caps = {k:v for k,v in caps.items() if v[1] > now}
        existing = sorted((v[1], k) for k, v in caps.items() if v[0] == user.id)
        for _, old in existing[:-3]:
            caps.pop(old, None)
        if len(caps) >= 128:
            raise web.HTTPTooManyRequests()
        token = secrets.token_hex(32)
        caps[token] = (user.id, now + 180)
        return web.json_response({"access": token}, headers={"Cache-Control": "no-store"})

    async def post(self, request):
        runtime = runtime_for(self.hass)
        user = request.get("hass_user")
        owner = user.id if user is not None else None
        if owner is None:
            access = request.headers.get("X-Talk-Access", "")
            caps = getattr(runtime, "talk_access", {})
            if re.fullmatch(r"[a-f0-9]{64}", access):
                value = caps.get(access)
                if value is not None and value[1] > time.monotonic():
                    owner = value[0]
        if owner is None:
            raise web.HTTPUnauthorized()
        if not runtime.video_enabled or runtime.media.process is None or runtime.media.process.returncode is not None:
            raise web.HTTPConflict(text="请先打开门口视频")
        action = request.query.get("action")
        if action not in {"begin", "audio", "end", "listen", "reply"}:
            raise web.HTTPBadRequest()
        if action == "reply":
            return await self.reply(runtime, request)
        owners = getattr(runtime, "talk_owners", None)
        if owners is None:
            owners = runtime.talk_owners = {}
        now = time.monotonic()
        for key, value in list(owners.items()):
            if value[1] < now:
                owners.pop(key, None)
        session = request.headers.get("X-Talk-Session", "")
        if action != "begin":
            if not re.fullmatch(r"[a-f0-9]{48}", session) or owners.get(session, (None, 0))[0] != owner:
                raise web.HTTPNotFound()
        endpoint = runtime.media.base_url + "/api/doorbell/talk"
        headers = {"X-Talk-Session": session} if session else {}

        async def audio():
            total = 0
            while True:
                async with asyncio.timeout(2):
                    chunk = await request.content.read(480)
                if not chunk:
                    return
                total += len(chunk)
                if total > 480000:
                    raise ValueError("talk_time_limit")
                yield chunk

        if action == "audio":
            if request.content_type != "audio/pcma":
                raise web.HTTPUnsupportedMediaType()
            headers["Content-Type"] = "audio/pcma"
        try:
            async with runtime.client.post(endpoint, params={"action": action}, headers=headers,
                                           data=audio() if action == "audio" else None,
                                           timeout=aiohttp.ClientTimeout(total=65, sock_read=64)) as response:
                if response.status not in {200, 204}:
                    logging.getLogger(__name__).warning("Talk backend action=%s status=%s", action, response.status)
                    if action == "begin" and response.status == 409:
                        allowed = {"live_video_required", "single_active_producer_required", "live_producer_unavailable", "talk_source_unsupported", "talk_model_unsupported", "talk_already_active", "talk_start_timeout", "talk_start_rejected", "talk_transport_unavailable"}
                        with suppress(ValueError, aiohttp.ContentTypeError):
                            value = await response.json()
                            if isinstance(value, dict) and value.get("error") in allowed:
                                return web.json_response({"error": value["error"]}, status=409, headers={"Cache-Control": "no-store"})
                    if response.status in {400, 404, 409, 415}:
                        return web.Response(status=response.status, text="通话暂不可用", headers={"Cache-Control": "no-store"})
                    raise web.HTTPBadGateway()
                if action == "begin":
                    value = await response.json()
                    token = value.get("session", "")
                    if not re.fullmatch(r"[a-f0-9]{48}", token):
                        raise web.HTTPBadGateway()
                    owners[token] = (owner, time.monotonic() + 61)
                    return web.json_response(value, headers={"Cache-Control": "no-store"})
                if action == "listen":
                    output = web.StreamResponse(headers={"Content-Type": "audio/pcm;rate=8000;channels=1;format=s16le", "Cache-Control": "no-store"})
                    await output.prepare(request)
                    total = 0
                    async for chunk in response.content.iter_chunked(1920):
                        total += len(chunk)
                        if total > 960000:
                            break
                        await output.write(chunk)
                    with suppress(ConnectionError):
                        await output.write_eof()
                    return output
                return web.Response(status=204, headers={"Cache-Control": "no-store"})
        except (aiohttp.ClientError, TimeoutError, ValueError):
            raise web.HTTPBadGateway(text="通话连接已断开") from None
        finally:
            if action in {"audio", "end", "listen"}:
                owners.pop(session, None)
                if action in {"audio", "listen"}:
                    with suppress(aiohttp.ClientError, TimeoutError):
                        async with runtime.client.post(endpoint, params={"action": "end"},
                                                       headers={"X-Talk-Session": session},
                                                       timeout=aiohttp.ClientTimeout(total=4)):
                            pass

    async def reply(self, runtime, request):
        preset = request.headers.get("X-Talk-Preset", "")
        if preset not in {"wait", "parcel", "later"}:
            raise web.HTTPBadRequest()
        directory = Path(__file__).parent / "assets" / "replies"
        def load():
            data = (directory / (preset + ".pcma")).read_bytes()
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if not 0 < len(data) <= 48000 or len(data) % 480 or hashlib.sha256(data).hexdigest() != manifest[preset]["sha256"]:
                raise ValueError("reply_asset_invalid")
            return data
        try:
            audio = await asyncio.to_thread(load)
        except (OSError, ValueError, KeyError):
            raise web.HTTPServiceUnavailable(text="语音回复暂不可用") from None
        endpoint = runtime.media.base_url + "/api/doorbell/talk"
        session = None
        async def frames():
            started = time.monotonic()
            for offset in range(0, len(audio), 480):
                await asyncio.sleep(max(0, started + offset / 8000 - time.monotonic()))
                yield audio[offset:offset + 480]
            await asyncio.sleep(max(0, started + len(audio) / 8000 - time.monotonic()))
        try:
            async with runtime.client.post(endpoint, params={"action":"begin"}, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    raise web.HTTPConflict(text="通话正在进行或视频未就绪")
                session = (await response.json())["session"]
                if not re.fullmatch(r"[a-f0-9]{48}", session):
                    raise ValueError("invalid_session")
            async with runtime.client.post(endpoint, params={"action":"audio"}, headers={"X-Talk-Session":session,"Content-Type":"audio/pcma"}, data=frames(), timeout=aiohttp.ClientTimeout(total=12)) as response:
                if response.status != 204:
                    raise web.HTTPBadGateway(text="语音回复未完成")
            return web.Response(status=204, headers={"Cache-Control":"no-store"})
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError):
            raise web.HTTPBadGateway(text="语音回复连接已断开") from None
        finally:
            if session is not None:
                with suppress(aiohttp.ClientError, TimeoutError):
                    async with runtime.client.post(endpoint, params={"action":"end"}, headers={"X-Talk-Session":session}, timeout=aiohttp.ClientTimeout(total=3)):
                        pass
