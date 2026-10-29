from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import time

import pytest
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from mi_cateye import config_flow as module
from mi_cateye.config_flow import ConfigFlow, OptionsFlow
from mi_cateye.helpers import DOMAIN


@pytest.fixture
def flow(hass):
    value = ConfigFlow()
    value.hass, value.handler, value.flow_id = hass, DOMAIN, "test-flow"
    value.context = {"source": "user"}
    value._begin = AsyncMock()
    hass.data.setdefault(DOMAIN, {"captchas": {}})
    return value


@pytest.mark.asyncio
async def test_user_form_and_invalid_callback_base(flow, monkeypatch):
    make = AsyncMock()
    monkeypatch.setattr(module, "make_media", make)
    form = await flow.async_step_user()
    assert form["type"] == FlowResultType.FORM
    result = await flow.async_step_user({"account": "test-user", "password": "test-password", "region": "cn",
                                         "ha_url": "http://user:password@example.com/path"})
    assert result["errors"] == {"base": "invalid_ha_url"}
    make.assert_not_awaited()


@pytest.mark.asyncio
async def test_password_only_sent_to_private_backend(flow, monkeypatch):
    media = SimpleNamespace(start=AsyncMock(), login=AsyncMock(return_value={"status": "ready"}))
    monkeypatch.setattr(module, "make_media", AsyncMock(return_value=media))
    monkeypatch.setattr(module, "async_get_clientsession", lambda hass: MagicMock())
    flow._after_video_login = AsyncMock(return_value={"done": True})
    await flow.async_step_user({"account": "test-user", "password": "private-test-password", "region": "cn",
                                "ha_url": "http://ha.example.test:8123"})
    media.login.assert_awaited_once_with(username="test-user", password="private-test-password")
    assert "private-test-password" not in repr(flow._data)
    assert "test-user" not in repr(flow._data)


@pytest.mark.asyncio
async def test_single_device_binds_without_account_wide_entities(flow):
    flow._choices = {"123": {"did": "123", "camera_host": "192.168.1.10", "media_user_id": "456", "name": "Door"}}
    flow.async_step_oauth = AsyncMock(return_value={"next": "oauth"})
    result = await flow.async_step_device()
    assert result == {"next": "oauth"}
    assert flow._data["did"] == "123"
    assert flow.unique_id == "123"


@pytest.mark.asyncio
async def test_duplicate_doorbell_aborts(flow, hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="123", data={})
    entry.add_to_hass(hass)
    flow._choices = {"123": {"did": "123", "camera_host": "192.168.1.10", "media_user_id": "456", "name": "Door"}}
    with pytest.raises(AbortFlow) as error:
        await flow.async_step_device()
    assert error.value.reason == "already_configured"


@pytest.mark.asyncio
async def test_callback_csrf_replay_and_bound_device(flow, monkeypatch):
    flow._hook, flow._nonce = "hook", "expected-state"
    flow._data.update({"did": "123", "region": "cn"})
    flow._oauth = SimpleNamespace(get_access_token_async=AsyncMock(return_value={
        "access_token": "private-test-access", "refresh_token": "private-test-refresh", "expires_ts": time.time() + 3600,
        "extra_server_field": "must-not-persist",
    }))
    http = SimpleNamespace(get_devices_with_dids_async=AsyncMock(return_value={"123": {"model": module.MODEL}}), deinit_async=AsyncMock())
    monkeypatch.setattr(module, "MIoTHttpClient", lambda **kwargs: http)
    wrong = SimpleNamespace(query={"state": "wrong", "code": "test-code"})
    assert (await flow._callback(flow.hass, "hook", wrong)).status == 404
    flow._oauth.get_access_token_async.assert_not_awaited()
    request = SimpleNamespace(query={"state": "expected-state", "code": "test-code"})
    assert (await flow._callback(flow.hass, "hook", request)).status == 200
    assert flow._oauth_complete
    assert set(flow._data["oauth"]) == {"access_token", "refresh_token", "expires_ts"}
    assert (await flow._callback(flow.hass, "hook", request)).status == 404
    assert flow._oauth.get_access_token_async.await_count == 1
    http.get_devices_with_dids_async.assert_awaited_once_with(["123"])
    http.deinit_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_account_device_does_not_persist_authorization(flow, monkeypatch):
    flow._hook, flow._nonce = "hook", "state"
    flow._data.update({"did": "123", "region": "cn"})
    flow._oauth = SimpleNamespace(get_access_token_async=AsyncMock(return_value={
        "access_token": "test-access", "refresh_token": "test-refresh", "expires_ts": time.time() + 3600,
    }))
    http = SimpleNamespace(get_devices_with_dids_async=AsyncMock(return_value={"different": {"model": module.MODEL}}), deinit_async=AsyncMock())
    monkeypatch.setattr(module, "MIoTHttpClient", lambda **kwargs: http)
    result = await flow._callback(flow.hass, "hook", SimpleNamespace(query={"state": "state", "code": "test-code"}))
    assert result.status == 400
    assert "oauth" not in flow._data
    assert not flow._oauth_complete


