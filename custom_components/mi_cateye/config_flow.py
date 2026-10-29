"""One configuration wizard for device OAuth and MISS video authorization."""
from __future__ import annotations

import base64
from datetime import timedelta
import hmac
import logging
import json
import re
import secrets
import time
from urllib.parse import urlsplit
from uuid import uuid4

from aiohttp import web
import probatio as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import UnknownFlow
from homeassistant.components import webhook
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.network import get_url
from homeassistant.helpers.system_info import async_get_system_info
from homeassistant.setup import async_setup_component

from .helpers import DOMAIN, make_media
from .media import MediaError
from .receivers import receiver_host
from .session import CLIENT_ID, MODEL, OAuthState
from .vendor.miot.miot_cloud import MIoTOauthClient, MIoTHttpClient

REGIONS = {"cn": "中国大陆", "de": "欧洲", "i2": "印度", "ru": "俄罗斯", "sg": "新加坡", "us": "美国"}
PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
_LOGGER = logging.getLogger(__name__)


def safe_oauth_reason(error):
    """Keep numeric protocol evidence only; cloud messages may contain secrets."""
    text = str(getattr(error, "message", ""))
    if text.startswith("unauthorized(401)"):
        return "http_status=401"
    if match := re.fullmatch(r"invalid http status code, ([1-5][0-9]{2})", text):
        return "http_status=" + match[1]
    prefix = "invalid http response, "
    if text.startswith(prefix):
        try:
            value = json.loads(text[len(prefix):])
        except (ValueError, TypeError):
            return "invalid_response"
        if isinstance(value, dict):
            parts = []
            for key in ("code", "error_code", "status"):
                number = value.get(key)
                if type(number) is int or isinstance(number, str) and re.fullmatch(r"-?[0-9]{1,10}", number):
                    parts.append(f"{key}={number}")
            return ",".join(parts) or "invalid_response"
    return "unclassified"


