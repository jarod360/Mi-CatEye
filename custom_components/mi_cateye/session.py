"""One bound doorbell, renewable OAuth and push subscriptions; no video wake-up."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

from .vendor.miot.miot_cloud import MIoTOauthClient, MIoTHttpClient
from .vendor.miot.miot_mips import MipsCloudClient, MIoTDeviceState
from .vendor.miot.miot_error import MIoTErrorCode

CLIENT_ID = "2882303761520251711"
MODEL = "loock.cateye.v02"
EVENTS = {1: "ring", 2: "pass", 3: "linger"}


class SessionError(Exception):
    """A stable error code, never the raw cloud response."""


@dataclass(frozen=True)
class OAuthState:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_ts: float

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            raise SessionError("authorization_missing")
        if not all(isinstance(value.get(k), str) and value[k] for k in ("access_token", "refresh_token")):
            raise SessionError("authorization_incomplete")
        expiry = value.get("expires_ts")
        if type(expiry) not in (int, float) or not 0 < expiry < float("inf"):
            raise SessionError("authorization_expiry_invalid")
        return cls(value["access_token"], value["refresh_token"], expiry)

    def private_data(self):
        return {"access_token": self.access_token, "refresh_token": self.refresh_token, "expires_ts": self.expires_ts}


class DoorbellSession:
    def __init__(self, did, uuid, region, redirect_url, auth, emit, persist, *,
                 oauth_factory=MIoTOauthClient, http_factory=MIoTHttpClient, mips_factory=MipsCloudClient):
        if not isinstance(did, str) or not did.isdecimal():
            raise SessionError("invalid_device_identity")
        self.did, self.uuid, self.region, self.redirect_url = did, uuid, region, redirect_url
        self.auth = OAuthState.parse(auth)
        self.emit, self.persist = emit, persist
        self.oauth_factory, self.http_factory, self.mips_factory = oauth_factory, http_factory, mips_factory
        self.oauth = self.http = self.mips = None
        self._maintenance = None
        self._read_task = None
        self._refresh_lock = asyncio.Lock()
        self._closed = True

    async def start(self):
        if not self._closed:
            return
        self._closed = False
        try:
            self.oauth = self.oauth_factory(client_id=CLIENT_ID, redirect_url=self.redirect_url, cloud_server=self.region, uuid=self.uuid)
            if self.auth.expires_ts <= time.time():
                await self.refresh()
            self.http = self.http_factory(cloud_server=self.region, client_id=CLIENT_ID, access_token=self.auth.access_token, uuid=self.uuid)
            devices = await self.http.get_devices_with_dids_async([self.did])
            device = (devices or {}).get(self.did)
            if not device or device.get("model") != MODEL:
                raise SessionError("bound_doorbell_not_found")
            # The SDK response can contain device tokens, SSID and other private
            # fields. Only these display/status fields leave this method.
            self.emit("device", {k: device.get(k) for k in ("name", "model", "online", "fw_version")})
            self.mips = self.mips_factory(uuid=self.uuid, cloud_server=self.region, app_id=CLIENT_ID, token=self.auth.access_token)
            self.mips.sub_mips_state("doorbell", self._connection_state)
            self.mips.connect()
            for eiid in EVENTS:
                self.mips.sub_event(did=self.did, siid=4, eiid=eiid, handler=self._ring)
            self.mips.sub_prop(did=self.did, siid=3, piid=1, handler=self._battery)
            self.mips.sub_device_state(did=self.did, handler=self._online)
            self._maintenance = asyncio.create_task(self._refresh_loop())
            self._read_task = asyncio.create_task(self._initial_battery())
        except asyncio.CancelledError:
            await self.stop()
            raise
        except SessionError:
            await self.stop()
            raise
        except Exception as err:
            await self.stop()
            if getattr(err, "code", None) == MIoTErrorCode.CODE_HTTP_INVALID_ACCESS_TOKEN:
                raise SessionError("authorization_invalid") from None
            raise SessionError("cloud_setup_failed") from None

    async def _connection_state(self, key, connected):
        if not self._closed:
            self.emit("connection", bool(connected))

    def _ring(self, message, _context):
        if self._closed or not isinstance(message, dict):
            return
        if message.get("did", self.did) != self.did or type(message.get("siid")) is not int or type(message.get("eiid")) is not int:
            return
        kind = EVENTS.get(message["eiid"]) if message["siid"] == 4 else None
        if kind and isinstance(message.get("arguments"), list):
            self.emit(kind, {"received_at": datetime.now(timezone.utc).isoformat()})

    def _battery(self, message, _context):
        if self._closed or not isinstance(message, dict) or message.get("did", self.did) != self.did:
            return
        value = message.get("value")
        if type(message.get("siid")) is not int or type(message.get("piid")) is not int:
            return
        if (message.get("siid"), message.get("piid")) == (3, 1) and type(value) in (int, float) and 0 <= value <= 100:
            self.emit("battery", value)

    async def _initial_battery(self):
        try:
            async with asyncio.timeout(10):
                results = await self.http.get_props_async([{"did": self.did, "siid": 3, "piid": 1}])
            for item in results if isinstance(results, list) else []:
                if isinstance(item, dict) and item.get("did") == self.did and item.get("code") == 0:
                    self._battery(item, None)
        except Exception:
            # Keep the push subscription; never log a raw cloud response.
            pass

    def _online(self, did, state, _context):
        if not self._closed and did == self.did:
            self.emit("online", state == MIoTDeviceState.ONLINE)

    async def refresh(self):
        async with self._refresh_lock:
            if self.auth.expires_ts > time.time():
                return
            try:
                value = await self.oauth.refresh_access_token_async(self.auth.refresh_token)
                new_auth = OAuthState.parse(value)
                if new_auth.expires_ts <= time.time():
                    raise SessionError("authorization_expired")
                await self.persist(new_auth.private_data())
                self.auth = new_auth
                if self.http is not None:
                    self.http.update_http_header(access_token=self.auth.access_token)
                if self.mips is not None:
                    self.mips.update_access_token(self.auth.access_token)
            except asyncio.CancelledError:
                raise
            except SessionError:
                raise
            except Exception as err:
                if getattr(err, "code", None) == MIoTErrorCode.CODE_OAUTH_UNAUTHORIZED:
                    raise SessionError("authorization_invalid") from None
                raise SessionError("authorization_refresh_failed") from None

    async def _refresh_loop(self):
        while not self._closed:
            await asyncio.sleep(min(3600, max(5, self.auth.expires_ts - time.time())))
            if self.auth.expires_ts <= time.time():
                try:
                    await self.refresh()
                except SessionError as err:
                    self.emit("authorization", str(err))
                    if str(err) == "authorization_invalid":
                        return
                    await asyncio.sleep(60)

    async def stop(self):
        self._closed = True
        tasks = [task for task in (self._maintenance, self._read_task) if task is not None]
        self._maintenance = self._read_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        mips, self.mips = self.mips, None
        if mips is not None:
            # Upstream deinit_async hangs when the client never connected.
            # Synchronous deinit also joins its thread: never block HA's loop.
            await asyncio.to_thread(mips.deinit)
        http, self.http = self.http, None
        oauth, self.oauth = self.oauth, None
        if http is not None:
            await http.deinit_async()
        if oauth is not None:
            await oauth.deinit_async()
