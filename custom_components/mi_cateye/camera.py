from homeassistant.components.camera import Camera, CameraEntityFeature
from .entity import DoorbellEntity
from .helpers import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([DoorbellCamera(hass.data[DOMAIN]["runtime"])])


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
