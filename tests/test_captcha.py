import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
import time

import pytest

from mi_cateye.config_flow import ConfigFlow
from mi_cateye.helpers import DOMAIN


@pytest.mark.asyncio
async def test_refresh_fetches_new_challenge_and_invalidates_old_image(hass, monkeypatch):
    flow = ConfigFlow()
    flow.hass, flow.handler, flow.flow_id = hass, DOMAIN, "captcha-test"
    flow.context = {"source": "user"}
    flow._captcha_nonce = "old-nonce"
    hass.data[DOMAIN] = {"captchas": {"old-nonce": (time.monotonic()+300, b"old", "image/png")}}
    flow._media = SimpleNamespace(login=AsyncMock(return_value={
        "status": "captcha", "image": base64.b64encode(b"\x89PNGtest-new-image").decode()}))
    monkeypatch.setattr("mi_cateye.config_flow.async_sign_path", lambda *args, **kwargs: "/signed-image")
    result = await flow.async_step_captcha({"refresh_captcha": True})
    flow._media.login.assert_awaited_once_with(refresh_captcha="true")
    assert "old-nonce" not in hass.data[DOMAIN]["captchas"]
    assert flow._captcha_nonce in hass.data[DOMAIN]["captchas"]
    assert result["step_id"] == "captcha"


@pytest.mark.asyncio
async def test_incorrect_code_replaces_challenge_from_server(hass, monkeypatch):
    flow = ConfigFlow()
    flow.hass, flow.handler, flow.flow_id = hass, DOMAIN, "captcha-test"
    flow.context = {"source": "user"}
    flow._captcha_nonce = "old-nonce"
    hass.data[DOMAIN] = {"captchas": {}}
    flow._media = SimpleNamespace(login=AsyncMock(return_value={
        "status": "captcha", "image": base64.b64encode(b"\x89PNGupdated-image").decode()}))
    monkeypatch.setattr("mi_cateye.config_flow.async_sign_path", lambda *args, **kwargs: "/new-image")
    await flow.async_step_captcha({"code": "incorrect"})
    flow._media.login.assert_awaited_once_with(captcha="incorrect")
    assert flow._captcha_nonce != "old-nonce"
