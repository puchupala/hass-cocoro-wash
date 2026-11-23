"""Diagnostics for the Sharp COCORO WASH integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import CocoroWashConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CocoroWashConfigEntry
) -> dict[str, Any]:
    """Return diagnostics; device ids, MAC addresses and names are left out."""
    coordinator = entry.runtime_data
    washers = []
    for device_id, washer in coordinator.washers.items():
        reading = coordinator.data.get(device_id)
        washers.append(
            {
                "object_id": washer.device.object_id,
                "model": washer.info.model,
                "readable_epcs": sorted(washer.info.readable_epcs),
                "polled_epcs": list(washer.epcs),
                "properties": reading.properties if reading else None,
                "state": asdict(reading.state) if reading and reading.state else None,
            }
        )
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds() if coordinator.update_interval else None
        ),
        "washers": washers,
    }
