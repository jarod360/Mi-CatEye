from homeassistant.helpers.entity import Entity, DeviceInfo
from .helpers import DOMAIN


class DoorbellEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime, key):
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.data['did']}_{key}"
        device = runtime.data.get("device", {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.data["did"])}, name=runtime.entry.title,
            manufacturer="Loock", model="loock.cateye.v02", sw_version=device.get("fw_version"),
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.listen(self._changed))

    def _changed(self, kind, value):
        self.async_write_ha_state()
