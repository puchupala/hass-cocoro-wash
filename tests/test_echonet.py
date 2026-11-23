"""Tests for decoding washer properties."""

from __future__ import annotations

import pytest

from custom_components.cocoro_wash.echonet import (
    COURSES,
    CycleType,
    DriveType,
    OperationState,
    Stage,
    TankLevel,
    decode,
)

from . import DRYING_PROPERTIES


def _with(**overrides: str) -> dict[str, str]:
    """Return the drying fixture with ``E2="0x45"``-style overrides applied."""
    properties = dict(DRYING_PROPERTIES)
    properties.update({f"0x{key}": value for key, value in overrides.items()})
    return properties


def _f0(drive_type: int, generation: int = 0x0B) -> str:
    data = bytearray(32)
    data[4] = generation
    data[10] = drive_type
    return "0x" + data.hex()


def _f4(course_id: int, total_minutes: int = 0) -> str:
    data = bytearray(97)
    data[15] = course_id
    data[27:29] = total_minutes.to_bytes(2)
    return "0x" + data.hex()


def test_decode_real_drying_cycle() -> None:
    state = decode(DRYING_PROPERTIES)

    assert state.operation_state is OperationState.RUNNING
    assert state.stage is Stage.DRYING
    assert state.course == "standard"
    assert state.cycle_type is CycleType.DRY
    assert state.remaining_minutes == 100
    assert state.total_minutes == 131
    assert state.progress == 24
    assert state.door_open is False
    assert state.fault is False
    assert state.timer_reserved is False
    assert state.detergent_level is TankLevel.OK
    assert state.softener_level is TankLevel.OK
    assert state.drive_type is DriveType.DRUM


def test_decode_empty_properties_gives_unknowns() -> None:
    state = decode({})

    assert state.operation_state is None
    assert state.stage is None
    assert state.course is None
    assert state.remaining_minutes is None
    assert state.progress is None
    assert state.door_open is None


def test_decode_ignores_malformed_values() -> None:
    state = decode({"0xE2": "bogus", "0xED": "0xZZ", "0xF4": "0x00", "0xB0": ""})

    assert state.stage is None
    assert state.remaining_minutes is None
    assert state.course is None
    assert state.door_open is None


@pytest.mark.parametrize(
    ("stage_code", "operation_state", "stage"),
    [
        ("0x41", OperationState.RUNNING, Stage.WASHING),
        ("0x42", OperationState.RUNNING, Stage.RINSING),
        ("0x43", OperationState.RUNNING, Stage.SPINNING),
        ("0x52", OperationState.RUNNING, Stage.DRYING),
        ("0xE5", OperationState.RUNNING, Stage.RUNNING),
        ("0x61", OperationState.STANDBY, Stage.STANDBY),
        ("0xE2", OperationState.STANDBY, Stage.STANDBY),
        ("0x45", OperationState.STOPPED, Stage.FINISHED),
        ("0x51", OperationState.STOPPED, Stage.FINISHED),
        ("0x53", OperationState.STOPPED, Stage.WRINKLE_MINIMIZING),
        ("0x44", OperationState.STOPPED, Stage.SUSPENDED),
        # Seen on the real washer between cycles; the app shows it as stopped.
        ("0xE4", OperationState.STOPPED, None),
    ],
)
def test_stage_and_operation_state(
    stage_code: str, operation_state: OperationState, stage: Stage | None
) -> None:
    state = decode(_with(E2=stage_code))

    assert state.operation_state is operation_state
    assert state.stage is stage


def test_stage_ef_runs_only_for_course_63() -> None:
    assert decode(_with(E2="0xEF", F4=_f4(63))).operation_state is OperationState.RUNNING
    assert decode(_with(E2="0xEF", F4=_f4(1))).operation_state is OperationState.STOPPED


def test_fault_is_reported_as_standby_like_the_app() -> None:
    state = decode(_with(**{"88": "0x41"}))

    assert state.fault is True
    assert state.operation_state is OperationState.STANDBY


def test_remaining_time_unknown_marker() -> None:
    state = decode(_with(ED="0xFFFF"))

    assert state.remaining_minutes is None
    assert state.progress is None


def test_progress_only_while_running() -> None:
    assert decode(_with(E2="0x45", ED="0x0000")).progress is None
    # A remaining time above the planned total must not go negative.
    assert decode(_with(ED="0x0300")).progress == 0


@pytest.mark.parametrize(
    ("code", "cycle_type"),
    [
        ("0x21", CycleType.WASH_DRY),
        ("0x4E", CycleType.WASH_DRY),
        ("0x61", CycleType.WASH),
        ("0x8F", CycleType.WASH),
        ("0xA1", CycleType.DRY),
        ("0xCF", CycleType.DRY),
        ("0x42", None),
        ("0xC0", None),
        ("0x50", None),
    ],
)
def test_cycle_type(code: str, cycle_type: CycleType | None) -> None:
    assert decode(_with(D0=code)).cycle_type is cycle_type


@pytest.mark.parametrize(
    ("level", "expected"),
    [("FF", TankLevel.OK), ("7F", TankLevel.LOW), ("01", TankLevel.LOW), ("00", TankLevel.EMPTY)],
)
def test_tank_levels(level: str, expected: TankLevel) -> None:
    state = decode(_with(F9=f"0x0A01{level}000A{level}0000"))

    assert state.detergent_level is expected
    assert state.softener_level is expected


def test_door_and_timer_flags() -> None:
    state = decode(_with(B0="0x41", **{"90": "0x41"}))

    assert state.door_open is True
    assert state.timer_reserved is True


@pytest.mark.parametrize(
    ("drive", "course_id", "generation", "year", "expected"),
    [
        (0, 0, 11, 2021, "standard"),
        (0, 14, 11, 2021, "standard"),
        (0, 4, 11, 2021, "fragrance_plus"),
        (0, 4, 20, 2021, "softener_plus"),
        (0, 7, 11, 2021, "blanket"),
        (0, 7, 11, 2026, "bulky_blanket"),
        (0, 11, 11, 2019, "deodorize"),
        (0, 11, 11, 2021, "sanitize_deodorize"),
        (0, 25, 11, 2021, "wash_dry_80"),
        (0, 8, 11, 2021, None),
        (0, 64, 11, 2021, "downloaded"),
        (1, 2, 11, 2021, "wash_10_min"),
        (1, 8, 19, 2021, "softener_plus"),
        (1, 9, 11, 2020, "hanger_dry"),
        (1, 12, 11, 2021, "hanger_sanitize_deodorize_10_min"),
        (1, 13, 11, 2020, "hanger_deodorize_30_min"),
        (2, 4, 11, 2021, "blanket"),
        (2, 7, 11, 2021, "delicates"),
        (2, 10, 18, 2021, "softener_plus"),
        (2, 20, 11, 2021, "thorough_rinse"),
    ],
)
def test_course(
    drive: int, course_id: int, generation: int, year: int, expected: str | None
) -> None:
    state = decode(_with(F0=_f0(drive, generation), F4=_f4(course_id), FC=f"0x02{year:04X}"))

    assert state.course == expected
    assert expected is None or expected in COURSES
