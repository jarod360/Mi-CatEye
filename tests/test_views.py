from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request
import pytest
from homeassistant.helpers.http import request_handler_factory, KEY_AUTHENTICATED
from homeassistant.helpers import network

from mi_cateye.helpers import DOMAIN
from mi_cateye.media import MediaError
from mi_cateye.views import RawView, MseView, PlayerView, VoiceView, CaptchaView


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [RawView, MseView, PlayerView, VoiceView, CaptchaView])
async def test_ha_auth_rejects_request_before_touching_runtime(hass, monkeypatch, kind):
    def unavailable(*args, **kwargs):
        raise network.NoURLAvailableError()

    monkeypatch.setattr(network, "get_url", unavailable)
    if kind is PlayerView:
        view = kind(hass, "template")
    elif kind is VoiceView:
        view = kind()
    else:
        view = kind(hass)
    runtime = SimpleNamespace(closed=False, ensure_video=AsyncMock())
    hass.data[DOMAIN] = {"runtime": runtime}
    handler = request_handler_factory(hass, view, view.get)
    request = make_mocked_request("GET", view.url)
    with pytest.raises(web.HTTPUnauthorized):
        await handler(request)
    runtime.ensure_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_bad_codec_never_starts_video(hass):
    runtime = SimpleNamespace(closed=False, ensure_video=AsyncMock())
    hass.data[DOMAIN] = {"runtime": runtime}
    view = RawView(hass)
    request = make_mocked_request("GET", view.url + "?codec=unsupported")
    request[KEY_AUTHENTICATED] = True
    with pytest.raises(web.HTTPBadRequest):
        await request_handler_factory(hass, view, view.get)(request)
    runtime.ensure_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_owner_conflict_does_not_open_stream(hass):
    runtime = SimpleNamespace(closed=False, ensure_video=AsyncMock(side_effect=MediaError("legacy_owner")),
                              client=SimpleNamespace(get=AsyncMock()))
    hass.data[DOMAIN] = {"runtime": runtime}
    view = RawView(hass)
    request = make_mocked_request("GET", view.url)
    request[KEY_AUTHENTICATED] = True
    with pytest.raises(web.HTTPConflict):
        await request_handler_factory(hass, view, view.get)(request)
    runtime.client.get.assert_not_called()
