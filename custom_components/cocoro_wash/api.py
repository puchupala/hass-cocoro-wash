"""Client for the Sharp COCORO WASH web API.

This talks to the same backend as the COCORO WASH web app
(https://cocoroplusapp.jp.sharp/wash/). The backend is a cookie-session BFF in
front of Sharp's device cloud; signing in goes through the Auth0-hosted
COCORO MEMBERS login pages. None of this is a documented public API.

The module depends only on aiohttp so it can be used outside Home Assistant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import aiohttp
from yarl import URL

BASE_URL = URL("https://cocoroplusapp.jp.sharp")
API_URL = BASE_URL / "v1" / "cocoro-wash"
AUTH_HOST = "auth.cocoromembers.jp.sharp"

EVENT_ECHONET_PROPERTY = "echonet_property"
#: ECHONET Lite class group/class of a washer-dryer, as reported in ``object_id``.
WASHER_OBJECT_PREFIX = "0x03d3"

_TIMEOUT = aiohttp.ClientTimeout(total=40)

# The COCORO MEMBERS login pages answer a non-browser User-Agent with a
# security challenge (HTTP 400) instead of the password step, so requests are
# sent with a browser-style one. If Sharp tightens this check, signing in from
# this client stops working and AuthError is raised.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
_JSON_HEADERS = {**_HEADERS, "Accept": "application/json"}


class CocoroWashError(Exception):
    """Base error for the COCORO WASH client."""


class CocoroWashConnectionError(CocoroWashError):
    """The service could not be reached."""


class AuthError(CocoroWashError):
    """Signing in failed."""


class InvalidCredentialsError(AuthError):
    """The COCORO ID or password was rejected."""


class ApiError(CocoroWashError):
    """The API answered with an error."""

    def __init__(self, status: int, message: str | None = None, info: str | None = None) -> None:
        """Store the error details reported by the API."""
        super().__init__(f"HTTP {status}: {message or 'error'}" + (f" ({info})" if info else ""))
        self.status = status
        self.message = message
        self.info = info


class DeviceUnreachableError(ApiError):
    """The cloud could not reach the washer (powered off or offline)."""


@dataclass(frozen=True, slots=True)
class Device:
    """A device registered to the account."""

    device_id: str
    object_id: str

    @property
    def is_washer(self) -> bool:
        """Return whether the device is an ECHONET Lite washer-dryer."""
        return self.object_id.lower().startswith(WASHER_OBJECT_PREFIX)


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Static details of a device."""

    name: str | None
    model: str | None
    place: str | None
    mac: str | None
    readable_epcs: frozenset[str]


