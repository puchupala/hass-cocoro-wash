"""Base entity for the Sharp COCORO WASH integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, format_mac
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import CocoroWashCoordinator, WasherData
from .echonet import WasherState


class CocoroWashEntity(CoordinatorEntity[CocoroWashCoordinator]):
    """An entity that belongs to one washer."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CocoroWashCoordinator, device_id: str, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        info = coordinator.washers[device_id].info
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections={(CONNECTION_NETWORK_MAC, format_mac(info.mac))} if info.mac else set(),
            manufacturer=MANUFACTURER,
            model=info.model,
            name=info.name or info.model or "COCORO WASH",
            suggested_area=info.place,
        )

    @property
    def reading(self) -> WasherData | None:
        """Return the latest reading of this entity's washer."""
        return self.coordinator.data.get(self._device_id)

    @property
    def washer_state(self) -> WasherState | None:
        """Return the latest decoded state of this entity's washer."""
        reading = self.reading
        return reading.state if reading else None

    @property
    def available(self) -> bool:
        """Return whether the service returned data for this washer."""
        return super().available and self.reading is not None
