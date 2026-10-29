"""Own one verified media subprocess and private configuration per integration."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
import secrets
import yaml
from urllib.parse import urlencode

import aiohttp


class MediaError(Exception):
    """A safe status suitable for the UI; never contains cloud responses."""


def unused_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stream_configuration(user_id: str, region: str, did: str, host: str) -> dict:
    if not user_id.isascii() or not did.isascii() or not user_id.isdecimal() or not did.isdecimal():
        raise MediaError("invalid_device_identity")
    if region not in {"cn", "de", "i2", "ru", "sg", "us"}:
        raise MediaError("unsupported_region")
    try:
        address = ipaddress.ip_address(host)
    except ValueError as err:
        raise MediaError("invalid_camera_address") from err
    private_networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if address.version != 4 or not any(address in ipaddress.ip_network(network) for network in private_networks):
        raise MediaError("camera_requires_private_ipv4")
    source = f"xiaomi://{user_id}:{region}@{address}?" + urlencode({"did": did, "model": "loock.cateye.v02"})
    return {
        "doorbell_live": source,
        "doorbell_compatible": "ffmpeg:doorbell_live#video=h264#audio=opus",
        "doorbell_tv": "ffmpeg:doorbell_live#video=h264#audio=opus",
        "doorbell_tv_mjpeg": "ffmpeg:doorbell_live#video=mjpeg",
    }


def secure_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise MediaError("unsafe_configuration_path")
    fd, temporary = tempfile.mkstemp(prefix=".media-", dir=path.parent)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False, default_flow_style=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class MediaRuntime:
    def __init__(self, directory: Path, binary: Path, expected_sha256: str, session: aiohttp.ClientSession):
        self.directory = directory
        self.binary = binary
        self.expected_sha256 = expected_sha256
        self.session = session
        self.process = None
        self.api_port = None
        self.rtsp_port = None
        self._lock = asyncio.Lock()
        self.instance_id = secrets.token_hex(16)

    @property
    def base_url(self):
        if self.api_port is None:
            raise MediaError("backend_not_running")
        return f"http://127.0.0.1:{self.api_port}"

    async def start(self, streams: dict | None = None, media_tokens: dict | None = None):
        async with self._lock:
            if self.process is not None and self.process.returncode is None:
                return
            valid = await asyncio.to_thread(self._binary_valid)
            if not valid:
                raise MediaError("backend_missing_or_checksum_mismatch")
            # Some ZIP extractors discard Unix executable permission bits.
            if os.name == "posix":
                await asyncio.to_thread(os.chmod, self.binary, 0o755)
            self.api_port = unused_loopback_port()
            self.rtsp_port = unused_loopback_port()
            while self.rtsp_port == self.api_port:
                self.rtsp_port = unused_loopback_port()
            configuration = {
                "api": {"listen": f"127.0.0.1:{self.api_port}", "allow_paths": [
                    "/api", "/api/streams", "/api/xiaomi", "/api/ws", "/api/stream.mp4",
                    "/api/frame.mp4", "/api/stream.mjpeg",
                    "/api/doorbell/recordings", "/api/doorbell/recordings/prepare", "/api/doorbell/recordings/clip",
                ]},
                "rtsp": {"listen": f"127.0.0.1:{self.rtsp_port}"},
                "log": {"level": "error"},
                "streams": streams or {},
                "doorbell": {"instance_id": self.instance_id},
            }
            if media_tokens:
                configuration["xiaomi"] = media_tokens
            path = self.directory / "media.json"
            await asyncio.to_thread(secure_write_json, path, configuration)
            self.process = await asyncio.create_subprocess_exec(
                str(self.binary), "-c", str(path),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                async with asyncio.timeout(10):
                    while self.process.returncode is None:
                        try:
                            async with self.session.get(self.base_url + "/api", timeout=aiohttp.ClientTimeout(total=0.5)) as response:
                                if response.status == 200:
                                    identity = await response.json()
                                    if identity.get("doorbell_instance") == self.instance_id and self.process.returncode is None:
                                        return
                        except (aiohttp.ClientError, TimeoutError):
                            pass
                        await asyncio.sleep(0.1)
                    raise MediaError("backend_start_failed")
            except BaseException:
                await self._stop()
                raise

    def _binary_valid(self):
        return self.binary.is_file() and hashlib.sha256(self.binary.read_bytes()).hexdigest() == self.expected_sha256

    async def _stop(self):
        process, self.process = self.process, None
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                await process.wait()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except TimeoutError:
                process.kill()
                await process.wait()
        self.api_port = self.rtsp_port = None

    async def stop(self):
        async with self._lock:
            await self._stop()

    async def login(self, **fields):
        """Send login inputs only to our identified loopback child."""
        if set(fields) - {"username", "password", "captcha", "verify", "refresh_captcha"}:
            raise MediaError("invalid_login_fields")
        try:
            async with self.session.post(self.base_url + "/api/xiaomi", data=fields,
                                         timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status == 200:
                    path = self.directory / "media.json"
                    await asyncio.to_thread(os.chmod, path, 0o600)
                    await self.read_tokens()
                    return {"status": "ready"}
                if response.status == 401:
                    value = await response.json()
                    if isinstance(value.get("captcha"), str) and len(value["captcha"]) <= 700000:
                        return {"status": "captcha", "image": value["captcha"]}
                    if value.get("verify_phone") or value.get("verify_email"):
                        return {"status": "verify"}
        except (aiohttp.ClientError, TimeoutError, ValueError, OSError):
            raise MediaError("video_login_unavailable") from None
        raise MediaError("video_login_failed")

    async def camera_choices(self, region):
        """Return only the supported cat-eye model, never arbitrary streams."""
        from urllib.parse import urlsplit, parse_qs
        try:
            async with self.session.get(self.base_url + "/api/xiaomi", timeout=aiohttp.ClientTimeout(total=10)) as response:
                users = await response.json()
            if not isinstance(users, list) or len(users) != 1:
                raise MediaError("video_account_not_unique")
            user = str(users[0])
            async with self.session.get(self.base_url + "/api/xiaomi", params={"id": user, "region": region},
                                        timeout=aiohttp.ClientTimeout(total=30)) as response:
                sources = await response.json()
            choices = {}
            # go2rtc's source-list response is an array, or a sources object.
            if isinstance(sources, dict):
                sources = sources.get("sources", [])
            for item in sources if isinstance(sources, list) else []:
                if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                    continue
                url = urlsplit(item["url"])
                query = parse_qs(url.query)
                if query.get("model") != ["loock.cateye.v02"] or url.username != user:
                    continue
                did = query.get("did", [""])[0]
                host = url.hostname or ""
                stream_configuration(user, region, did, host)
                choices[did] = {"did": did, "camera_host": host, "media_user_id": user,
                                "name": str(item.get("name") or "猫眼")[:80]}
            return choices
        except MediaError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
            raise MediaError("device_list_unavailable") from None

    async def read_tokens(self):
        def read():
            path = self.directory / "media.json"
            if path.is_symlink():
                raise MediaError("unsafe_configuration_path")
            text = path.read_text(encoding="utf-8")
            migrated = False
            try:
                value = yaml.safe_load(text)
            except yaml.YAMLError:
                # Older alpha writes JSON; upstream's line-based YAML patcher
                # appends a credential mapping after that complete JSON object.
                # Accept only this exact, validated legacy shape.
                stripped = text.lstrip()
                value, end = json.JSONDecoder().raw_decode(stripped)
                if not isinstance(value, dict) or value.get("xiaomi") != {}:
                    raise MediaError("video_authorization_missing")
                tail = yaml.safe_load(stripped[end:].strip())
                if not isinstance(tail, dict):
                    raise MediaError("video_authorization_missing")
                value["xiaomi"] = tail["xiaomi"] if set(tail) == {"xiaomi"} else tail
                migrated = True
            tokens = value.get("xiaomi", {}) if isinstance(value, dict) else {}
            if not isinstance(tokens, dict) or not tokens or not all(
                isinstance(k, str) and k.isascii() and k.isdecimal() and isinstance(v, str) and v
                for k, v in tokens.items()
            ):
                raise MediaError("video_authorization_missing")
            if migrated:
                secure_write_json(path, value)
            return tokens
        try:
            return await asyncio.to_thread(read)
        except MediaError:
            raise
        except Exception:
            raise MediaError("video_authorization_missing") from None
