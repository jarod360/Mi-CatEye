from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from mi_cateye.event import DoorbellEvent


@pytest.mark.parametrize("kind,name", [("ring","门铃"),("pass","经过"),("linger","停留")])
def test_event_entity_isolated_and_ring_id_unchanged(kind, name):
    runtime=SimpleNamespace(entry=SimpleNamespace(data={"did":"123"},title="Door"),data={})
    entity=DoorbellEvent(runtime,kind,name)
    entity._trigger_event=MagicMock()
    entity.async_write_ha_state=MagicMock()
    for candidate in ("ring","pass","linger"):
        entity._changed(candidate,{"received_at":"test"})
    entity._trigger_event.assert_called_once_with(kind,{"received_at":"test"})
    assert entity.unique_id == "123_"+kind
    assert entity.name == name
