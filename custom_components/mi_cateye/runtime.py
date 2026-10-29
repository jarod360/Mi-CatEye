"""HA-facing ownership of cloud events, one media backend and receiver actions."""
from __future__ import annotations

import asyncio
from contextlib import suppress

from .media import stream_configuration, MediaError
from .session import DoorbellSession


class Runtime:
    def __init__(self, hass, entry, media, client):
        self.hass, self.entry, self.media, self.client = hass, entry, media, client
        self.data = {"connection": False, "online": None, "battery": None, "device": {}}
        self.listeners = set()
        self.tasks = set()
        self.xiaoai_lock = asyncio.Lock()
        self.raw_prime = self.raw_expiry = None
        self.closed = False
        # The legacy bridge still owns video until a deliberate migration.
        self.video_enabled = not bool(hass.data.get("doorbell_local")) and entry.options.get("enable_video", True)
        self.cloud = DoorbellSession(
            entry.data["did"], entry.data["uuid"], entry.data["region"], entry.data["redirect_url"],
            entry.data["oauth"], self.emit, self.persist,
        )

    async def persist(self, oauth):
        self.hass.config_entries.async_update_entry(self.entry, data={**self.entry.data, "oauth": oauth})

    def emit(self, kind, value):
        if self.closed:
            return
        self.data[kind] = value
        if kind == "authorization" and value == "authorization_invalid":
            self.entry.async_start_reauth(self.hass)
        for listener in tuple(self.listeners):
            listener(kind, value)
        if kind == "ring" and self.video_enabled and self.entry.options.get("auto_notify", True):
            self.task(self.dispatch())

    def task(self, coro):
        task = self.hass.async_create_task(coro, "unified doorbell action")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def listen(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    async def start(self):
        if self.video_enabled:
            tokens = await self.media.read_tokens()
            streams = stream_configuration(self.entry.data["media_user_id"], self.entry.data["region"],
                                            self.entry.data["did"], self.entry.data["camera_host"])
            await self.media.start(streams, tokens)
        await self.cloud.start()

    async def ensure_video(self):
        if self.closed or not self.video_enabled:
            raise MediaError("video_migration_not_enabled")
        if self.media.process is None or self.media.process.returncode is not None:
            await self.media.start(
                stream_configuration(self.entry.data["media_user_id"], self.entry.data["region"],
                                     self.entry.data["did"], self.entry.data["camera_host"]),
                await self.media.read_tokens(),
            )

    def cancel_prime(self):
        if self.raw_expiry is not None:
            self.raw_expiry.cancel()
            self.raw_expiry = None
        task, self.raw_prime = self.raw_prime, None
        if task is not None:
            if not task.done():
                task.cancel()
            elif not task.cancelled():
                with suppress(Exception):
                    task.result().close()

    async def prime(self):
        import aiohttp
        await self.ensure_video()
        self.cancel_prime()
        self.raw_prime = self.task(self.client.get(
            self.media.base_url + "/api/stream.mp4?src=doorbell_live&video=h265",
            timeout=aiohttp.ClientTimeout(total=None, sock_read=20),
        ))
        self.raw_expiry = asyncio.get_running_loop().call_later(8, self.cancel_prime)

    async def dispatch(self):
        from .receivers import show_tv, show_xiaoai, notify_phone, popup_phone
        calls = []
        for option, name, action in (("tv_host", "tv", show_tv), ("xiaoai_host", "xiaoai", show_xiaoai),
                                     ("phone_service", "phone", notify_phone), ("phone_browser_id", "phone_popup", popup_phone)):
            if self.entry.options.get(option):
                calls.append((name, action(self)))
        results = await asyncio.gather(*(call for _, call in calls), return_exceptions=True)
        self.data["notifications"] = {name: "failed" if isinstance(result, BaseException) else "sent"
                                      for (name, _), result in zip(calls, results)}

    async def close(self, _event=None):
        if self.closed:
            return
        self.closed = True
        self.cancel_prime()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await self.cloud.stop()
        finally:
            await self.media.stop()
        self.listeners.clear()
