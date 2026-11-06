from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from mi_cateye.helpers import DOMAIN
from mi_cateye import recordings

def runtime(hass):
    value = SimpleNamespace(closed=False, entry=SimpleNamespace(data={"did":"1"}), cameras={
        "2":{"name":"测试摄像机","model":"chuangmi.camera.ipc021"},
        "3":{"name":"另一台","model":"chuangmi.camera.ipc009"},
        "4":{"name":"未验证","model":"other.camera.test"}})
    hass.data[DOMAIN] = {"runtime":value}
    return value

@pytest.mark.asyncio
async def test_catalog_only_lists_configured_verified_models(hass):
    runtime(hass);conn=MagicMock()
    await recordings.ws_recordings_devices.__wrapped__(hass,conn,{"id":1})
    result=conn.send_result.call_args.args[1]
    assert [r["device"] for r in result["devices"]]==["1","1","2","3"]
    assert [r["source"] for r in result["devices"]]==["cloud","sd","sd","sd"]

@pytest.mark.asyncio
async def test_sd_list_binds_selected_device_and_filters_private_fields(hass,monkeypatch):
    runtime(hass);conn=MagicMock()
    backend=AsyncMock(return_value={"items":[{"id":"a"*32,"start":1793200000010,"duration":60,"event":"local","token":"PRIVATE","path":"PRIVATE"}]})
    monkeypatch.setattr(recordings,"backend_request",backend)
    await recordings.ws_recordings_list.__wrapped__(hass,conn,{"id":1,"start":1793200000000,"end":1793286399999,"source":"sd","device":"2"})
    assert backend.call_args.args[3]["device"]=="2"
    result=conn.send_result.call_args.args[1]
    assert result["source"]=="sd" and result["sd_supported"] is True
    assert set(result["items"][0])=={"id","start","duration","event","source"}

@pytest.mark.asyncio
@pytest.mark.parametrize("device",["4","../private","999"])
async def test_unverified_or_unknown_sd_device_never_reaches_backend(hass,monkeypatch,device):
    runtime(hass);conn=MagicMock();backend=AsyncMock();monkeypatch.setattr(recordings,"backend_request",backend)
    await recordings.ws_recordings_list.__wrapped__(hass,conn,{"id":1,"start":1793200000000,"end":1793286399999,"source":"sd","device":device})
    backend.assert_not_awaited();conn.send_error.assert_called_once()

@pytest.mark.asyncio
async def test_cat_sd_reaches_only_entry_device(hass,monkeypatch):
    runtime(hass);conn=MagicMock();backend=AsyncMock(return_value={"items":[]})
    monkeypatch.setattr(recordings,"backend_request",backend)
    await recordings.ws_recordings_list.__wrapped__(hass,conn,{"id":1,"start":1793200000000,"end":1793286399999,"source":"sd","device":"1"})
    assert backend.call_args.args[3]["device"]=="1"
    assert conn.send_result.call_args.args[1]["sd_supported"] is True

@pytest.mark.asyncio
async def test_busy_camera_message_is_actionable_without_private_error_text(hass,monkeypatch):
    runtime(hass);conn=MagicMock();monkeypatch.setattr(recordings,"backend_request",AsyncMock(side_effect=ValueError("storage_device_busy")))
    await recordings.ws_recordings_list.__wrapped__(hass,conn,{"id":1,"start":1793200000000,"end":1793286399999,"source":"sd","device":"2"})
    assert "实时视频" in conn.send_error.call_args.args[2]
