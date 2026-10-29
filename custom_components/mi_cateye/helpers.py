"""Private paths and bundled, checksummed backend selection."""
from __future__ import annotations

import json
from pathlib import Path
import platform
import re

from .media import MediaRuntime, MediaError

DOMAIN = "mi_cateye"
ASSETS = Path(__file__).parent / "assets"


def profile_directory(hass, uuid):
    if not isinstance(uuid, str) or not re.fullmatch(r"[a-f0-9]{32}", uuid):
        raise MediaError("invalid_profile_identity")
    return Path(hass.config.path(".storage", DOMAIN, uuid))


def bundled_backend():
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armv7"}.get(machine)
    if platform.system() != "Linux" or arch is None:
        raise MediaError("unsupported_host_platform")
    base = Path(__file__).parent / "bin"
    try:
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        item = manifest[arch]
        filename, digest = item["filename"], item["sha256"]
        if Path(filename).name != filename or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError
        return base / filename, digest
    except (OSError, ValueError, KeyError, TypeError):
        raise MediaError("backend_not_packaged") from None


async def make_media(hass, uuid, session):
    binary, digest = await hass.async_add_executor_job(bundled_backend)
    return MediaRuntime(profile_directory(hass, uuid), binary, digest, session)
