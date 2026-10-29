from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from homeassistant.helpers.http import request_handler_factory
from mi_cateye.helpers import DOMAIN
from mi_cateye.recordings import RecordingView, validate_recording_id, ws_recordings_list, ws_recordings_prepare


@pytest.mark.asyncio
async def test_recording_rejects_unauthenticated_client_before_backend(hass):
    runtime = SimpleNamespace(closed=False, ensure_video=AsyncMock())
    hass.data[DOMAIN] = {"runtime": runtime}
    view = RecordingView(hass)
    with pytest.raises(web.HTTPUnauthorized):
        await request_handler_factory(hass, view, view.get)(make_mocked_request("GET", "/api/mi_cateye/recordings/" + "a" * 32))
    runtime.ensure_video.assert_not_awaited()


@pytest.mark.parametrize("identity", ["../private", "a" * 31, "g" * 32, "A" * 32, None])
def test_recording_ids_are_opaque_and_path_safe(identity):
    with pytest.raises(ValueError):
        validate_recording_id(identity)


@pytest.mark.asyncio
async def test_recording_list_filters_private_upstream_fields(hass, monkeypatch):
    from mi_cateye import recordings
    hass.data[DOMAIN] = {"runtime": SimpleNamespace(closed=False)}
    fake = AsyncMock(return_value={"items": [
        {"id": "a" * 32, "start": 1793200000001, "duration": 6.1, "event": "Pass", "fileId": "private", "url": "https://private/", "token": "private"},
        {"id": "b" * 32, "start": 1, "duration": 5},
    ]})
    monkeypatch.setattr(recordings, "backend_request", fake)
    conn = MagicMock()
    await ws_recordings_list.__wrapped__(hass, conn, {"id": 1, "start": 1793200000000, "end": 1793286399999, "source": "cloud"})
    result = conn.send_result.call_args.args[1]
    assert len(result["items"]) == 1
    assert set(result["items"][0]) == {"id", "source", "start", "duration", "event"}


@pytest.mark.asyncio
async def test_unsupported_sd_request_never_opens_a_session(hass, monkeypatch):
    from mi_cateye import recordings
    backend = AsyncMock()
    monkeypatch.setattr(recordings, "backend_request", backend)
    conn = MagicMock()
    await ws_recordings_list.__wrapped__(hass, conn, {"id": 1, "start": 1793200000000, "end": 1793286399999, "source": "sd"})
    conn.send_error.assert_called_once()
    backend.assert_not_called()
