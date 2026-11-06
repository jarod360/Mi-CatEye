"""Selected cameras only; explicit user confirmation before privacy changes."""
import asyncio
import time

import aiohttp
import probatio as vol
from homeassistant.components import websocket_api

from .views import runtime_for

MODELS = {"chuangmi.camera.ipc021", "chuangmi.camera.ipc009"}


async def camera_state(runtime, device, enabled=None):
    camera = runtime.cameras.get(device)
    if not camera or camera["model"] not in MODELS:
        raise ValueError("camera_not_selected")
    if not hasattr(runtime, "camera_status_cache"):
        runtime.camera_status_cache = {}
        runtime.camera_status_lock = asyncio.Lock()
    async with runtime.camera_status_lock:
        cached = runtime.camera_status_cache.get(device)
        if enabled is None and cached and time.monotonic() - cached[0] < 15:
            return dict(cached[1])
        await runtime.ensure_video()
        kwargs = {"params": {"device": device}, "timeout": aiohttp.ClientTimeout(total=60)}
        if enabled is not None:
            runtime.camera_status_cache.pop(device, None)
            kwargs["json"] = {"enabled": enabled, "confirmed": True}
        async with runtime.client.request("GET" if enabled is None else "POST",
                                          runtime.media.base_url + "/api/doorbell/camera-state", **kwargs) as response:
            value = await response.json()
            if response.status != 200 or not isinstance(value, dict):
                raise ValueError("camera_control_failed")
        state = {"device": device, "online": value.get("online") if type(value.get("online")) is bool else None,
                 "enabled": value.get("enabled") if type(value.get("enabled")) is bool else None,
                 "physical_privacy": camera["model"] == "chuangmi.camera.ipc021"}
        runtime.camera_status_cache[device] = (time.monotonic(), state)
        return dict(state)


@websocket_api.websocket_command({vol.Required("type"): "mi_cateye/camera_state",
                                 vol.Required("device"): str,
                                 vol.Optional("enabled"): bool,
                                 vol.Optional("confirmed", default=False): bool})
@websocket_api.async_response
async def ws_camera_state(hass, connection, message):
    if "enabled" in message and message.get("confirmed") is not True:
        connection.send_error(message["id"], "confirmation_required", "请先确认隐私模式更改")
        return
    try:
        value = await camera_state(runtime_for(hass), message["device"], message.get("enabled"))
        connection.send_result(message["id"], value)
    except (ValueError, aiohttp.ClientError, TimeoutError):
        connection.send_error(message["id"], "camera_status_unavailable", "暂时无法读取或设置摄像机状态，请稍后重试")