class _HiddenInputParser(HTMLParser):
    """Collect the hidden inputs of the Auth0 login form."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        attr = dict(attrs)
        if attr.get("type") == "hidden" and attr.get("name"):
            self.fields[attr["name"]] = attr.get("value") or ""


def _hidden_inputs(page: str) -> dict[str, str]:
    parser = _HiddenInputParser()
    parser.feed(page)
    return parser.fields


class CocoroWashClient:
    """Cookie-session client for COCORO WASH.

    ``session`` must own its cookie jar: the login stores the session cookie
    there, and :meth:`login` clears the jar before signing in.
    """

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        """Initialize the client; no network traffic happens here."""
        self._session = session
        self._email = email
        self._password = password
        self._login_lock = asyncio.Lock()
        self._logged_in = False

    async def login(self) -> None:
        """Sign in with the COCORO ID and store the session cookie.

        Raises InvalidCredentialsError when the ID or password is rejected and
        AuthError when the login pages do not behave as expected (for example
        an extra verification step this client does not support).
        """
        async with self._login_lock:
            await self._login()

    async def _login(self) -> None:
        self._logged_in = False
        self._session.cookie_jar.clear()
        try:
            async with self._session.get(
                API_URL / "login", headers=_JSON_HEADERS, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                authorize_url = (await resp.json())["redirectUrl"]

            async with self._session.get(authorize_url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                identifier_url = resp.url
                page = await resp.text()
            if identifier_url.host != AUTH_HOST or "state" not in (fields := _hidden_inputs(page)):
                raise AuthError(f"Unexpected login page: {identifier_url.path}")

            fields.update(username=self._email, action="default")
            async with self._session.post(
                identifier_url, data=fields, headers=_HEADERS, timeout=_TIMEOUT
            ) as resp:
                password_url = resp.url
                page = await resp.text()
            if not password_url.path.endswith("/login/password"):
                # Seen when the page demands a security challenge, and for an
                # ID that is not an email address.
                raise AuthError(
                    f"The login page did not accept the COCORO ID (HTTP {resp.status} "
                    f"at {password_url.path}); it may be asking for a security check"
                )

            fields = _hidden_inputs(page)
            fields.update(username=self._email, password=self._password, action="default")
            async with self._session.post(
                password_url, data=fields, headers=_HEADERS, timeout=_TIMEOUT
            ) as resp:
                final_url = resp.url
                await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CocoroWashConnectionError(f"Could not sign in: {err!r}") from err
        except (KeyError, ValueError) as err:
            raise AuthError("Unexpected response while signing in") from err

        if final_url.host == BASE_URL.host and final_url.query.get("login") == "success":
            self._logged_in = True
            return
        if final_url.host == AUTH_HOST and final_url.path.endswith("/login/password"):
            raise InvalidCredentialsError("The COCORO ID or password was not accepted")
        raise AuthError(f"Sign-in did not complete (stopped at {final_url.host}{final_url.path})")

    async def get_devices(self) -> list[Device]:
        """Return the devices registered to the account."""
        body = await self._get("devices/cocoro-home")
        return [
            Device(device_id=item["device_id"], object_id=item.get("object_id", ""))
            for item in body.get("devices", [])
            if item.get("device_id")
        ]

    async def get_device_info(self, device_id: str) -> DeviceInfo:
        """Return name, model and readable properties of a device."""
        body = await self._get("deviceinfo", {"device_id": device_id})
        readable: set[str] = set()
        for event in body.get("events", []):
            if event.get("event_key") != "echonet_access":
                continue
            for prop in event.get("value", []):
                if "get" in prop.get("access_rule", []) and prop.get("epc"):
                    readable.add(_normalize_epc(prop["epc"]))
        return DeviceInfo(
            name=body.get("device_name") or None,
            model=body.get("model_name") or None,
            place=body.get("place") or None,
            mac=body.get("uniq_id") or None,
            readable_epcs=frozenset(readable),
        )

    async def get_properties(self, device_id: str, epcs: Iterable[str]) -> dict[str, str]:
        """Read ECHONET Lite properties from the washer.

        This is a live query: the cloud asks the washer and answers after a few
        seconds. Raises DeviceUnreachableError when the washer does not answer.
        """
        body = await self._get(
            "sensors",
            {
                "device_id": device_id,
                "event_key": EVENT_ECHONET_PROPERTY,
                "epc": "+".join(epcs),
            },
        )
        properties: dict[str, str] = {}
        for row in body.get("data", []):
            for key, value in row.items():
                if key != "time" and isinstance(value, str):
                    properties[_normalize_epc(key)] = value
        return properties

    async def _get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        if not self._logged_in:
            await self.login()
        try:
            return await self._get_once(path, params)
        except _SessionExpired:
            await self.login()
        try:
            return await self._get_once(path, params)
        except _SessionExpired as err:
            raise AuthError("The session was rejected right after signing in") from err

    async def _get_once(self, path: str, params: Mapping[str, str] | None) -> dict[str, Any]:
        try:
            async with self._session.get(
                API_URL / path,
                params=params,
                headers=_JSON_HEADERS,
                timeout=_TIMEOUT,
            ) as resp:
                status = resp.status
                try:
                    payload = await resp.json(content_type=None)
                except ValueError:
                    payload = None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CocoroWashConnectionError(f"Request to {path} failed: {err!r}") from err

        if status == 401:
            self._logged_in = False
            raise _SessionExpired
        if not isinstance(payload, dict):
            raise ApiError(status, "Response was not a JSON object")
        if status >= 400:
            raise ApiError(status, payload.get("title"), payload.get("detail") or None)
        return _unwrap(payload)


class _SessionExpired(Exception):
    """The session cookie is missing or no longer valid."""


def _normalize_epc(epc: str) -> str:
    """Return an EPC code as ``0xNN`` with upper-case hex digits."""
    return "0x" + epc[2:].upper() if epc[:2].lower() == "0x" else epc


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the body of a ``{"<name>": {"status": ..., "body": {...}}}`` envelope."""
    if len(payload) != 1:
        raise ApiError(200, "Unexpected response envelope")
    (inner,) = payload.values()
    if not isinstance(inner, dict) or not isinstance(inner.get("body"), dict):
        raise ApiError(200, "Unexpected response envelope")
    body: dict[str, Any] = inner["body"]
    status = inner.get("status", 200)
    if isinstance(status, int) and status >= 400:
        message = body.get("message")
        info = body.get("info")
        error = DeviceUnreachableError if info == "unreachable" else ApiError
        raise error(status, message, info)
    return body
