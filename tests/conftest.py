import sys
from pathlib import Path
for parent in Path(__file__).resolve().parents:
    if (parent / "custom_components" / "mi_cateye").is_dir():
        sys.path.insert(0, str(parent / "custom_components"))
        break

# The upstream plugin imports the Linux runner (fcntl). On Windows, use
# its real-HA context manager directly; CI uses the standard Linux plugin.
if sys.platform == "win32":
    import pytest_asyncio
    from pytest_homeassistant_custom_component.common import async_test_home_assistant
    @pytest_asyncio.fixture
    async def hass(tmp_path):
        async with async_test_home_assistant(config_dir=str(tmp_path)) as instance:
            yield instance
