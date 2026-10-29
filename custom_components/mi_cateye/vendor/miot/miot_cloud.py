# -*- coding: utf-8 -*-
"""
Copyright (C) 2024 Xiaomi Corporation.

The ownership and intellectual property rights of Xiaomi Home Assistant
Integration and related Xiaomi cloud service API interface provided under this
license, including source code and object code (collectively, "Licensed Work"),
are owned by Xiaomi. Subject to the terms and conditions of this License, Xiaomi
hereby grants you a personal, limited, non-exclusive, non-transferable,
non-sublicensable, and royalty-free license to reproduce, use, modify, and
distribute the Licensed Work only for your use of Home Assistant for
non-commercial purposes. For the avoidance of doubt, Xiaomi does not authorize
you to use the Licensed Work for any other purpose, including but not limited
to use Licensed Work to develop applications (APP), Web services, and other
forms of software.

You may reproduce and distribute copies of the Licensed Work, with or without
modifications, whether in source or object form, provided that you must give
any other recipients of the Licensed Work a copy of this License and retain all
copyright and disclaimers.

Xiaomi provides the Licensed Work on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied, including, without
limitation, any warranties, undertakes, or conditions of TITLE, NO ERROR OR
OMISSION, CONTINUITY, RELIABILITY, NON-INFRINGEMENT, MERCHANTABILITY, or
FITNESS FOR A PARTICULAR PURPOSE. In any event, you are solely responsible
for any direct, indirect, special, incidental, or consequential damages or
losses arising from the use or inability to use the Licensed Work.

Xiaomi reserves all rights not expressly granted to you in this License.
Except for the rights expressly granted by Xiaomi under this License, Xiaomi
does not authorize you in any form to use the trademarks, copyrights, or other
forms of intellectual property rights of Xiaomi and its affiliates, including,
without limitation, without obtaining other written permission from Xiaomi, you
shall not use "Xiaomi", "Mijia" and other words related to Xiaomi or words that
may make the public associate with Xiaomi in any form to publicize or promote
the software or hardware devices that use the Licensed Work.

Xiaomi has the right to immediately terminate all your authorization under this
License in the event:
1. You assert patent invalidation, litigation, or other claims against patents
or other intellectual property rights of Xiaomi or its affiliates; or,
2. You make, have made, manufacture, sell, or offer to sell products that knock
off Xiaomi or its affiliates' products.

MIoT http client.
"""

# Local extraction for a doorbell-only Home Assistant component; upstream license retained.
import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlencode
import aiohttp
from .common import calc_group_id
from .const import (
    UNSUPPORTED_MODELS,
    DEFAULT_OAUTH2_API_HOST,
    INTEGRATION_VERSION,
    MIHOME_HTTP_API_TIMEOUT,
    OAUTH2_AUTH_URL)
from .miot_error import MIoTErrorCode, MIoTHttpError, MIoTOauthError


_LOGGER = logging.getLogger(__name__)


TOKEN_EXPIRES_TS_RATIO = 0.7


