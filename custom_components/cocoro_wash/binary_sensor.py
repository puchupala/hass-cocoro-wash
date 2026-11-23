"""Binary sensors for the Sharp COCORO WASH integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CocoroWashConfigEntry, CocoroWashCoordinator
from .echonet import EPC_DOOR, EPC_FAULT, EPC_ON_TIMER, OperationState, WasherState
from .entity import CocoroWashEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CocoroWashBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a COCORO WASH binary sensor."""

    value_fn: Callable[[WasherState], bool | None]
    #: Property that must be readable on the washer for the sensor to exist.
    required_epc: str | None = None


def _is_running(state: WasherState) -> bool | None:
    if state.operation_state is None:
        return None
    return state.operation_state is OperationState.RUNNING


BINARY_SENSORS: tuple[CocoroWashBinarySensorDescription, ...] = (
    CocoroWashBinarySensorDescription(
        key="running",
        translation_key="running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_is_running,
    ),
    CocoroWashBinarySensorDescription(
        key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        required_epc=EPC_DOOR,
        value_fn=lambda state: state.door_open,
    ),
    CocoroWashBinarySensorDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        required_epc=EPC_FAULT,
        value_fn=lambda state: state.fault,
    ),
    CocoroWashBinarySensorDescription(
        key="timer_reserved",
        translation_key="timer_reserved",
        required_epc=EPC_ON_TIMER,
        value_fn=lambda state: state.timer_reserved,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CocoroWashConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors of every washer on the account."""
    coordinator = entry.runtime_data
    async_add_entities(
        CocoroWashBinarySensor(coordinator, device_id, description)
        for device_id, washer in coordinator.washers.items()
        for description in BINARY_SENSORS
        if description.required_epc is None or description.required_epc in washer.epcs
    )


class CocoroWashBinarySensor(CocoroWashEntity, BinarySensorEntity):
    """A binary sensor backed by one field of the washer state."""

    entity_description: CocoroWashBinarySensorDescription

    def __init__(
        self,
        coordinator: CocoroWashCoordinator,
        device_id: str,
        description: CocoroWashBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the sensor is on."""
        state = self.washer_state
        return self.entity_description.value_fn(state) if state else None
