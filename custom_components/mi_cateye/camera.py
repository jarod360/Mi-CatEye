from homeassistant.components.camera import Camera, CameraEntityFeature
from .entity import DoorbellEntity
from .helpers import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN]["runtime"]
    remove_deselected_cameras(hass, entry, runtime.cameras)
    async_add_entities([DoorbellCamera(runtime), *[MijiaCamera(runtime, camera) for camera in runtime.cameras.values()]])


def remove_deselected_cameras(hass, entry, cameras):
    import re
    from homeassistant.helpers import entity_registry as er, device_registry as dr
    registry, devices = er.async_get(hass), dr.async_get(hass)
    keep = {entry.data["did"], *cameras}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        match = re.fullmatch(r"([0-9]+)_camera", entity.unique_id)
        if entity.domain != "camera" or entity.platform != DOMAIN or not match or match[1] in keep:
            continue
        registry.async_remove(entity.entity_id)
        device = devices.async_get(entity.device_id) if entity.device_id else None
        if device and device.identifiers == {(DOMAIN, match[1])}:
            remaining = er.async_entries_for_device(registry, device.id)
            if not any(item.config_entry_id == entry.entry_id for item in remaining):
                devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


class DoorbellCamera(DoorbellEntity, Camera):
    _attr_name = "实时画面"
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_use_stream_for_stills = False

    def __init__(self, runtime):
        Camera.__init__(self)
        DoorbellEntity.__init__(self, runtime, "camera")

    @property
    def available(self):
        return not self.runtime.closed and self.runtime.video_enabled

    async def stream_source(self):
        await self.runtime.ensure_video()
        return f"rtsp://127.0.0.1:{self.runtime.media.rtsp_port}/doorbell_live"

    async def async_camera_image(self, width=None, height=None):
        # A dashboard thumbnail must not wake the battery camera repeatedly.
        return None


class MijiaCamera(Camera):
    _attr_has_entity_name = True
    _attr_name = "实时画面"
    _attr_should_poll = False
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_use_stream_for_stills = False

    def __init__(self, runtime, camera):
        from homeassistant.helpers.entity import DeviceInfo
        super().__init__()
        self.runtime, self.camera = runtime, camera
        self._attr_unique_id = camera["did"] + "_camera"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, camera["did"])}, name=camera["name"],
            manufacturer=camera["model"].split(".")[0], model=camera["model"],
            configuration_url=(runtime.entry.data["ha_url"].rstrip("/") + f"/mi-cateye?device={camera['did']}")
                if runtime.entry.data.get("ha_url") else None)

    @property
    def available(self):
        return not self.runtime.closed and self.runtime.video_enabled

    async def stream_source(self):
        source = self.runtime.source_for(self.camera["did"])
        await self.runtime.ensure_video()
        return f"rtsp://127.0.0.1:{self.runtime.media.rtsp_port}/{source}"

    async def async_camera_image(self, width=None, height=None):
        return None
