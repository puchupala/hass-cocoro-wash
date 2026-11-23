"""Data update coordinator for the Sharp COCORO WASH integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CocoroWashClient,
    CocoroWashError,
    Device,
    DeviceInfo,
    DeviceUnreachableError,
    InvalidCredentialsError,
)
from .const import (
    CONF_SCAN_INTERVAL_IDLE,
    CONF_SCAN_INTERVAL_RUNNING,
    DEFAULT_SCAN_INTERVAL_IDLE,
    DEFAULT_SCAN_INTERVAL_RUNNING,
    DOMAIN,
)
from .echonet import STATE_EPCS, OperationState, WasherState, decode

_LOGGER = logging.getLogger(__name__)

type CocoroWashConfigEntry = ConfigEntry[CocoroWashCoordinator]


@dataclass(frozen=True, slots=True)
class Washer:
    """A washer found on the account; fixed for the lifetime of the entry."""

    device: Device
    info: DeviceInfo
    epcs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WasherData:
    """Latest reading of a washer; ``state`` is None while it is unreachable."""

    state: WasherState | None
    properties: dict[str, str]


class CocoroWashCoordinator(DataUpdateCoordinator[dict[str, WasherData]]):
    """Poll every washer on the account, faster while one is running."""

    config_entry: CocoroWashConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CocoroWashConfigEntry, client: CocoroWashClient
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        self.washers: dict[str, Washer] = {}
        self._interval_running = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL_RUNNING, DEFAULT_SCAN_INTERVAL_RUNNING)
        )
        self._interval_idle = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL_IDLE, DEFAULT_SCAN_INTERVAL_IDLE)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._interval_idle,
        )

    async def _async_setup(self) -> None:
        """Find the washers on the account; runs once before the first update."""
        try:
            for device in await self.client.get_devices():
                if not device.is_washer:
                    continue
                info = await self.client.get_device_info(device.device_id)
                epcs = tuple(epc for epc in STATE_EPCS if epc in info.readable_epcs)
                self.washers[device.device_id] = Washer(device, info, epcs)
        except InvalidCredentialsError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CocoroWashError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> dict[str, WasherData]:
        data: dict[str, WasherData] = {}
        try:
            for device_id, washer in self.washers.items():
                try:
                    properties = await self.client.get_properties(device_id, washer.epcs)
                except DeviceUnreachableError:
                    _LOGGER.debug("Washer %s is unreachable", washer.info.model)
                    data[device_id] = WasherData(None, {})
                    continue
                data[device_id] = WasherData(decode(properties), properties)
        except InvalidCredentialsError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CocoroWashError as err:
            raise UpdateFailed(str(err)) from err

        running = any(
            reading.state is not None and reading.state.operation_state is OperationState.RUNNING
            for reading in data.values()
        )
        self.update_interval = self._interval_running if running else self._interval_idle
        return data
