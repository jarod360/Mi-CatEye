from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from mi_cateye.binary_sensor import RingActive


@pytest.mark.asyncio
async def test_ring_expires_retrigger_resets_and_unload_cancels():
    runtime = SimpleNamespace(entry=SimpleNamespace(data={"did":"123"}, title="Door"), data={})
    entity = RingActive(runtime)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    cancel1, cancel2 = MagicMock(), MagicMock()
    with patch("mi_cateye.binary_sensor.async_call_later", side_effect=[cancel1, cancel2]) as timer:
        entity._changed("pass", {})
        assert not entity.is_on
        entity._changed("ring", {})
        assert entity.is_on
        entity._changed("ring", {})
        cancel1.assert_called_once()
        assert timer.call_args.args[1] == 60
        entity._expire(None)
        assert not entity.is_on
        entity._cancel_expiry = cancel2
        await entity.async_will_remove_from_hass()
        cancel2.assert_called_once()


@pytest.mark.asyncio
async def test_real_ha_timer_publishes_off_in_event_loop(hass, monkeypatch):
    import asyncio
    from homeassistant.helpers.event import async_call_later as real_timer
    from homeassistant.core import HassJob, HassJobType
    runtime=SimpleNamespace(entry=SimpleNamespace(data={"did":"123"},title="Door"),data={})
    entity=RingActive(runtime)
    entity.hass=hass
    entity.entity_id="binary_sensor.test_doorbell_ring"
    assert HassJob(entity._expire).job_type is HassJobType.Callback
    monkeypatch.setattr("mi_cateye.binary_sensor.async_call_later",lambda h,d,fn:real_timer(h,0.01,fn))
    entity._changed("ring",{})
    assert hass.states.get(entity.entity_id).state == "on"
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert hass.states.get(entity.entity_id).state == "off"
