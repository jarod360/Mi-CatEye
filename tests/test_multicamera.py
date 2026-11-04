from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mi_cateye.media import MediaError, stream_configuration
from mi_cateye.devices import selected_cameras, source_for, media_streams

DATA = {"did": "123", "media_user_id": "456", "region": "cn", "camera_host": "192.168.1.10"}
CAM = {"did": "789", "media_user_id": "456", "camera_host": "192.168.1.11", "model": "chuangmi.camera.021a04", "name": "Camera"}


def test_extra_camera_sources_preserve_legacy_and_one_source_per_device():
    cameras = selected_cameras(DATA, {"cameras": [CAM]})
    streams = media_streams(DATA, cameras)
    old = stream_configuration("456", "cn", "123", "192.168.1.10")
    assert all(streams[k] == v for k, v in old.items())
    assert streams["camera_789"].endswith("did=789&model=chuangmi.camera.021a04")
    assert source_for(DATA, cameras, "789") == "camera_789"
    assert source_for(DATA, cameras, None) == "doorbell_live"
    assert source_for(DATA, cameras, "123") == "doorbell_live"


@pytest.mark.parametrize("change", [{"did": "123"}, {"did": "../123"}, {"media_user_id": "999"},
                                    {"camera_host": "8.8.8.8"}, {"model": "xiaomi.light.test"},
                                    {"model": "chuangmi.camera.x?src=other"}])
def test_reject_cross_account_duplicate_and_injected_metadata(change):
    with pytest.raises(MediaError):
        selected_cameras(DATA, {"cameras": [{**CAM, **change}]})


def test_unselected_device_never_falls_back_to_doorbell():
    with pytest.raises(MediaError):
        source_for(DATA, {}, "999")
    with pytest.raises(MediaError):
        selected_cameras(DATA, {"cameras": [CAM, CAM]})


def test_generic_future_camera_model_is_not_restricted_to_two_skus():
    cameras = selected_cameras(DATA, {"cameras": [{**CAM, "model": "xiaomi.camera.future123"}]})
    assert "model=xiaomi.camera.future123" in media_streams(DATA, cameras)["camera_789"]


@pytest.mark.asyncio
async def test_normal_options_save_preserves_selected_cameras(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from mi_cateye.config_flow import OptionsFlow
    entry = MockConfigEntry(domain="mi_cateye", data=DATA, options={"cameras": [CAM]})
    entry.add_to_hass(hass)
    flow = OptionsFlow()
    flow.hass, flow.handler, flow.flow_id = hass, entry.entry_id, "camera-options"
    result = await flow.async_step_init({"enable_video": True, "auto_notify": True})
    assert result["data"]["cameras"] == [CAM]


@pytest.mark.asyncio
async def test_deselection_removes_only_owned_camera_entities(hass):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from mi_cateye.camera import remove_deselected_cameras
    entry = MockConfigEntry(domain="mi_cateye", data=DATA)
    other = MockConfigEntry(domain="mi_cateye", data={"did": "999"})
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    door = registry.async_get_or_create("camera", "mi_cateye", "123_camera", config_entry=entry)
    removed = registry.async_get_or_create("camera", "mi_cateye", "789_camera", config_entry=entry)
    unrelated = registry.async_get_or_create("camera", "mi_cateye", "999_camera", config_entry=other)
    remove_deselected_cameras(hass, entry, {})
    assert registry.async_get(removed.entity_id) is None
    assert registry.async_get(door.entity_id) is not None
    assert registry.async_get(unrelated.entity_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["raw", "mse", "player"])
async def test_unselected_camera_rejected_before_network(hass, kind):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    from mi_cateye.views import RawView, MseView, PlayerView
    runtime = SimpleNamespace(closed=False, ensure_video=AsyncMock(),
        source_for=lambda device, codec="h265": source_for(DATA, {}, device, codec))
    hass.data["mi_cateye"] = {"runtime": runtime}
    view = {"raw": lambda: RawView(hass), "mse": lambda: MseView(hass), "player": lambda: PlayerView(hass, "test")}[kind]()
    with pytest.raises(web.HTTPNotFound):
        await view.get(make_mocked_request("GET", view.url + "?device=999"))
    runtime.ensure_video.assert_not_awaited()


@pytest.mark.asyncio
async def test_camera_selection_only_accepts_discovered_devices(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from mi_cateye.config_flow import OptionsFlow
    entry = MockConfigEntry(domain="mi_cateye", data=DATA, options={})
    entry.add_to_hass(hass)
    flow = OptionsFlow()
    flow.hass, flow.handler, flow.flow_id = hass, entry.entry_id, "camera-options"
    flow._camera_options = {"enable_video": True}
    flow._camera_choices = {CAM["did"]: CAM}
    result = await flow.async_step_cameras({"cameras": ["999"]})
    assert result["errors"] == {"base": "invalid_camera_selection"}
    result = await flow.async_step_cameras({"cameras": ["789"]})
    assert result["data"]["cameras"] == [CAM]
    result = await flow.async_step_cameras({"cameras": []})
    assert result["data"]["cameras"] == []
