from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from mi_cateye.helpers import DOMAIN
from mi_cateye import camera_control

@pytest.mark.asyncio
async def test_privacy_write_requires_explicit_confirmation(hass, monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(camera_control, "camera_state", call)
    connection = MagicMock()
    await camera_control.ws_camera_state.__wrapped__(hass, connection, {"id": 1, "device": "2", "enabled": True})
    call.assert_not_awaited()
    connection.send_error.assert_called_once()

@pytest.mark.asyncio
async def test_unselected_device_is_rejected_before_network():
    runtime = SimpleNamespace(cameras={}, ensure_video=AsyncMock())
    with pytest.raises(ValueError):
        await camera_control.camera_state(runtime, "unselected", True)
    runtime.ensure_video.assert_not_awaited()

@pytest.mark.asyncio
async def test_status_cache_avoids_cloud_polling_but_write_invalidates():
    import time
    import asyncio
    runtime = SimpleNamespace(cameras={"2": {"model": "chuangmi.camera.ipc021"}},
        camera_status_cache={"2": (time.monotonic(), {"online": True, "enabled": False})},
        camera_status_lock=asyncio.Lock(), ensure_video=AsyncMock())
    state = await camera_control.camera_state(runtime, "2")
    assert state == {"online": True, "enabled": False}
    runtime.ensure_video.assert_not_awaited()
