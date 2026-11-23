"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.cocoro_wash.api import Device, DeviceInfo
from custom_components.cocoro_wash.echonet import STATE_EPCS

from . import DEVICE_ID, DRYING_PROPERTIES, LAST_REPORT_PROPERTIES


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration under test."""


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Replace the API client with a mock that reports one drying washer."""
    with (
        patch("custom_components.cocoro_wash.CocoroWashClient", autospec=True) as client_class,
        patch("custom_components.cocoro_wash.config_flow.CocoroWashClient", new=client_class),
    ):
        client = client_class.return_value
        client.get_devices.return_value = [Device(DEVICE_ID, "0x03d301")]
        client.get_device_info.return_value = DeviceInfo(
            name="Laundry",
            model="ES-W114",
            # No place: Home Assistant would prefix entity ids with the area.
            place=None,
            mac="aa-bb-cc-dd-ee-ff",
            readable_epcs=frozenset(STATE_EPCS),
        )
        client.get_properties.return_value = dict(DRYING_PROPERTIES)
        client.get_last_properties.return_value = dict(LAST_REPORT_PROPERTIES)
        yield client
