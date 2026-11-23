"""Sensors for the Sharp COCORO WASH integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import CocoroWashConfigEntry, CocoroWashCoordinator
from .echonet import (
    COURSES,
    EPC_DISPENSER,
    CycleType,
    OperationState,
    Stage,
    TankLevel,
    WasherState,
)
from .entity import CocoroWashEntity

PARALLEL_UPDATES = 0

# The washer reports whole minutes, so an end time computed at each poll
# wobbles; only move it when the estimate really changed.
COMPLETION_TOLERANCE = timedelta(seconds=90)


@dataclass(frozen=True, kw_only=True)
class CocoroWashSensorDescription(SensorEntityDescription):
    """Describes a COCORO WASH sensor."""

    value_fn: Callable[[WasherState], str | int | None]
    #: Property that must be readable on the washer for the sensor to exist.
    required_epc: str | None = None


SENSORS: tuple[CocoroWashSensorDescription, ...] = (
    CocoroWashSensorDescription(
        key="operation_state",
        translation_key="operation_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in OperationState],
        value_fn=lambda state: state.operation_state,
    ),
    CocoroWashSensorDescription(
        key="stage",
        translation_key="stage",
        device_class=SensorDeviceClass.ENUM,
        options=[stage.value for stage in Stage],
        value_fn=lambda state: state.stage,
    ),
    CocoroWashSensorDescription(
        key="course",
        translation_key="course",
        device_class=SensorDeviceClass.ENUM,
        options=list(COURSES),
        value_fn=lambda state: state.course,
    ),
    CocoroWashSensorDescription(
        key="cycle_type",
        translation_key="cycle_type",
        device_class=SensorDeviceClass.ENUM,
        options=[cycle.value for cycle in CycleType],
        value_fn=lambda state: state.cycle_type,
    ),
    CocoroWashSensorDescription(
        key="remaining_time",
        translation_key="remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda state: state.remaining_minutes,
    ),
    CocoroWashSensorDescription(
        key="progress",
        translation_key="progress",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda state: state.progress,
    ),
    CocoroWashSensorDescription(
        key="detergent_level",
        translation_key="detergent_level",
        device_class=SensorDeviceClass.ENUM,
        options=[level.value for level in TankLevel],
        entity_category=EntityCategory.DIAGNOSTIC,
        required_epc=EPC_DISPENSER,
        value_fn=lambda state: state.detergent_level,
    ),
    CocoroWashSensorDescription(
        key="softener_level",
        translation_key="softener_level",
        device_class=SensorDeviceClass.ENUM,
        options=[level.value for level in TankLevel],
        entity_category=EntityCategory.DIAGNOSTIC,
        required_epc=EPC_DISPENSER,
        value_fn=lambda state: state.softener_level,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CocoroWashConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of every washer on the account."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for device_id, washer in coordinator.washers.items():
        entities.extend(
            CocoroWashSensor(coordinator, device_id, description)
            for description in SENSORS
            if description.required_epc is None or description.required_epc in washer.epcs
        )
        entities.append(CocoroWashCompletionTimeSensor(coordinator, device_id))
    async_add_entities(entities)


class CocoroWashSensor(CocoroWashEntity, SensorEntity):
    """A sensor backed by one field of the washer state."""

    entity_description: CocoroWashSensorDescription

    def __init__(
        self,
        coordinator: CocoroWashCoordinator,
        device_id: str,
        description: CocoroWashSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | None:
        """Return the sensor value."""
        state = self.washer_state
        return self.entity_description.value_fn(state) if state else None


class CocoroWashCompletionTimeSensor(CocoroWashEntity, SensorEntity):
    """Estimated time at which the running cycle ends; unknown while paused."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "completion_time"

    def __init__(self, coordinator: CocoroWashCoordinator, device_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, "completion_time")
        self._attr_native_value = self._estimate(None)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self._estimate(self._attr_native_value)
        super()._handle_coordinator_update()

    def _estimate(self, previous: datetime | None) -> datetime | None:
        state = self.washer_state
        if (
            state is None
            or state.operation_state is not OperationState.RUNNING
            or state.remaining_minutes is None
        ):
            return None
        estimate = (dt_util.utcnow() + timedelta(minutes=state.remaining_minutes)).replace(
            second=0, microsecond=0
        )
        if previous is not None and abs(estimate - previous) <= COMPLETION_TOLERANCE:
            return previous
        return estimate
