from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

import aiohttp
import pytest

from mi_cateye import receivers


class Response:
    def __init__(self, data=None, fail=False):
        self.data, self.fail = data, fail

    async def __aenter__(self):
        if self.fail:
            raise aiohttp.ClientConnectionError()
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def json(self):
        return self.data


@pytest.fixture
def rig(monkeypatch):
    calls = []
    state = {"level": 25, "manual": None, "closed": False}

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET" and url.endswith("/volume"):
            return Response({"level": state["level"]})
        if "/volume?level=" in url:
            state["level"] = int(url.split("level=")[1].split("&")[0])
        if url.endswith("/state"):
            return Response({"popups": []} if state["closed"] else {
                "popups": [{"id": "doorbell-shared-live"}],
                "lastPopup": {"id": "doorbell-shared-live", "firstFrameMs": 3000}})
        return Response()

    async def sleep(_):
        if state["manual"] is not None:
            state["level"] = state["manual"]

    monkeypatch.setattr(receivers, "signed_url", lambda r, path, seconds=120: "http://ha.example.test" + path)
    monkeypatch.setattr(receivers.asyncio, "sleep", sleep)
    runtime = SimpleNamespace(
        entry=SimpleNamespace(options={"xiaoai_host": "192.168.1.10", "tv_host": "192.168.1.11"}),
        ensure_video=AsyncMock(), prime=AsyncMock(), cancel_prime=lambda: calls.append(("cancel",)),
        xiaoai_lock=asyncio.Lock(), closed=False,
        client=SimpleNamespace(request=request, post=lambda url, **kwargs: request("POST", url, **kwargs)),
    )
    return runtime, calls, state


@pytest.mark.asyncio
async def test_xiaoai_restores_volume_and_keeps_ai_guard_id(rig):
    runtime, calls, state = rig
    await receivers.show_xiaoai(runtime)
    assert state["level"] == 25
    payloads = [kw["json"] for method, url, kw in calls if url.endswith("/notify")]
    assert len(payloads) == 1
    assert payloads[0]["id"] == "doorbell-shared-live"
    assert payloads[0]["media"]["video"]["width"] == 854
    assert payloads[0]["fullscreen"] is True


@pytest.mark.asyncio
async def test_xiaoai_preserves_manual_volume(rig):
    runtime, calls, state = rig
    state["manual"] = 42
    await receivers.show_xiaoai(runtime)
    assert state["level"] == 42
    assert not any("level=25" in url for _, url, _ in calls)


@pytest.mark.asyncio
async def test_xiaoai_closed_popup_not_reopened(rig):
    runtime, calls, state = rig
    state["closed"] = True
    await receivers.show_xiaoai(runtime)
    assert sum(url.endswith("/notify") for _, url, _ in calls) == 1


@pytest.mark.asyncio
async def test_tv_failure_cancels_prime_without_fallback(rig):
    runtime, calls, _ = rig
    runtime.client.post = lambda *args, **kwargs: Response(fail=True)
    with pytest.raises(ValueError, match="tv_receiver_unavailable"):
        await receivers.show_tv(runtime)
    runtime.prime.assert_awaited_once()
    assert calls == [("cancel",)]


@pytest.mark.asyncio
async def test_phone_popup_targets_only_configured_browser(monkeypatch):
    call = AsyncMock()
    runtime = SimpleNamespace(entry=SimpleNamespace(options={"phone_browser_id":"browser_mod_test_phone"}),
        hass=SimpleNamespace(services=SimpleNamespace(has_service=lambda *args: True, async_call=call)))
    monkeypatch.setattr(receivers,"signed_url",lambda *args:"/signed-player")
    await receivers.popup_phone(runtime)
    args=call.await_args.args
    assert args[:2] == ("browser_mod","popup")
    assert args[2]["browser_id"] == ["browser_mod_test_phone"]
    assert args[2]["content"]["aspect_ratio"] == "56.25%"
    assert args[2]["dismissable"] and args[2]["timeout"] == 60000


@pytest.mark.asyncio
async def test_phone_popup_blank_never_broadcasts():
    call=AsyncMock()
    runtime=SimpleNamespace(entry=SimpleNamespace(options={}),hass=SimpleNamespace(services=SimpleNamespace(async_call=call)))
    await receivers.popup_phone(runtime)
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_phone_popup_rejects_invalid_target():
    runtime=SimpleNamespace(entry=SimpleNamespace(options={"phone_browser_id":"*"}))
    with pytest.raises(ValueError,match="invalid_phone_browser"):
        await receivers.popup_phone(runtime)
