"""Tests for the API client, run against a local stand-in for the service."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from yarl import URL

from custom_components.cocoro_wash import api
from custom_components.cocoro_wash.api import (
    ApiError,
    AuthError,
    CocoroWashClient,
    CocoroWashConnectionError,
    DeviceUnreachableError,
    InvalidCredentialsError,
)

from . import DEVICE_ID, DRYING_PROPERTIES

EMAIL = "user@example.com"
PASSWORD = "correct horse"
STATE = "state-token"


def _form(extra: str = "") -> web.Response:
    page = (
        '<html><body><form method="POST" data-form-primary="true">'
        f'<input type="hidden" name="state" value="{STATE}"/>'
        '<input type="email" name="username" value=""/>'
        f"{extra}</form></body></html>"
    )
    return web.Response(text=page, content_type="text/html")


class FakeService:
    """Mimics the login pages and the API closely enough to exercise the client."""

    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.logins = 0
        self.sensor_queries: list[str] = []
        self.sensor_response: dict[str, Any] | None = None
        self.app = web.Application()
        self.app.add_routes(
            [
                web.get("/v1/cocoro-wash/login", self.login),
                web.get("/authorize", self.authorize),
                web.get("/u/login/identifier", self.page),
                web.post("/u/login/identifier", self.identifier),
                web.get("/u/login/password", self.page),
                web.post("/u/login/password", self.password),
                web.get("/v1/cocoro-wash/login/callback/cocoromembers", self.callback),
                web.get("/wash/", self.page),
                web.get("/v1/cocoro-wash/devices/cocoro-home", self.devices),
                web.get("/v1/cocoro-wash/deviceinfo", self.device_info),
                web.get("/v1/cocoro-wash/sensors", self.sensors),
                web.get("/v1/cocoro-wash/objects", self.objects),
            ]
        )

    async def login(self, request: web.Request) -> web.Response:
        return web.json_response({"redirectUrl": str(request.url.origin() / "authorize")})

    async def authorize(self, request: web.Request) -> web.Response:
        raise web.HTTPFound(f"/u/login/identifier?state={STATE}")

    async def page(self, request: web.Request) -> web.Response:
        return _form()

    async def identifier(self, request: web.Request) -> web.Response:
        form = await request.post()
        # The real page answers non-browser clients with a security challenge.
        if "Mozilla" not in request.headers.get("User-Agent", "") or form.get("state") != STATE:
            return web.Response(status=400, text="challenge", content_type="text/html")
        raise web.HTTPFound(f"/u/login/password?state={STATE}")

    async def password(self, request: web.Request) -> web.Response:
        form = await request.post()
        if form.get("username") != EMAIL or form.get("password") != PASSWORD:
            return web.Response(status=400, text=_form().text, content_type="text/html")
        raise web.HTTPFound(f"/v1/cocoro-wash/login/callback/cocoromembers?code=c&state={STATE}")

    async def callback(self, request: web.Request) -> web.Response:
        self.logins += 1
        token = f"session-{self.logins}"
        self.sessions.add(token)
        response = web.HTTPFound("/wash/?from=bf&login=success")
        response.set_cookie("jsessionid", token, path="/v1/cocoro-wash")
        raise response

    def _authorize(self, request: web.Request) -> None:
        if request.cookies.get("jsessionid") not in self.sessions:
            raise web.HTTPUnauthorized(
                text='{"detail": "Signature has expired.", "status": 401, "title": "Unauthorized"}',
                content_type="application/json",
            )

    async def devices(self, request: web.Request) -> web.Response:
        self._authorize(request)
        devices = [
            {"device_id": DEVICE_ID, "object_id": "0x03d301"},
            {"device_id": "b" * 64, "object_id": "0x013001"},
        ]
        return web.json_response(
            {"devices_cocorohome_003": {"status": 200, "body": {"devices": devices}}}
        )

    async def device_info(self, request: web.Request) -> web.Response:
        self._authorize(request)
        body = {
            "device_name": "Laundry",
            "model_name": "ES-W114",
            "place": "Utility room",
            "uniq_id": "aa-bb-cc-dd-ee-ff",
            "events": [
                {
                    "event_key": "echonet_access",
                    "value": [
                        {"epc": "0xe2", "access_rule": ["get", "inf"]},
                        {"epc": "0xED", "access_rule": ["get"]},
                        {"epc": "0xE4", "access_rule": ["set"]},
                    ],
                }
            ],
        }
        return web.json_response({"deviceinfo_010": {"status": 200, "body": body}})

    async def sensors(self, request: web.Request) -> web.Response:
        self._authorize(request)
        self.sensor_queries.append(request.query["epc"])
        if self.sensor_response is not None:
            return web.json_response({"sensors_021": self.sensor_response})
        data = [
            {epc: value, "time": "2026-11-23T09:00:50+00:00"}
            for epc, value in DRYING_PROPERTIES.items()
        ]
        return web.json_response({"sensors_021": {"status": 200, "body": {"data": data}}})

    async def objects(self, request: web.Request) -> web.Response:
        self._authorize(request)
        assert request.query["count"] == "1"
        assert request.query["epc"] == "0xE2+0xED+0xB0"
        # One row per property, plus an older stray row that must lose.
        data = [
            {"0xE2": "0x53", "time": "2026-11-23T09:46:26+00:00"},
            {"0xE2": "0x54", "time": "2026-11-23T09:55:46+00:00"},
            {"0xED": "0x0002", "time": "2026-11-23T09:45:02+00:00"},
            {"0xb0": "0x42", "time": "2026-11-23T09:56:07+00:00"},
        ]
        return web.json_response(
            {"objects_020": {"status": 200, "body": {"count": 4, "data": data}}}
        )


@pytest.fixture
async def service(
    monkeypatch: pytest.MonkeyPatch, socket_enabled: None
) -> AsyncGenerator[FakeService]:
    """Run the fake service and point the client at it."""
    fake = FakeService()
    server = TestServer(fake.app)
    await server.start_server()
    base = URL(f"http://127.0.0.1:{server.port}")
    monkeypatch.setattr(api, "BASE_URL", base)
    monkeypatch.setattr(api, "API_URL", base / "v1" / "cocoro-wash")
    monkeypatch.setattr(api, "AUTH_HOST", "127.0.0.1")
    yield fake
    await server.close()


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as client_session:
        yield client_session


async def test_login_and_read(service: FakeService, session: aiohttp.ClientSession) -> None:
    client = CocoroWashClient(session, EMAIL, PASSWORD)

    devices = await client.get_devices()
    assert service.logins == 1
    assert [device.device_id for device in devices] == [DEVICE_ID, "b" * 64]
    assert [device.is_washer for device in devices] == [True, False]

    info = await client.get_device_info(DEVICE_ID)
    assert info.model == "ES-W114"
    assert info.name == "Laundry"
    assert info.mac == "aa-bb-cc-dd-ee-ff"
    # Only readable properties, normalized to upper-case hex.
    assert info.readable_epcs == {"0xE2", "0xED"}

    properties = await client.get_properties(DEVICE_ID, ["0xE2", "0xED"])
    assert properties == DRYING_PROPERTIES
    assert service.sensor_queries == ["0xE2+0xED"]
    assert service.logins == 1


async def test_wrong_password(service: FakeService, session: aiohttp.ClientSession) -> None:
    client = CocoroWashClient(session, EMAIL, "wrong")

    with pytest.raises(InvalidCredentialsError):
        await client.login()
    assert service.logins == 0


async def test_challenge_on_identifier_step_is_not_a_credential_error(
    service: FakeService, session: aiohttp.ClientSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_HEADERS", {"User-Agent": "python"})
    client = CocoroWashClient(session, EMAIL, PASSWORD)

    with pytest.raises(AuthError) as err:
        await client.login()
    assert not isinstance(err.value, InvalidCredentialsError)


async def test_expired_session_signs_in_again(
    service: FakeService, session: aiohttp.ClientSession
) -> None:
    client = CocoroWashClient(session, EMAIL, PASSWORD)
    await client.get_devices()

    service.sessions.clear()
    devices = await client.get_devices()

    assert len(devices) == 2
    assert service.logins == 2


async def test_unreachable_washer(service: FakeService, session: aiohttp.ClientSession) -> None:
    service.sensor_response = {
        "status": 404,
        "body": {"code": 404, "message": "Not Found", "info": "unreachable"},
    }
    client = CocoroWashClient(session, EMAIL, PASSWORD)

    with pytest.raises(DeviceUnreachableError):
        await client.get_properties(DEVICE_ID, ["0xE2"])


async def test_api_error(service: FakeService, session: aiohttp.ClientSession) -> None:
    service.sensor_response = {
        "status": 400,
        "body": {"code": 400, "message": "Bad Request", "info": "Can not set epc=0x80"},
    }
    client = CocoroWashClient(session, EMAIL, PASSWORD)

    with pytest.raises(ApiError) as err:
        await client.get_properties(DEVICE_ID, ["0x80"])
    assert not isinstance(err.value, DeviceUnreachableError)
    assert err.value.status == 400
    assert err.value.info == "Can not set epc=0x80"


async def test_connection_error(
    monkeypatch: pytest.MonkeyPatch, session: aiohttp.ClientSession, socket_enabled: None
) -> None:
    # Port 9 (discard) on localhost is closed, so the connection is refused.
    base = URL("http://127.0.0.1:9")
    monkeypatch.setattr(api, "BASE_URL", base)
    monkeypatch.setattr(api, "API_URL", base / "v1" / "cocoro-wash")
    client = CocoroWashClient(session, EMAIL, PASSWORD)

    with pytest.raises(CocoroWashConnectionError):
        await client.login()


async def test_last_properties_come_from_history(
    service: FakeService, session: aiohttp.ClientSession
) -> None:
    client = CocoroWashClient(session, EMAIL, PASSWORD)

    properties = await client.get_last_properties(DEVICE_ID, ["0xE2", "0xED", "0xB0"])

    assert properties == {"0xE2": "0x54", "0xED": "0x0002", "0xB0": "0x42"}
