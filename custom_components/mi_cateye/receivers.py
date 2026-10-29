"""Existing receiver behavior, parameterized for the unified integration."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
import ipaddress
import re
import time

import aiohttp


def receiver_host(host):
    try:
        address = ipaddress.ip_address(host)
        if address.version == 4 and any(address in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
            return str(address)
    except ValueError:
        pass
    raise ValueError("receiver_requires_private_ipv4")


def signed_url(runtime, path, seconds=120):
    from homeassistant.components.http.auth import async_sign_path
    return runtime.entry.data["ha_url"].rstrip("/") + async_sign_path(
        runtime.hass, path, timedelta(seconds=seconds), use_content_user=True,
    )


async def show_tv(runtime):
    host = receiver_host(runtime.entry.options.get("tv_host", ""))
    await runtime.prime()
    payload = {
        "id": "doorbell-live", "title": "门口实时画面", "message": "智能猫眼", "position": 0, "duration": 60,
        "media": {"video": {"uri": signed_url(runtime, "/api/mi_cateye/raw.mp4", 90),
                            "width": 640, "height": 360, "muted": True, "softwareDecoder": True}},
    }
    try:
        async with runtime.client.post(f"http://{host}:7980/notify", json=payload, timeout=aiohttp.ClientTimeout(total=8)) as response:
            response.raise_for_status()
    except (aiohttp.ClientError, TimeoutError):
        runtime.cancel_prime()
        raise ValueError("tv_receiver_unavailable") from None
    # EXO only. A TV failure never switches to a compatibility receiver.


async def show_xiaoai(runtime):
    await runtime.ensure_video()
    host = receiver_host(runtime.entry.options.get("xiaoai_host", ""))
    endpoint = f"http://{host}:7979"
    runtime.xiaoai_generation = getattr(runtime, "xiaoai_generation", 0) + 1
    generation = runtime.xiaoai_generation

    async def request(method, path, **kwargs):
        async with runtime.client.request(method, endpoint + path, timeout=aiohttp.ClientTimeout(total=8), **kwargs) as response:
            response.raise_for_status()
            return await response.json() if method == "GET" else None

    async with runtime.xiaoai_lock:
        previous = None
        try:
            previous = (await request("GET", "/volume")).get("level")
            if type(previous) is not int or not 0 <= previous <= 100:
                previous = None
            if previous is not None and previous != 80:
                await request("POST", "/volume?level=80&ui=false")
            with suppress(aiohttp.ClientError, TimeoutError):
                await request("POST", "/power?state=on")
            payload = {
                "id": "doorbell-shared-live", "duration": 60, "position": 0, "fullscreen": True,
                "mediaFullBleed": True, "padding": 0, "borderWidth": 0, "cornerRadius": 0,
                "backgroundColor": "#000000", "dismissScreensaver": True,
                "sound": signed_url(runtime, "/api/mi_cateye/visitor.wav"), "soundVolume": 1,
                "media": {"video": {"uri": signed_url(runtime, "/api/mi_cateye/raw.mp4"),
                                    "width": 854, "height": 480, "muted": True}},
            }
            started = time.monotonic()
            await request("POST", "/notify", json=payload)
            await asyncio.sleep(6)
        finally:
            if previous is not None and previous != 80:
                with suppress(aiohttp.ClientError, TimeoutError):
                    current = await request("GET", "/volume")
                    if current.get("level") == 80:
                        await request("POST", f"/volume?level={previous}&ui=false")

    def active(state):
        return (not runtime.closed and runtime.xiaoai_generation == generation
                and (state.get("lastPopup") or {}).get("id") == "doorbell-shared-live"
                and any(p.get("id") == "doorbell-shared-live" for p in state.get("popups", [])))

    with suppress(aiohttp.ClientError, TimeoutError):
        for _ in range(6):
            state = await request("GET", "/state")
            if not active(state) or (state.get("lastPopup") or {}).get("firstFrameMs") is not None:
                return
            if (state.get("lastPopup") or {}).get("mediaError"):
                break
            await asyncio.sleep(2)
        state = await request("GET", "/state")
        if not active(state) or (state.get("lastPopup") or {}).get("firstFrameMs") is not None:
            return
        remaining = 60 - int(time.monotonic() - started)
        if remaining > 0:
            fallback = {**payload, "duration": remaining, "sound": None,
                        "media": {"video": {"uri": signed_url(runtime, "/api/mi_cateye/raw.mp4?codec=h264"),
                                            "width": 854, "height": 480, "muted": True}}}
            await request("POST", "/notify", json=fallback)


async def notify_phone(runtime):
    service = runtime.entry.options.get("phone_service", "")
    if not re.fullmatch(r"mobile_app_[a-z0-9_]+", service):
        raise ValueError("invalid_phone_notification_service")
    if not runtime.hass.services.has_service("notify", service):
        raise ValueError("phone_notification_unavailable")
    await runtime.hass.services.async_call("notify", service, {
        "title": "有人按门铃", "message": "点此查看门口实时画面",
        "data": {"clickAction": "/mi-cateye", "tag": "doorbell-visitor", "channel": "门铃来访",
                 "priority": "high", "ttl": 120, "importance": "high", "visibility": "private",
                 "notification_icon": "mdi:doorbell-video",
                 "actions": [{"action": "URI", "title": "查看门口", "uri": "/mi-cateye"}]}}, blocking=True)


async def popup_phone(runtime):
    """Optional, explicitly targeted Browser Mod popup; never broadcast."""
    browser = runtime.entry.options.get("phone_browser_id", "")
    if not browser:
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", browser):
        raise ValueError("invalid_phone_browser")
    if not runtime.hass.services.has_service("browser_mod", "popup"):
        raise ValueError("browser_mod_unavailable")
    await runtime.hass.services.async_call("browser_mod", "popup", {
        "browser_id": [browser], "title": "门口 · 实时画面",
        "dismissable": True, "dismiss_icon": "mdi:close", "timeout": 60000,
        "size": "classic", "initial_style": "classic",
        "content": {"type": "iframe", "url": signed_url(runtime, "/api/mi_cateye/player", 120),
                    "aspect_ratio": "56.25%"},
    }, blocking=True)