def ha_base_url(value):
    value = str(value).strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("invalid_ha_url")
    return value


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._data = {"uuid": uuid4().hex}
        self._media = self._oauth = None
        self._choices = {}
        self._hook = self._nonce = self._captcha_nonce = None
        self._oauth_url = None
        self._oauth_complete = self._oauth_claimed = self._finished = self._cleaned = False
        self._reauth_entry = None
        self._timer = None

    async def _begin(self):
        await async_setup_component(self.hass, DOMAIN, {})
        if self._timer is None:
            self._timer = async_call_later(self.hass, 600, self._expire)

    async def _expire(self, _now):
        await self._cleanup()
        try:
            self.hass.config_entries.flow.async_abort(self.flow_id)
        except UnknownFlow:
            pass

    async def async_step_user(self, user_input=None):
        await self._begin()
        if self._cleaned:
            return self.async_abort(reason="setup_expired")
        errors = {}
        default_url = self.hass.config.external_url or self.hass.config.internal_url
        if not default_url:
            try:
                default_url = get_url(self.hass)
            except Exception:
                default_url = ""
        if user_input:
            try:
                self._data["ha_url"] = ha_base_url(user_input["ha_url"])
                self._data["region"] = user_input["region"]
                if self._media is None:
                    self._media = await make_media(self.hass, self._data["uuid"], async_get_clientsession(self.hass))
                    await self._media.start()
                result = await self._media.login(username=user_input["account"], password=user_input["password"])
                return await self._after_video_login(result)
            except (MediaError, ValueError) as err:
                if str(err) in {"backend_not_packaged", "unsupported_host_platform", "backend_missing_or_checksum_mismatch"}:
                    return self.async_abort(reason="backend_unavailable")
                errors["base"] = str(err) if str(err) == "invalid_ha_url" else "video_login_failed"
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("account"): str,
            vol.Required("password"): PASSWORD,
            vol.Required("region", default=self._data.get("region", "cn")): vol.In(REGIONS),
            vol.Required("ha_url", default=self._data.get("ha_url", default_url)): str,
        }), errors=errors)

    async def _after_video_login(self, result):
        if result["status"] == "verify":
            return await self.async_step_verify()
        if result["status"] == "captcha":
            try:
                image = base64.b64decode(result["image"], validate=True)
                content_type = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg" if image.startswith(b"\xff\xd8") else None
                if content_type is None or len(image) > 512000:
                    raise ValueError
                cache = self.hass.data[DOMAIN].setdefault("captchas", {})
                if self._captcha_nonce is not None:
                    cache.pop(self._captcha_nonce, None)
                self._captcha_nonce = secrets.token_hex(24)
                cache[self._captcha_nonce] = (time.monotonic() + 300, image, content_type)
                return await self.async_step_captcha()
            except ValueError:
                return self.async_abort(reason="captcha_unavailable")
        return await self.async_step_device()

    async def async_step_verify(self, user_input=None):
        if self._cleaned:
            return self.async_abort(reason="setup_expired")
        errors = {}
        if user_input:
            try:
                return await self._after_video_login(await self._media.login(verify=user_input["code"]))
            except MediaError:
                errors["base"] = "verification_failed"
        return self.async_show_form(step_id="verify", data_schema=vol.Schema({vol.Required("code"): PASSWORD}), errors=errors)

    async def async_step_captcha(self, user_input=None):
        if self._cleaned:
            return self.async_abort(reason="setup_expired")
        errors = {}
        if user_input:
            try:
                if user_input.get("refresh_captcha") or not user_input.get("code", "").strip():
                    result = await self._media.login(refresh_captcha="true")
                else:
                    result = await self._media.login(captcha=user_input.get("code", "").strip())
                return await self._after_video_login(result)
            except MediaError:
                errors["base"] = "verification_failed"
        path = async_sign_path(self.hass, "/api/mi_cateye/captcha/" + self._captcha_nonce,
                               timedelta(minutes=3), use_content_user=True)
        return self.async_show_form(step_id="captcha", data_schema=vol.Schema({
            vol.Optional("code", default=""): str,
            vol.Optional("refresh_captcha", default=False): bool}),
                                    description_placeholders={"captcha_url": path}, errors=errors)

    async def async_step_device(self, user_input=None):
        if self._cleaned:
            return self.async_abort(reason="setup_expired")
        if not self._choices:
            try:
                self._choices = await self._media.camera_choices(self._data["region"])
            except MediaError:
                return self.async_abort(reason="device_list_unavailable")
        if not self._choices:
            return self.async_abort(reason="no_supported_doorbell")
        if user_input is None and len(self._choices) == 1:
            user_input = {"doorbell": next(iter(self._choices))}
        if user_input:
            self._data.update(self._choices[user_input["doorbell"]])
            await self.async_set_unique_id(self._data["did"])
            self._abort_if_unique_id_configured()
            return await self.async_step_oauth()
        return self.async_show_form(step_id="device", data_schema=vol.Schema({
            vol.Required("doorbell"): vol.In({key: value["name"] + " · " + key[-4:] for key, value in self._choices.items()}),
        }))

    async def async_step_oauth(self, user_input=None):
        await self._begin()
        if self._cleaned:
            return self.async_abort(reason="setup_expired")
        if self._oauth_complete:
            return await self._finish()
        if self._oauth is None:
            self._hook = str(secrets.randbits(64))
            # This public OAuth client is registered for the upstream callback
            # origin, independently of the playback address chosen by the user.
            self._data["redirect_url"] = "http://homeassistant.local:8123" + webhook.async_generate_path(self._hook)
            info = await async_get_system_info(self.hass)
            system_info = (f"hass/{info['version']} ({info['os_name']}/{info['os_version']};"
                           f" {info['arch']}; {info['installation_type']})")
            self._oauth = MIoTOauthClient(client_id=CLIENT_ID, redirect_url=self._data["redirect_url"],
                                          cloud_server=self._data["region"], uuid=self._data["uuid"],
                                          system_info=system_info)
            self._nonce = self._oauth.state
            self._oauth_url = self._oauth.gen_auth_url(redirect_url=self._data["redirect_url"])
            webhook.async_register(self.hass, DOMAIN, "Doorbell authorization", self._hook, self._callback,
                                   allowed_methods=("GET",), local_only=False)
        return self.async_show_form(step_id="oauth", data_schema=vol.Schema({}),
                                    description_placeholders={"authorization_url": self._oauth_url},
                                    errors={"base": "authorization_pending"} if user_input is not None else {})

    async def _callback(self, hass, webhook_id, request):
        state = request.query.get("state", "")
        code = request.query.get("code", "")
        if self._cleaned or self._oauth_claimed or webhook_id != self._hook or not code or len(code) > 4096:
            return web.Response(status=404)
        if not hmac.compare_digest(state.encode(), self._nonce.encode()):
            return web.Response(status=404)
        self._oauth_claimed = True
        http = None
        stage = "token_exchange"
        try:
            auth = OAuthState.parse(await self._oauth.get_access_token_async(code))
            stage = "device_query"
            http = MIoTHttpClient(cloud_server=self._data["region"], client_id=CLIENT_ID,
                                  access_token=auth.access_token, uuid=self._data["uuid"])
            devices = await http.get_devices_with_dids_async([self._data["did"]])
            stage = "device_match"
            if (devices or {}).get(self._data["did"], {}).get("model") != MODEL:
                raise ValueError
            self._data["oauth"] = auth.private_data()
            self._oauth_complete = True
            return web.Response(text="授权完成，请关闭此页，返回 Home Assistant 点击下一步。", content_type="text/plain",
                                headers={"Cache-Control": "no-store"})
        except Exception as err:
            self._oauth_claimed = False
            # Never log exception text, cloud payloads, URLs, codes or tokens.
            kind = type(err).__name__
            reason = safe_oauth_reason(err)
            _LOGGER.warning("Authorization failed: stage=%s exception=%s reason=%s", stage, kind, reason)
            self._authorization_error = stage
            labels = {"token_exchange": "授权凭据交换", "device_query": "猫眼设备查询", "device_match": "所选猫眼匹配"}
            return web.Response(text=f"授权未完成：{labels[stage]}失败（{kind}; {reason}）。请返回配置页重新打开授权链接；此提示不代表账号一定无权限。", status=400,
                                content_type="text/plain", headers={"Cache-Control": "no-store"})
        finally:
            if http is not None:
                await http.deinit_async()

    async def async_step_reauth(self, entry_data):
        self._reauth_entry = self._get_reauth_entry()
        self._data = dict(self._reauth_entry.data)
        return await self.async_step_oauth()

    async def _finish(self):
        self._finished = True
        await self._cleanup()
        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=self._data)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")
        return self.async_create_entry(title=self._data["name"], data=self._data)

    async def _cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        if self._timer is not None:
            self._timer()
            self._timer = None
        if self._hook is not None:
            webhook.async_unregister(self.hass, self._hook)
        if self._captcha_nonce is not None:
            self.hass.data.get(DOMAIN, {}).get("captchas", {}).pop(self._captcha_nonce, None)
        try:
            if self._media is not None:
                await self._media.stop()
                if not self._finished and self._reauth_entry is None:
                    path = self._media.directory / "media.json"
                    await self.hass.async_add_executor_job(lambda: path.unlink(missing_ok=True))
        finally:
            if self._oauth is not None:
                await self._oauth.deinit_async()

    @callback
    def async_remove(self):
        self.hass.async_create_task(self._cleanup(), "doorbell setup cleanup")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input:
            try:
                for key in ("tv_host", "xiaoai_host"):
                    if user_input.get(key):
                        receiver_host(user_input[key])
                browser = user_input.get("phone_browser_id", "")
                if browser and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", browser):
                    raise ValueError("invalid_phone_browser")
                return self.async_create_entry(title="", data=user_input)
            except ValueError as err:
                errors["base"] = "invalid_phone_browser" if str(err) == "invalid_phone_browser" else "invalid_receiver_address"
        current = self.config_entry.options
        services = self.hass.services.async_services().get("notify", {})
        phones = {"": "不推送到手机", **{key: key.removeprefix("mobile_app_").replace("_", " ")
                                         for key in services if key.startswith("mobile_app_")}}
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Optional("enable_video", default=current.get("enable_video", True)): bool,
            vol.Optional("auto_notify", default=current.get("auto_notify", True)): bool,
            vol.Optional("tv_host", default=current.get("tv_host", "")): str,
            vol.Optional("xiaoai_host", default=current.get("xiaoai_host", "")): str,
            vol.Optional("phone_browser_id", default=current.get("phone_browser_id", "")): str,
            vol.Optional("phone_service", default=current.get("phone_service", "") if current.get("phone_service", "") in phones else ""): vol.In(phones),
        }), errors=errors)
