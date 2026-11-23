"""Tests for the config and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cocoro_wash.api import (
    AuthError,
    CocoroWashConnectionError,
    CocoroWashError,
    Device,
    InvalidCredentialsError,
)
from custom_components.cocoro_wash.const import (
    CONF_SCAN_INTERVAL_IDLE,
    CONF_SCAN_INTERVAL_RUNNING,
    DOMAIN,
)

USER_INPUT = {CONF_EMAIL: "User@Example.com", CONF_PASSWORD: "secret"}


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "User@Example.com"
    assert result["data"] == USER_INPUT
    assert result["result"].unique_id == "user@example.com"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvalidCredentialsError("bad"), "invalid_auth"),
        (CocoroWashConnectionError("down"), "cannot_connect"),
        (AuthError("challenge"), "login_failed"),
        (CocoroWashError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant, mock_client: AsyncMock, error: Exception, expected: str
) -> None:
    mock_client.login.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    mock_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_without_washer(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    mock_client.get_devices.return_value = [Device("c" * 64, "0x013001")]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_devices"}


async def test_user_flow_rejects_duplicate_account(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="user@example.com", data=USER_INPUT).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_client.login.assert_not_called()


async def test_reauth_updates_password(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="user@example.com", data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_client.login.side_effect = InvalidCredentialsError("bad")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new secret"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {CONF_EMAIL: "User@Example.com", CONF_PASSWORD: "new secret"}


async def test_options_flow(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="user@example.com", data=USER_INPUT)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL_RUNNING: 45, CONF_SCAN_INTERVAL_IDLE: 900}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL_RUNNING: 45, CONF_SCAN_INTERVAL_IDLE: 900}
    # The entry reloads with the new intervals; the washer is running.
    assert entry.runtime_data.update_interval.total_seconds() == 45