@pytest.mark.asyncio
async def test_aborted_flow_stops_backend_and_removes_its_temporary_profile(flow, tmp_path, monkeypatch):
    path = tmp_path / "media.json"
    path.write_text("private test profile")
    flow._media = SimpleNamespace(directory=tmp_path, stop=AsyncMock())
    flow._oauth = SimpleNamespace(deinit_async=AsyncMock())
    flow._hook, flow._captcha_nonce = "hook", "nonce"
    flow.hass.data[DOMAIN]["captchas"]["nonce"] = (999999, b"test", "image/png")
    unregister = MagicMock()
    monkeypatch.setattr(module.webhook, "async_unregister", unregister)
    await flow._cleanup()
    await flow._cleanup()
    flow._media.stop.assert_awaited_once()
    flow._oauth.deinit_async.assert_awaited_once()
    unregister.assert_called_once_with(flow.hass, "hook")
    assert not path.exists()
    assert not flow.hass.data[DOMAIN]["captchas"]


@pytest.mark.asyncio
async def test_completed_flow_keeps_owned_media_credentials(flow, tmp_path):
    path = tmp_path / "media.json"
    path.write_text("private test profile")
    flow._media = SimpleNamespace(directory=tmp_path, stop=AsyncMock())
    flow._finished = True
    await flow._cleanup()
    assert path.exists()


@pytest.mark.asyncio
async def test_options_reject_external_receiver(hass):
    entry = MockConfigEntry(domain=DOMAIN, options={})
    entry.add_to_hass(hass)
    flow = OptionsFlow()
    flow.hass, flow.handler, flow.flow_id = hass, entry.entry_id, "options-test"
    result = await flow.async_step_init({"tv_host": "8.8.8.8"})
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_receiver_address"}


@pytest.mark.asyncio
async def test_oauth_uses_registered_origin_not_playback_address(flow, monkeypatch):
    flow._data.update({"ha_url": "https://remote.example.test", "region": "cn"})
    factory = MagicMock(return_value=SimpleNamespace(state="upstream-sdk-state", gen_auth_url=MagicMock(return_value="https://account.example.test")))
    monkeypatch.setattr(module, "async_get_system_info", AsyncMock(return_value={
        "version":"2026.10.4", "os_name":"Linux", "os_version":"test", "arch":"x86_64", "installation_type":"Home Assistant OS"}))
    monkeypatch.setattr(module, "MIoTOauthClient", factory)
    monkeypatch.setattr(module.webhook, "async_register", MagicMock())
    await flow.async_step_oauth()
    callback = factory.call_args.kwargs["redirect_url"]
    assert callback.startswith("http://homeassistant.local:8123/api/webhook/")
    assert "remote.example.test" not in callback
    assert callback.rsplit("/", 1)[-1].isdecimal()
    assert flow._nonce == "upstream-sdk-state"
    assert factory.call_args.kwargs["system_info"] == "hass/2026.10.4 (Linux/test; x86_64; Home Assistant OS)"
    factory.return_value.gen_auth_url.assert_called_once_with(redirect_url=callback)


@pytest.mark.asyncio
async def test_authorization_failure_reports_stage_without_secret(flow, caplog):
    flow._hook, flow._nonce = "hook", "state"
    flow._oauth = SimpleNamespace(get_access_token_async=AsyncMock(side_effect=RuntimeError("private-secret-url")))
    request = SimpleNamespace(query={"state": "state", "code": "test-code"})
    result = await flow._callback(flow.hass, "hook", request)
    assert result.status == 400
    assert "授权凭据交换" in result.text
    assert "private-secret-url" not in result.text + caplog.text
    assert "token_exchange" in caplog.text


@pytest.mark.parametrize("message,expected", [
    ('invalid http response, {"code":-10000,"message":"private secret","access_token":"secret"}', "code=-10000"),
    ('invalid http status code, 403', 'http_status=403'),
    ('unauthorized(401)', 'http_status=401'),
    ('invalid http response, {"code":"secret token"}', 'invalid_response'),
    ('private secret', 'unclassified'),
])
def test_oauth_error_keeps_only_numeric_protocol_evidence(message, expected):
    error = SimpleNamespace(message=message)
    assert module.safe_oauth_reason(error) == expected


def test_vendor_user_agent_uses_upstream_manifest_version():
    from mi_cateye.vendor.miot.const import INTEGRATION_VERSION
    assert INTEGRATION_VERSION == "0.5.0"
