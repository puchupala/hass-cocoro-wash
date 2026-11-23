"""Tests for setup, entities, polling and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.cocoro_wash.api import (
    ApiError,
    CocoroWashConnectionError,
    DeviceUnreachableError,
    InvalidCredentialsError,
)
from custom_components.cocoro_wash.const import DOMAIN
from custom_components.cocoro_wash.diagnostics import async_get_config_entry_diagnostics
from custom_components.cocoro_wash.echonet import STATE_EPCS

from . import DEVICE_ID, DRYING_PROPERTIES

FINISHED_PROPERTIES = {**DRYING_PROPERTIES, "0xE2": "0x51", "0xED": "0x0000"}


@pytest.fixture
async def entry(hass: HomeAssistant, mock_client: AsyncMock) -> MockConfigEntry:
    """Set up the integration with one drying washer."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-11-23 09:00:00+00:00")
async def test_entities_of_a_drying_washer(
    hass: HomeAssistant, entry: MockConfigEntry, mock_client: AsyncMock
) -> None:
    states = {
        "sensor.laundry_operation_state": "running",
        "sensor.laundry_stage": "drying",
        "sensor.laundry_course": "standard",
        "sensor.laundry_cycle_type": "dry",
        "sensor.laundry_remaining_time": "100",
        "sensor.laundry_progress": "24",
        "sensor.laundry_completion_time": "2026-11-23T10:40:00+00:00",
        "sensor.laundry_detergent_level": "ok",
        "sensor.laundry_softener_level": "ok",
        "binary_sensor.laundry_running": "on",
        "binary_sensor.laundry_door": "off",
        "binary_sensor.laundry_problem": "off",
        "binary_sensor.laundry_timer_reserved": "off",
    }
    assert {state.entity_id: state.state for state in hass.states.async_all()} == states
    mock_client.get_properties.assert_awaited_once_with(DEVICE_ID, STATE_EPCS)

    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, DEVICE_ID), entry.entry_id)
    assert device is not None
    assert device.manufacturer == "Sharp"
    assert device.model == "ES-W114"
    assert device.name == "Laundry"
    assert (dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff") in device.connections

    registry = er.async_get(hass)
    assert registry.async_get("sensor.laundry_stage").unique_id == f"{DEVICE_ID}_stage"


async def test_entities_skip_unreadable_properties(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    info = mock_client.get_device_info.return_value
    mock_client.get_device_info.return_value = type(info)(
        name=info.name,
        model=info.model,
        place=info.place,
        mac=info.mac,
        readable_epcs=frozenset({"0xE2", "0xED", "0xF0", "0xF4"}),
    )
    config_entry = MockConfigEntry(domain=DOMAIN, data={CONF_EMAIL: "a@b.c", CONF_PASSWORD: "x"})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.laundry_stage") is not None
    assert hass.states.get("sensor.laundry_detergent_level") is None
    assert hass.states.get("binary_sensor.laundry_door") is None
    mock_client.get_properties.assert_awaited_once_with(DEVICE_ID, ("0xE2", "0xED", "0xF0", "0xF4"))


async def test_polls_faster_while_running(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator = entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=60)

    mock_client.get_properties.return_value = FINISHED_PROPERTIES
    await _poll(hass, freezer, 60)

    assert hass.states.get("sensor.laundry_operation_state").state == "stopped"
    assert hass.states.get("sensor.laundry_stage").state == "finished"
    assert hass.states.get("sensor.laundry_completion_time").state == STATE_UNKNOWN
    assert hass.states.get("sensor.laundry_progress").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.laundry_running").state == "off"
    assert coordinator.update_interval == timedelta(seconds=300)

    calls = mock_client.get_properties.await_count
    await _poll(hass, freezer, 60)
    assert mock_client.get_properties.await_count == calls
    await _poll(hass, freezer, 240)
    assert mock_client.get_properties.await_count == calls + 1


@pytest.mark.freeze_time("2026-11-23 09:00:00+00:00")
async def test_completion_time_does_not_wobble(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    entity_id = "sensor.laundry_completion_time"
    assert hass.states.get(entity_id).state == "2026-11-23T10:40:00+00:00"

    # A minute later the washer still says 100 minutes: within tolerance, keep it.
    await _poll(hass, freezer, 60)
    assert hass.states.get(entity_id).state == "2026-11-23T10:40:00+00:00"

    # The washer extends the cycle by ten minutes: follow it.
    mock_client.get_properties.return_value = {**DRYING_PROPERTIES, "0xED": "0x0132"}
    await _poll(hass, freezer, 60)
    assert hass.states.get(entity_id).state == "2026-11-23T10:52:00+00:00"


async def test_unreachable_washer_is_unavailable_and_recovers(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.get_properties.side_effect = DeviceUnreachableError(404, "Not Found", "unreachable")
    await _poll(hass, freezer, 60)

    assert hass.states.get("sensor.laundry_stage").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.laundry_door").state == STATE_UNAVAILABLE
    # An unreachable washer is not an integration failure.
    assert entry.runtime_data.last_update_success is True

    mock_client.get_properties.side_effect = None
    await _poll(hass, freezer, 300)
    assert hass.states.get("sensor.laundry_stage").state == "drying"


async def test_service_outage_marks_entities_unavailable(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.get_properties.side_effect = CocoroWashConnectionError("down")
    await _poll(hass, freezer, 60)

    assert entry.runtime_data.last_update_success is False
    assert hass.states.get("sensor.laundry_stage").state == STATE_UNAVAILABLE


async def test_rejected_password_starts_reauth(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_client: AsyncMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_client.get_properties.side_effect = InvalidCredentialsError("bad")
    await _poll(hass, freezer, 60)

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (InvalidCredentialsError("bad"), ConfigEntryState.SETUP_ERROR),
        (CocoroWashConnectionError("down"), ConfigEntryState.SETUP_RETRY),
        (ApiError(500, "Server Error"), ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant, mock_client: AsyncMock, error: Exception, state: ConfigEntryState
) -> None:
    mock_client.get_devices.side_effect = error
    config_entry = MockConfigEntry(domain=DOMAIN, data={CONF_EMAIL: "a@b.c", CONF_PASSWORD: "x"})
    config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is state


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert hass.states.get("sensor.laundry_stage").state == STATE_UNAVAILABLE


async def test_diagnostics_leave_out_identifying_data(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    text = str(diagnostics)
    for secret in ("user@example.com", "secret", DEVICE_ID, "aa-bb-cc-dd-ee-ff", "Laundry"):
        assert secret not in text
    washer = diagnostics["washers"][0]
    assert washer["model"] == "ES-W114"
    assert washer["properties"] == DRYING_PROPERTIES
    assert washer["state"]["stage"] == "drying"
    assert diagnostics["update_interval_seconds"] == 60
