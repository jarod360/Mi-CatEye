"""Selected cameras only; explicit user confirmation before privacy changes."""
import asyncio
import time
import logging

import aiohttp
import probatio as vol
from homeassistant.components import websocket_api

from .views import runtime_for

MODELS = {"chuangmi.camera.ipc021", "chuangmi.camera.ipc009"}
LOGGER = logging.getLogger(__name__)


async def backend_state(runtime, device, enabled=None):
    kwargs = {"params": {"device": device}, "timeout": aiohttp.ClientTimeout(total=15)}
    if enabled is not None:
        kwargs["json"] = {"enabled": enabled, "confirmed": True}
    async with runtime.client.request("GET" if enabled is None else "POST",
                                      runtime.media.base_url + "/api/doorbell/camera-state", **kwargs) as response:
        value = await response.json()
        if response.status != 200 or not isinstance(value, dict):
            raise ValueError("camera_control_failed")
    return value


async def camera_state(runtime, device, enabled=None, fresh=False):
    camera = runtime.cameras.get(device)
    if not camera or camera["model"] not in MODELS:
        raise ValueError("camera_not_selected")
    if not hasattr(runtime, "camera_status_cache"):
        runtime.camera_status_cache = {}
        runtime.camera_status_lock = asyncio.Lock()
    async with runtime.camera_status_lock:
        cached = runtime.camera_status_cache.get(device)
        if enabled is None and not fresh and cached and time.monotonic() - cached[0] < 15:
            return dict(cached[1])
        await runtime.ensure_video()
        if enabled is not None or fresh:
            runtime.camera_status_cache.pop(device, None)
        started = time.monotonic()
        try:
            async with asyncio.timeout(35):
                # Send exactly once. Xiaomi may acknowledge before the property
                # changes; subsequent attempts only read, never resend the write.
                value = await backend_state(runtime, device, enabled)
                if enabled is not None:
                    for _ in range(8):
                        if value.get("enabled") is enabled:
                            break
                        await asyncio.sleep(1.5)
                        value = await backend_state(runtime, device)
                    if value.get("enabled") is not enabled:
                        raise ValueError("camera_state_not_confirmed")
                    LOGGER.info("Camera privacy confirmed model=%s enabled=%s elapsed=%.1fs",
                                camera["model"], enabled, time.monotonic() - started)
        except (ValueError, aiohttp.ClientError, TimeoutError):
            if enabled is not None:
                LOGGER.warning("Camera privacy not confirmed model=%s enabled=%s elapsed=%.1fs; no write retry",
                               camera["model"], enabled, time.monotonic() - started)
            raise
        state = {"device": device, "online": value.get("online") if type(value.get("online")) is bool else None,
                 "enabled": value.get("enabled") if type(value.get("enabled")) is bool else None,
                 "physical_privacy": camera["model"] == "chuangmi.camera.ipc021"}
        runtime.camera_status_cache[device] = (time.monotonic(), state)
        return dict(state)


@websocket_api.websocket_command({vol.Required("type"): "mi_cateye/camera_state",
                                 vol.Required("device"): str,
                                 vol.Optional("enabled"): bool,
                                 vol.Optional("fresh", default=False): bool,
                                 vol.Optional("confirmed", default=False): bool})
@websocket_api.async_response
async def ws_camera_state(hass, connection, message):
    if "enabled" in message and message.get("confirmed") is not True:
        connection.send_error(message["id"], "confirmation_required", "请先确认隐私模式更改")
        return
    try:
        value = await camera_state(runtime_for(hass), message["device"], message.get("enabled"), message.get("fresh", False))
        connection.send_result(message["id"], value)
    except (ValueError, aiohttp.ClientError, TimeoutError):
        connection.send_error(message["id"], "camera_status_unavailable", "暂时无法读取或设置摄像机状态，请稍后重试")


@websocket_api.websocket_command({vol.Required("type"): "mi_cateye/camera_move",
                                 vol.Required("device"): str,
                                 vol.Required("direction"): vol.In(("left", "right", "up", "down"))})
@websocket_api.async_response
async def ws_camera_move(hass, connection, message):
    runtime = runtime_for(hass)
    device = message["device"]
    if runtime.cameras.get(device, {}).get("model") not in MODELS:
        connection.send_error(message["id"], "camera_not_selected", "未配置此摄像机")
        return
    try:
        await runtime.ensure_video()
        async with runtime.client.post(
            runtime.media.base_url + "/api/doorbell/camera-move",
            params={"device": device}, json={"direction": message["direction"]},
            timeout=aiohttp.ClientTimeout(total=48),
        ) as response:
            if response.status in (409, 429):
                connection.send_error(message["id"], "camera_move_unavailable", "请确认画面仍在播放，稍等再操作")
                return
            response.raise_for_status()
            if (await response.json()).get("sent") is not True:
                raise ValueError("camera_move_unconfirmed")
        connection.send_result(message["id"], {"sent": True})
    except (ValueError, aiohttp.ClientError, TimeoutError):
        connection.send_error(message["id"], "camera_move_unconfirmed", "无法确认指令是否送达，请先查看画面")