class MIoTOauthClient:
    """oauth agent url, default: product env."""
    _main_loop: asyncio.AbstractEventLoop
    _session: aiohttp.ClientSession
    _oauth_host: str
    _client_id: int
    _redirect_url: str
    _device_id: str
    _user_agent: str
    _state: str

    def __init__(
            self, client_id: str, redirect_url: str, cloud_server: str,
            uuid: str, system_info: str = '',
            loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        self._main_loop = loop or asyncio.get_running_loop()
        if client_id is None or client_id.strip() == '':
            raise MIoTOauthError('invalid client_id')
        if not redirect_url:
            raise MIoTOauthError('invalid redirect_url')
        if not cloud_server:
            raise MIoTOauthError('invalid cloud_server')
        if not uuid:
            raise MIoTOauthError('invalid uuid')

        self._client_id = int(client_id)
        self._redirect_url = redirect_url
        if cloud_server == 'cn':
            self._oauth_host = DEFAULT_OAUTH2_API_HOST
        else:
            self._oauth_host = f'{cloud_server}.{DEFAULT_OAUTH2_API_HOST}'
        self._device_id = f'ha.{uuid}'
        self._user_agent = (
            f'ha_xiaomi_home/{INTEGRATION_VERSION}'
            f' {system_info}'
            f' client/{self._device_id}')
        self._state = hashlib.sha1(
            f'd={self._device_id}'.encode('utf-8')).hexdigest()
        self._session = aiohttp.ClientSession(loop=self._main_loop)

    @property
    def state(self) -> str:
        return self._state

    async def deinit_async(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def set_redirect_url(self, redirect_url: str) -> None:
        if not isinstance(redirect_url, str) or redirect_url.strip() == '':
            raise MIoTOauthError('invalid redirect_url')
        self._redirect_url = redirect_url

    def gen_auth_url(
        self,
        redirect_url: Optional[str] = None,
        state: Optional[str] = None,
        scope: Optional[list] = None,
        skip_confirm: Optional[bool] = False,
    ) -> str:
        """get auth url

        Args:
            redirect_url
            state
            scope (list, optional):
                开放数据接口权限 ID，可以传递多个，用空格分隔，具体值可以参考开放
                [数据接口权限列表](https://dev.mi.com/distribute/doc/details?pId=1518).
                Defaults to None.\n
            skip_confirm (bool, optional):
                默认值为true，授权有效期内的用户在已登录情况下，不显示授权页面，直接通过。
                如果需要用户每次手动授权，设置为false. Defaults to True.\n

        Returns:
            str: _description_
        """
        params: dict = {
            'redirect_uri': redirect_url or self._redirect_url,
            'client_id': self._client_id,
            'response_type': 'code',
            'device_id': self._device_id,
            'state': self._state
        }
        if state:
            params['state'] = state
        if scope:
            params['scope'] = ' '.join(scope).strip()
        params['skip_confirm'] = skip_confirm
        encoded_params = urlencode(params)

        return f'{OAUTH2_AUTH_URL}?{encoded_params}'

    async def __get_token_async(self, data) -> dict:
        http_res = await self._session.get(
            url=f'https://{self._oauth_host}/app/v2/ha/oauth/get_token',
            params={'data': json.dumps(data)},
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': self._user_agent,
            },
            timeout=MIHOME_HTTP_API_TIMEOUT
        )
        if http_res.status == 401:
            raise MIoTOauthError(
                'unauthorized(401)', MIoTErrorCode.CODE_OAUTH_UNAUTHORIZED)
        if http_res.status != 200:
            raise MIoTOauthError(
                f'invalid http status code, {http_res.status}')

        res_str = await http_res.text()
        res_obj = json.loads(res_str)
        if (
            not res_obj
            or res_obj.get('code', None) != 0
            or 'result' not in res_obj
            or not all(
                key in res_obj['result']
                for key in ['access_token', 'refresh_token', 'expires_in'])
        ):
            raise MIoTOauthError(f'invalid http response, {res_str}')

        return {
            **res_obj['result'],
            'expires_ts': int(
                time.time() +
                (res_obj['result'].get('expires_in', 0)*TOKEN_EXPIRES_TS_RATIO))
        }

    async def get_access_token_async(self, code: str) -> dict:
        """get access token by authorization code

        Args:
            code (str): auth code

        Returns:
            str: _description_
        """
        if not isinstance(code, str):
            raise MIoTOauthError('invalid code')

        return await self.__get_token_async(data={
            'client_id': self._client_id,
            'redirect_uri': self._redirect_url,
            'code': code,
            'device_id': self._device_id
        })

    async def refresh_access_token_async(self, refresh_token: str) -> dict:
        """get access token  by refresh token.

        Args:
            refresh_token (str): refresh_token

        Returns:
            str: _description_
        """
        if not isinstance(refresh_token, str):
            raise MIoTOauthError('invalid refresh_token')

        return await self.__get_token_async(data={
            'client_id': self._client_id,
            'redirect_uri': self._redirect_url,
            'refresh_token': refresh_token,
        })


class MIoTHttpClient:
    """MIoT http client."""

    GET_PROP_AGGREGATE_INTERVAL: float = 0.2

    GET_PROP_MAX_REQ_COUNT = 150

    _main_loop: asyncio.AbstractEventLoop

    _session: aiohttp.ClientSession

    _host: str

    _base_url: str

    _client_id: str

    _access_token: str

    _user_agent: str

    _get_prop_timer: Optional[asyncio.TimerHandle]

    _get_prop_list: dict[str, dict]

    def __init__(
            self, cloud_server: str, client_id: str, access_token: str,
            uuid: str, system_info: str = '',
            loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        self._main_loop = loop or asyncio.get_running_loop()
        self._host = DEFAULT_OAUTH2_API_HOST
        self._base_url = ''
        self._client_id = ''
        self._access_token = ''

        self._get_prop_timer = None
        self._get_prop_list = {}

        if (
            not isinstance(cloud_server, str)
            or not isinstance(client_id, str)
            or not isinstance(access_token, str)
            or not isinstance(uuid, str)
        ):
            raise MIoTHttpError('invalid params')

        self._user_agent = (
            f'ha_xiaomi_home/{INTEGRATION_VERSION}'
            f' {system_info}'
            f' client/ha.{uuid}')
        self.update_http_header(
            cloud_server=cloud_server, client_id=client_id,
            access_token=access_token)

        self._session = aiohttp.ClientSession(loop=self._main_loop)

    async def deinit_async(self) -> None:
        if self._get_prop_timer:
            self._get_prop_timer.cancel()
            self._get_prop_timer = None
        for item in self._get_prop_list.values():
            fut: Optional[asyncio.Future] = item.get('fut', None)
            if fut:
                fut.cancel()
        self._get_prop_list.clear()
        if self._session and not self._session.closed:
            await self._session.close()

    def update_http_header(
        self, cloud_server: Optional[str] = None,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None
    ) -> None:
        if isinstance(cloud_server, str):
            if cloud_server != 'cn':
                self._host = f'{cloud_server}.{DEFAULT_OAUTH2_API_HOST}'
            self._base_url = f'https://{self._host}'
        if isinstance(client_id, str):
            self._client_id = client_id
        if isinstance(access_token, str):
            self._access_token = access_token

    @property
    def __api_request_headers(self) -> dict:
        return {
            'Host': self._host,
            'X-Client-BizId': 'haapi',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer{self._access_token}',
            'X-Client-AppId': self._client_id,
            'User-Agent': self._user_agent,
        }

    async def __mihome_api_post_async(
        self, url_path: str, data: dict,
        timeout: int = MIHOME_HTTP_API_TIMEOUT
    ) -> dict:
        http_res = await self._session.post(
            url=f'{self._base_url}{url_path}',
            json=data,
            headers=self.__api_request_headers,
            timeout=timeout)
        if http_res.status == 401:
            raise MIoTHttpError(
                'mihome api get failed, unauthorized(401)',
                MIoTErrorCode.CODE_HTTP_INVALID_ACCESS_TOKEN)
        if http_res.status != 200:
            raise MIoTHttpError(
                f'mihome api post failed, {http_res.status}, '
                f'{url_path}, {data}')
        res_str = await http_res.text()
        res_obj: dict = json.loads(res_str)
        if res_obj.get('code', None) != 0:
            raise MIoTHttpError(
                f'invalid response code, {res_obj.get("code",None)}, '
                f'{res_obj.get("message","")}')
        _LOGGER.debug(
            'mihome api post, %s%s, %s -> %s',
            self._base_url, url_path, data, res_obj)
        return res_obj

    async def __get_device_list_page_async(
        self, dids: list[str], start_did: Optional[str] = None
    ) -> dict[str, dict]:
        req_data: dict = {
            'limit': 200,
            'get_split_device': True,
            'get_third_device': True,
            'dids': dids
        }
        if start_did:
            req_data['start_did'] = start_did
        device_infos: dict = {}
        res_obj = await self.__mihome_api_post_async(
            url_path='/app/v2/home/device_list_page',
            data=req_data
        )
        if 'result' not in res_obj:
            raise MIoTHttpError('invalid response result')
        res_obj = res_obj['result']

        for device in res_obj.get('list', []) or []:
            did = device.get('did', None)
            name = device.get('name', None)
            urn = device.get('spec_type', None)
            model = device.get('model', None)
            if did is None or name is None:
                _LOGGER.info(
                    'invalid device, cloud, %s', device)
                continue
            if urn is None or model is None:
                _LOGGER.info(
                    'missing the urn|model field, cloud, %s', device)
                continue
            if did.startswith('miwifi.'):
                # The miwifi.* routers defined SPEC functions, but none of them
                # were implemented.
                _LOGGER.info('ignore miwifi.* device, cloud, %s', did)
                continue
            if model in UNSUPPORTED_MODELS:
                _LOGGER.info('ignore unsupported model %s, cloud, %s',
                             model, did)
                continue
            device_infos[did] = {
                'did': did,
                'uid': device.get('uid', None),
                'name': name,
                'urn': urn,
                'model': model,
                'connect_type': device.get('pid', -1),
                'token': device.get('token', None),
                'online': device.get('isOnline', False),
                'icon': device.get('icon', None),
                'parent_id': device.get('parent_id', None),
                'manufacturer': model.split('.')[0],
                # 2: xiao-ai, 1: general speaker
                'voice_ctrl': device.get('voice_ctrl', 0),
                'rssi': device.get('rssi', None),
                'owner': device.get('owner', None),
                'pid': device.get('pid', None),
                'local_ip': device.get('local_ip', None),
                'ssid': device.get('ssid', None),
                'bssid': device.get('bssid', None),
                'order_time': device.get('orderTime', 0),
                'fw_version': device.get('extra', {}).get(
                    'fw_version', None)
            }

        next_start_did = res_obj.get('next_start_did', None)
        if res_obj.get('has_more', False) and next_start_did:
            device_infos.update(await self.__get_device_list_page_async(
                dids=dids, start_did=next_start_did))

        return device_infos

    async def get_devices_with_dids_async(
        self, dids: list[str]
    ) -> Optional[dict[str, dict]]:
        results: list[dict[str, dict]] = await asyncio.gather(
            *[self.__get_device_list_page_async(dids=dids[index:index+150])
                for index in range(0, len(dids), 150)])
        devices = {}
        for result in results:
            if result is None:
                return None
            devices.update(result)
        return devices

    async def get_props_async(self, params: list) -> list:
        """
        params = [{"did": "xxxx", "siid": 2, "piid": 1},
                    {"did": "xxxxxx", "siid": 2, "piid": 2}]
        """
        res_obj = await self.__mihome_api_post_async(
            url_path='/app/v2/miotspec/prop/get',
            data={
                'datasource': 1,
                'params': params
            },
        )
        if 'result' not in res_obj:
            raise MIoTHttpError('invalid response result')
        return res_obj['result']

