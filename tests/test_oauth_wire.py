import hashlib
import json
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from mi_cateye.vendor.miot.miot_cloud import MIoTOauthClient


@pytest.mark.asyncio
async def test_real_sdk_auth_and_exchange_share_device_redirect_and_state():
    client = MIoTOauthClient(client_id="2882303761520251711", cloud_server="cn", uuid="a"*32,
                            redirect_url="http://homeassistant.local:8123/api/webhook/1234567890",
                            system_info="hass/2026.10.4 (Linux/test; x86_64; Home Assistant OS)")
    try:
        auth = parse_qs(urlsplit(client.gen_auth_url()).query)
        expected = hashlib.sha1(("d=ha."+"a"*32).encode()).hexdigest()
        assert auth["state"] == [expected]
        response = SimpleNamespace(status=200, text=AsyncMock(return_value=json.dumps({
            "code":0, "result":{"access_token":"test-access", "refresh_token":"test-refresh", "expires_in":3600}})))
        get = AsyncMock(return_value=response)
        client._session.get = get
        await client.get_access_token_async("test-authorization-code")
        kwargs = get.call_args.kwargs
        body = json.loads(kwargs["params"]["data"])
        assert body["device_id"] == auth["device_id"][0]
        assert body["redirect_uri"] == auth["redirect_uri"][0]
        assert str(body["client_id"]) == auth["client_id"][0]
        assert "hass/2026.10.4" in kwargs["headers"]["User-Agent"]
    finally:
        await client.deinit_async()
