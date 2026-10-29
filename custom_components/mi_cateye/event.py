from homeassistant.components.event import EventEntity
from .entity import DoorbellEntity
from .helpers import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN]["runtime"]
    async_add_entities([DoorbellEvent(runtime, kind, name) for kind, name in
                        (("ring", "门铃"), ("pass", "经过"), ("linger", "停留"))])


class DoorbellEvent(DoorbellEntity, EventEntity):

    def __init__(self, runtime, kind, name):
        super().__init__(runtime, kind)
        self.kind = kind
        self._attr_name = name
        self._attr_event_types = [kind]

    def _changed(self, kind, value):
        if kind == self.kind:
            self._trigger_event(kind, value)
        self.async_write_ha_state()
