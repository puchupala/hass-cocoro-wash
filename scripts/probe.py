"""Developer tool: sign in to COCORO WASH and print each washer's state.

Reads COCORO_ID and COCORO_PASSWORD from the .env file at the repository root.
Only reads from the service; nothing is sent to the washer.

    .venv/bin/python scripts/probe.py [--raw] [--check-bad-password]
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.cocoro_wash.api import (  # noqa: E402
    CocoroWashClient,
    CocoroWashError,
    DeviceUnreachableError,
    InvalidCredentialsError,
)
from custom_components.cocoro_wash.echonet import STATE_EPCS, decode  # noqa: E402


def load_env(path: Path) -> dict[str, str]:
    """Parse plain KEY=value lines; the file is never executed."""
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


async def check_bad_password(email: str) -> None:
    """Confirm a wrong password is reported as invalid credentials."""
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
        try:
            await CocoroWashClient(session, email, "not-the-password").login()
        except InvalidCredentialsError as err:
            print(f"wrong password -> InvalidCredentialsError: {err}")
        else:
            print("wrong password -> unexpectedly signed in")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", action="store_true", help="also print the raw properties")
    parser.add_argument(
        "--check-bad-password",
        action="store_true",
        help="make one sign-in attempt with a wrong password and show the error",
    )
    args = parser.parse_args()

    env = load_env(ROOT / ".env")
    email, password = env.get("COCORO_ID", ""), env.get("COCORO_PASSWORD", "")
    if not email or not password:
        print("Set COCORO_ID and COCORO_PASSWORD in .env", file=sys.stderr)
        return 2

    if args.check_bad_password:
        await check_bad_password(email)

    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar()) as session:
        client = CocoroWashClient(session, email, password)
        await client.login()
        print("signed in")
        devices = await client.get_devices()
        print(f"{len(devices)} device(s)")
        for index, device in enumerate(devices):
            info = await client.get_device_info(device.device_id)
            print(
                f"\n[{index}] object_id={device.object_id} washer={device.is_washer} "
                f"model={info.model} place={info.place} "
                f"readable_epcs={len(info.readable_epcs)}"
            )
            epcs = [epc for epc in STATE_EPCS if epc in info.readable_epcs]
            try:
                properties = await client.get_properties(device.device_id, epcs)
            except DeviceUnreachableError as err:
                print(f"    unreachable ({err}); showing its last report to the cloud")
                properties = await client.get_last_properties(device.device_id, epcs)
            if args.raw:
                for epc in sorted(properties):
                    print(f"    {epc} = {properties[epc]}")
            state = decode(properties)
            for field in dataclasses.fields(state):
                print(f"    {field.name:18} {getattr(state, field.name)}")
            print(f"    {'progress':18} {state.progress}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except CocoroWashError as err:
        print(f"error: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(1)
