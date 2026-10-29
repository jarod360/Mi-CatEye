from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE
from .entity import DoorbellEntity
from .helpers import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Battery(hass.data[DOMAIN]["runtime"])])


class Battery(DoorbellEntity, SensorEntity):
    _attr_name = "电量"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, runtime):
        super().__init__(runtime, "battery")

    @property
    def native_value(self):
        return self.runtime.data.get("battery")
