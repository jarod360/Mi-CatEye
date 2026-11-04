from types import SimpleNamespace

import pytest
from mi_cateye.helpers import account_title
from mi_cateye.entity import DoorbellEntity


def test_account_title_masks_identifier_and_allows_display_name():
    assert account_title({"media_user_id": "12345678"}) == "米家账号 · 尾号 5678"
    assert account_title({"media_user_id": "12345678"}, "  家里的米家  ") == "家里的米家"
    assert account_title({}) == "米家账号"
    with pytest.raises(ValueError):
        account_title({}, "invalid\nlabel")


def test_account_group_title_does_not_rename_physical_doorbell():
    runtime = SimpleNamespace(entry=SimpleNamespace(data={"did": "123", "name": "入户门猫眼"}, title="家里的米家"), data={})
    entity = DoorbellEntity(runtime, "camera")
    assert entity.device_info["name"] == "入户门猫眼"
    assert entity.unique_id == "123_camera"
