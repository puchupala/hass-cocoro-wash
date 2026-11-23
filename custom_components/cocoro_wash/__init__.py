"""The Sharp COCORO WASH integration."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CocoroWashClient
from .coordinator import CocoroWashConfigEntry, CocoroWashCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: CocoroWashConfigEntry) -> bool:
    """Set up COCORO WASH from a config entry."""
    # A dedicated session: the client keeps its login cookie in the session's jar.
    session = async_create_clientsession(hass)
    client = CocoroWashClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    coordinator = CocoroWashCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CocoroWashConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
