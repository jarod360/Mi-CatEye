"""Authenticated recording selection and fixed-source playback."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
import re
import logging

import aiohttp
from aiohttp import web
import probatio as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path

from .helpers import ASSETS
from .media import MediaError
from .views import runtime_for


def validate_recording_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("recording_not_found")
    return value


async def backend_request(runtime, method, path, params):
    try:
        await runtime.ensure_video()
        async with runtime.client.request(method, runtime.media.base_url + path, params=params,
                                          timeout=aiohttp.ClientTimeout(total=95)) as response:
            value = await response.json()
            if response.status != 200 or not isinstance(value, dict):
                reason = value.get("error", "unknown") if isinstance(value, dict) else "unknown"
                if isinstance(reason, str) and re.fullmatch(r"[a-z_]{1,60}", reason):
                    logging.getLogger(__name__).warning("Recording preparation failed: %s", reason)
                raise ValueError("recording_unavailable")
            return value
    except (aiohttp.ClientError, TimeoutError, ValueError, MediaError):
        raise ValueError("recording_unavailable") from None


@websocket_api.websocket_command({
    vol.Required("type"): "mi_cateye/recordings_list",
    vol.Required("start"): int,
    vol.Required("end"): int,
    vol.Optional("source", default="cloud"): vol.In(["cloud", "sd"]),
})
@websocket_api.async_response
async def ws_recordings_list(hass, connection, message):
    start, end = message["start"], message["end"]
    if start < 1262304000000 or not 0 < end - start <= 86400001:
        connection.send_error(message["id"], "invalid_time_range", "请选择一天内的录像")
        return
    if message["source"] != "cloud":
        connection.send_error(message["id"], "sd_unavailable", "这台猫眼的 SD 卡录像暂不能远程读取")
        return
    try:
        value = await backend_request(runtime_for(hass), "GET", "/api/doorbell/recordings",
                                      {"start": start, "end": end, "source": "cloud"})
        items = []
        for item in value.get("items", [])[:500]:
            if not isinstance(item, dict):
                continue
            try:
                identity = validate_recording_id(item.get("id"))
                at, duration = item["start"], item["duration"]
                if type(at) is not int or not start <= at < end or type(duration) not in (int, float) or not 0 < duration < 3600:
                    continue
                items.append({"id": identity, "source": "cloud", "start": at, "duration": duration,
                              "event": str(item.get("event", ""))[:40]})
            except (ValueError, KeyError, TypeError):
                continue
        connection.send_result(message["id"], {"items": items, "source": "cloud", "sd_supported": False})
    except (ValueError, web.HTTPException):
        connection.send_error(message["id"], "recording_list_failed", "暂时无法读取录像，请稍后重试")


@websocket_api.websocket_command({
    vol.Required("type"): "mi_cateye/recordings_prepare",
    vol.Required("recording_id"): str,
})
@websocket_api.async_response
async def ws_recordings_prepare(hass, connection, message):
    try:
        identity = validate_recording_id(message["recording_id"])
        await backend_request(runtime_for(hass), "POST", "/api/doorbell/recordings/prepare", {"id": identity})
        path = f"/api/mi_cateye/recordings/{identity}"
        connection.send_result(message["id"], {
            "url": async_sign_path(hass, path, timedelta(minutes=10), use_content_user=True),
            "download_url": async_sign_path(hass, path + "?download=1", timedelta(minutes=10), use_content_user=True),
        })
    except (ValueError, web.HTTPException):
        connection.send_error(message["id"], "recording_prepare_failed", "这段录像暂时无法播放，可能已过期，请选择其它时间")


def register_recording_commands(hass):
    websocket_api.async_register_command(hass, ws_recordings_list)
    websocket_api.async_register_command(hass, ws_recordings_prepare)


class RecordingsScriptView(HomeAssistantView):
    url = "/api/mi_cateye/recordings-panel.js"
    name = "api:mi_cateye:recordings-script"
    requires_auth = False

    async def get(self, request):
        return web.FileResponse(ASSETS / "recordings-panel.js", headers={"Content-Type": "application/javascript", "Cache-Control": "no-store"})


class RecordingView(HomeAssistantView):
    url = "/api/mi_cateye/recordings/{recording_id}"
    name = "api:mi_cateye:recording"
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass

    async def get(self, request, recording_id):
        try:
            identity = validate_recording_id(recording_id)
        except ValueError:
            raise web.HTTPNotFound() from None
        runtime = runtime_for(self.hass)
        headers = {}
        byte_range = request.headers.get("Range", "")
        if byte_range:
            if not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", byte_range):
                raise web.HTTPRequestRangeNotSatisfiable()
            headers["Range"] = byte_range
        output = None
        try:
            async with runtime.client.get(runtime.media.base_url + "/api/doorbell/recordings/clip",
                                           params={"id": identity}, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=180, sock_read=20)) as upstream:
                if upstream.status not in (200, 206):
                    raise web.HTTPNotFound(text="录像已清理，请重新选择片段")
                result_headers = {"Content-Type": "video/mp4", "Cache-Control": "private, no-store"}
                for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
                    if name in upstream.headers:
                        result_headers[name] = upstream.headers[name]
                if request.query.get("download") == "1":
                    result_headers["Content-Disposition"] = 'attachment; filename="doorbell-recording.mp4"'
                output = web.StreamResponse(status=upstream.status, headers=result_headers)
                await output.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):
                    await output.write(chunk)
        except asyncio.CancelledError:
            raise
        except (aiohttp.ClientError, ConnectionError, TimeoutError, RuntimeError):
            if output is None or not output.prepared:
                raise web.HTTPBadGateway(text="录像连接暂不可用") from None
        if output is not None:
            with suppress(ConnectionError, RuntimeError):
                await output.write_eof()
        return output
