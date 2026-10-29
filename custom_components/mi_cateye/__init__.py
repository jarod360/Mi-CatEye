"""Candidate unified doorbell integration; not enabled on the live system."""
from __future__ import annotations

DOMAIN = "mi_cateye"


async def async_setup(hass, config):
    state = hass.data.setdefault(DOMAIN, {})
    if state.get("views_registered"):
        return True
    from homeassistant.components import frontend
    from .helpers import ASSETS
    from .views import RawView, MseView, PlayerView, PanelScriptView, VoiceView, CaptchaView
    from .recordings import RecordingView, RecordingsScriptView, register_recording_commands
    template = await hass.async_add_executor_job(lambda: (ASSETS / "player.html").read_text(encoding="utf-8"))
    for view in (RawView(hass), MseView(hass), PlayerView(hass, template), PanelScriptView(), VoiceView(), CaptchaView(hass),
                 RecordingView(hass), RecordingsScriptView()):
        hass.http.register_view(view)
    frontend.async_register_built_in_panel(
        hass, component_name="custom", frontend_url_path="mi-cateye", show_in_sidebar=False,
        config={"_panel_custom": {"name": "mi-cateye-phone-panel",
                                 "module_url": "/api/mi_cateye/phone-panel.js?v=001",
                                 "embed_iframe": False, "trust_external": False}},
    )
    frontend.async_register_built_in_panel(
        hass, component_name="custom", frontend_url_path="mi-cateye-recordings", show_in_sidebar=False,
        config={"_panel_custom": {"name": "mi-cateye-recordings-panel",
                                 "module_url": "/api/mi_cateye/recordings-panel.js?v=008",
                                 "embed_iframe": False, "trust_external": False}},
    )
    register_recording_commands(hass)
    state["views_registered"] = True
    await _register_services(hass)
    return True


async def _register_services(hass):
    import probatio as vol
    from homeassistant.exceptions import HomeAssistantError
    from .receivers import show_tv, show_xiaoai, notify_phone
    async def handle(call):
        runtime = hass.data[DOMAIN].get("runtime")
        if runtime is None or runtime.closed or call.data["config_entry_id"] != runtime.entry.entry_id:
            raise HomeAssistantError("门铃实例暂不可用")
        try:
            await {"show_tv": show_tv, "show_xiaoai": show_xiaoai, "notify_phone": notify_phone}[call.service](runtime)
        except (ValueError, OSError, TimeoutError):
            raise HomeAssistantError("接收端暂不可用，请检查电源和网络") from None
    for action in ("show_tv", "show_xiaoai", "notify_phone"):
        hass.services.async_register(DOMAIN, action, handle, schema=vol.Schema({vol.Required("config_entry_id"): str}))


async def async_setup_entry(hass, entry):
    from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
    from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .helpers import make_media
    from .runtime import Runtime
    from .media import MediaError
    from .session import SessionError
    state = hass.data.setdefault(DOMAIN, {})
    previous = state.get("runtime")
    if previous is not None and not previous.closed:
        raise ConfigEntryNotReady("已有门铃实例正在运行")
    runtime = None
    try:
        client = async_get_clientsession(hass)
        media = await make_media(hass, entry.data["uuid"], client)
        runtime = Runtime(hass, entry, media, client)
        state["runtime"] = runtime
        await runtime.start()
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.EVENT, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CAMERA])
    except (MediaError, SessionError) as err:
        if runtime is not None:
            await runtime.close()
        state.pop("runtime", None)
        if str(err) in {"authorization_missing", "authorization_incomplete", "authorization_expiry_invalid", "authorization_expired", "authorization_invalid"}:
            raise ConfigEntryAuthFailed("门铃设备授权需要重新确认") from None
        raise ConfigEntryNotReady("门铃连接暂不可用：" + str(err)) from None
    except BaseException:
        if runtime is not None:
            await runtime.close()
        state.pop("runtime", None)
        raise
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, runtime.close))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    runtime.initial_options = dict(entry.options)
    return True


async def _async_options_updated(hass, entry):
    runtime = hass.data[DOMAIN].get("runtime")
    if runtime is not None and runtime.initial_options != dict(entry.options):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    from homeassistant.const import Platform
    unloaded = await hass.config_entries.async_unload_platforms(entry, [Platform.EVENT, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CAMERA])
    if unloaded:
        runtime = hass.data[DOMAIN].pop("runtime", None)
        if runtime is not None:
            await runtime.close()
    return unloaded
