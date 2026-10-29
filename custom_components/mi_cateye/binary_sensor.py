from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later
from .entity import DoorbellEntity
from .helpers import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN]["runtime"]
    async_add_entities([Connection(runtime), Online(runtime), RingActive(runtime)])


class RingActive(DoorbellEntity, BinarySensorEntity):
    """A bounded ring indicator for dashboard conditions, without legacy polling."""
    _attr_name = "门铃正在响"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_is_on = False

    def __init__(self, runtime):
        super().__init__(runtime, "ring_active")
        self._cancel_expiry = None

    def _changed(self, kind, value):
        if kind == "ring":
            if self._cancel_expiry is not None:
                self._cancel_expiry()
            self._attr_is_on = True
            self._cancel_expiry = async_call_later(self.hass, 60, self._expire)
        super()._changed(kind, value)

    @callback
    def _expire(self, _now):
        self._cancel_expiry = None
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None


class Connection(DoorbellEntity, BinarySensorEntity):
    _attr_name = "事件连接"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime):
        super().__init__(runtime, "connection")

    @property
    def is_on(self):
        return self.runtime.data.get("connection", False)


class Online(DoorbellEntity, BinarySensorEntity):
    _attr_name = "云端在线"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, runtime):
        super().__init__(runtime, "online")

    @property
    def is_on(self):
        value = self.runtime.data.get("online")
        return self.runtime.data.get("device", {}).get("online") if value is None else value
