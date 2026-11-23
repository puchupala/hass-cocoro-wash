"""Decode the ECHONET Lite properties of a Sharp washer-dryer.

Standard properties follow the ECHONET Lite "washer and dryer" device class
(0x03D3). The 0xF0-0xFF properties are Sharp specific; their layout and the
course tables are taken from the behaviour of the COCORO WASH web app.

Property values (EDT) arrive as hex strings such as ``"0x0128"``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

EPC_FAULT = "0x88"
EPC_ON_TIMER = "0x90"
EPC_DOOR = "0xB0"
EPC_CYCLE = "0xD0"
EPC_STAGE = "0xE2"
EPC_REMAINING_TIME = "0xED"
EPC_CAPABILITIES = "0xF0"
EPC_RUN_INFO = "0xF4"
EPC_DISPENSER = "0xF9"
EPC_MODEL_INFO = "0xFC"

#: Properties needed to build a :class:`WasherState`, read in one request.
STATE_EPCS: tuple[str, ...] = (
    EPC_FAULT,
    EPC_ON_TIMER,
    EPC_DOOR,
    EPC_CYCLE,
    EPC_STAGE,
    EPC_REMAINING_TIME,
    EPC_CAPABILITIES,
    EPC_RUN_INFO,
    EPC_DISPENSER,
    EPC_MODEL_INFO,
)


class DriveType(StrEnum):
    """Mechanical type of the washer, which selects the course table."""

    DRUM = "drum"
    VERTICAL = "vertical"
    AUTO = "auto"


class OperationState(StrEnum):
    """Overall state, as the COCORO WASH app derives it."""

    RUNNING = "running"
    STANDBY = "standby"
    STOPPED = "stopped"


class Stage(StrEnum):
    """Current stage of the cycle."""

    WASHING = "washing"
    RINSING = "rinsing"
    SPINNING = "spinning"
    DRYING = "drying"
    WRINKLE_MINIMIZING = "wrinkle_minimizing"
    SUSPENDED = "suspended"
    FINISHED = "finished"
    STANDBY = "standby"
    #: A Sharp-specific stage code that the app treats as "in operation".
    RUNNING = "running"


class CycleType(StrEnum):
    """Which parts of a full cycle the selected course runs."""

    WASH_DRY = "wash_dry"
    WASH = "wash"
    DRY = "dry"


class TankLevel(StrEnum):
    """Fill level of an automatic detergent or softener tank."""

    OK = "ok"
    LOW = "low"
    EMPTY = "empty"


#: Course key used when the washer runs a course downloaded through the app.
COURSE_DOWNLOADED = "downloaded"

_STAGES: dict[int, Stage] = {
    0x41: Stage.WASHING,
    0x42: Stage.RINSING,
    0x43: Stage.SPINNING,
    0x44: Stage.SUSPENDED,
    0x45: Stage.FINISHED,
    0x51: Stage.FINISHED,
    0x52: Stage.DRYING,
    0x53: Stage.WRINKLE_MINIMIZING,
    0x54: Stage.FINISHED,
    0x61: Stage.STANDBY,
    0xE0: Stage.RUNNING,
    0xE1: Stage.RUNNING,
    0xE2: Stage.STANDBY,
    0xE5: Stage.RUNNING,
    0xE6: Stage.RUNNING,
}
_RUNNING_STAGE_CODES = frozenset({0x41, 0x42, 0x43, 0x52, 0xE0, 0xE1, 0xE5, 0xE6})
_STANDBY_STAGE_CODES = frozenset({0x61, 0xE2})
#: Stage 0xEF means "running" only for this course id.
_STAGE_EF = 0xEF
_STAGE_EF_RUNNING_COURSE = 63

# Course tables: course id (byte 15 of 0xF4) -> course key. Ids not listed are
# either unused or, from 64 up, courses downloaded through the app.
_DRUM_COURSES: dict[int, str] = {
    0: "standard",
    1: "quick",
    2: "wrinkle_reduction",
    3: "my_course",
    5: "hot_water_deep_wash",
    6: "home_cleaning",
    9: "tub_wash",
    12: "quick_prewash",
    13: "tub_clean",
    14: "standard",
    15: "heavy_soil",
    25: "wash_dry_80",
    27: "towel_care",
}
_VERTICAL_COURSES: dict[int, str] = {
    0: "standard",
    1: "my_course",
    2: "wash_10_min",
    3: "quick_prewash",
    4: "warm_air_wash",
    5: "home_cleaning",
    6: "wrinkle_reduction",
    7: "blanket",
    10: "tub_clean",
    17: "tub_wash",
    18: "standard",
    19: "warm_soak_wash",
}
_AUTO_COURSES: dict[int, str] = {
    0: "standard",
    1: "my_course",
    2: "wash_10_min",
    3: "quick_prewash",
    5: "tub_clean",
    6: "heavy_soil",
    7: "delicates",
    8: "wrinkle_reduction",
    9: "tub_wash",
    18: "standard",
    19: "heavy_soak",
    20: "thorough_rinse",
}
_FIRST_DOWNLOADED_COURSE_ID = 64

#: Every course key :func:`decode` can return, for enum sensors.
COURSES: tuple[str, ...] = (
    "standard",
    "quick",
    "wrinkle_reduction",
    "my_course",
    "softener_plus",
    "fragrance_plus",
    "hot_water_deep_wash",
    "home_cleaning",
    "blanket",
    "bulky_blanket",
    "tub_wash",
    "tub_clean",
    "deodorize",
    "sanitize_deodorize",
    "quick_prewash",
    "heavy_soil",
    "wash_dry_80",
    "towel_care",
    "wash_10_min",
    "warm_air_wash",
    "hanger_dry",
    "hanger_sanitize_dry",
    "hanger_deodorize_5_min",
    "hanger_deodorize_10_min",
    "hanger_deodorize_30_min",
    "hanger_sanitize_deodorize_5_min",
    "hanger_sanitize_deodorize_10_min",
    "hanger_sanitize_deodorize_30_min",
    "warm_soak_wash",
    "delicates",
    "heavy_soak",
    "thorough_rinse",
    COURSE_DOWNLOADED,
)


@dataclass(frozen=True, slots=True)
class WasherState:
    """Decoded state of a washer. Fields are None when not reported."""

    operation_state: OperationState | None
    stage: Stage | None
    course: str | None
    cycle_type: CycleType | None
    remaining_minutes: int | None
    total_minutes: int | None
    door_open: bool | None
    fault: bool | None
    timer_reserved: bool | None
    detergent_level: TankLevel | None
    softener_level: TankLevel | None
    drive_type: DriveType | None

    @property
    def progress(self) -> int | None:
        """Return the percentage of the running cycle that has elapsed."""
        if (
            self.operation_state is not OperationState.RUNNING
            or self.remaining_minutes is None
            or not self.total_minutes
        ):
            return None
        elapsed = self.total_minutes - self.remaining_minutes
        return max(0, min(100, round(elapsed * 100 / self.total_minutes)))


def decode(properties: Mapping[str, str]) -> WasherState:
    """Decode raw properties (``{"0xE2": "0x52", ...}``) into a WasherState."""
    capabilities = _edt(properties.get(EPC_CAPABILITIES))
    run_info = _edt(properties.get(EPC_RUN_INFO))
    dispenser = _edt(properties.get(EPC_DISPENSER))
    model_info = _edt(properties.get(EPC_MODEL_INFO))

    drive_type = _drive_type(_byte(capabilities, 10))
    course_id = _byte(run_info, 15)
    stage_code = _byte(_edt(properties.get(EPC_STAGE)), 0)
    fault = _flag(properties.get(EPC_FAULT))

    return WasherState(
        operation_state=_operation_state(stage_code, course_id, fault),
        stage=_stage(stage_code, course_id),
        course=_course(
            course_id,
            drive_type,
            generation=_byte(capabilities, 4),
            model_year=_word(model_info, 1),
        ),
        cycle_type=_cycle_type(_byte(_edt(properties.get(EPC_CYCLE)), 0), drive_type),
        remaining_minutes=_remaining_minutes(_edt(properties.get(EPC_REMAINING_TIME))),
        total_minutes=_word(run_info, 27),
        door_open=_flag(properties.get(EPC_DOOR)),
        fault=fault,
        timer_reserved=_flag(properties.get(EPC_ON_TIMER)),
        detergent_level=_tank_level(_byte(dispenser, 2)),
        softener_level=_tank_level(_byte(dispenser, 5)),
        drive_type=drive_type,
    )


def _edt(value: str | None) -> bytes | None:
    """Return the bytes of a ``0x...`` hex string, or None if it is not one."""
    if not value or value[:2].lower() != "0x":
        return None
    try:
        return bytes.fromhex(value[2:])
    except ValueError:
        return None


def _byte(data: bytes | None, index: int) -> int | None:
    return data[index] if data is not None and len(data) > index else None


def _word(data: bytes | None, index: int) -> int | None:
    """Return the big-endian 16-bit value starting at ``index``."""
    if data is None or len(data) < index + 2:
        return None
    return int.from_bytes(data[index : index + 2])


def _flag(value: str | None) -> bool | None:
    """Decode the ECHONET Lite 0x41 (true) / 0x42 (false) convention."""
    code = _byte(_edt(value), 0)
    if code == 0x41:
        return True
    if code == 0x42:
        return False
    return None


def _drive_type(code: int | None) -> DriveType | None:
    return {0: DriveType.DRUM, 1: DriveType.VERTICAL, 2: DriveType.AUTO}.get(code)


def _operation_state(
    stage_code: int | None, course_id: int | None, fault: bool | None
) -> OperationState | None:
    if stage_code is None:
        return None
    if fault:
        return OperationState.STANDBY
    if stage_code in _STANDBY_STAGE_CODES:
        return OperationState.STANDBY
    if stage_code in _RUNNING_STAGE_CODES:
        return OperationState.RUNNING
    if stage_code == _STAGE_EF and course_id == _STAGE_EF_RUNNING_COURSE:
        return OperationState.RUNNING
    return OperationState.STOPPED


def _stage(stage_code: int | None, course_id: int | None) -> Stage | None:
    if stage_code == _STAGE_EF and course_id == _STAGE_EF_RUNNING_COURSE:
        return Stage.RUNNING
    return _STAGES.get(stage_code)


def _cycle_type(code: int | None, drive_type: DriveType | None) -> CycleType | None:
    if code is None or drive_type not in (DriveType.DRUM, DriveType.VERTICAL):
        return None
    if code in (0x42, 0xC0) or (drive_type is DriveType.VERTICAL and code in (0x7F, 0xBF)):
        return None
    if 0x21 <= code <= 0x4E:
        return CycleType.WASH_DRY
    if 0x61 <= code <= 0x8F:
        return CycleType.WASH
    if 0xA1 <= code <= 0xCF:
        return CycleType.DRY
    return None


def _remaining_minutes(data: bytes | None) -> int | None:
    """Decode hours and minutes; 0xFFFF means the washer has no estimate."""
    if data is None or len(data) < 2 or data[:2] == b"\xff\xff":
        return None
    return data[0] * 60 + data[1]


def _tank_level(level: int | None) -> TankLevel | None:
    if level is None:
        return None
    if level >= 0xFF:
        return TankLevel.OK
    return TankLevel.EMPTY if level == 0 else TankLevel.LOW


def _course(
    course_id: int | None,
    drive_type: DriveType | None,
    *,
    generation: int | None,
    model_year: int | None,
) -> str | None:
    """Return the course key; some ids changed meaning between model years."""
    if course_id is None or drive_type is None:
        return None
    if course_id >= _FIRST_DOWNLOADED_COURSE_ID:
        return COURSE_DOWNLOADED
    generation = generation or 0
    model_year = model_year or 0

    if drive_type is DriveType.DRUM:
        if course_id == 4:
            return "softener_plus" if generation >= 20 else "fragrance_plus"
        if course_id == 7:
            return "bulky_blanket" if model_year >= 2026 else "blanket"
        if course_id == 11:
            return "sanitize_deodorize" if model_year >= 2020 else "deodorize"
        return _DRUM_COURSES.get(course_id)

    if drive_type is DriveType.VERTICAL:
        if course_id == 8:
            return "softener_plus" if generation >= 19 else "fragrance_plus"
        if course_id == 9:
            return "hanger_sanitize_dry" if model_year >= 2021 else "hanger_dry"
        if course_id in (11, 12, 13):
            minutes = {11: 5, 12: 10, 13: 30}[course_id]
            prefix = "hanger_sanitize_deodorize" if model_year >= 2021 else "hanger_deodorize"
            return f"{prefix}_{minutes}_min"
        return _VERTICAL_COURSES.get(course_id)

    if course_id == 4:
        return "bulky_blanket" if model_year >= 2026 else "blanket"
    if course_id == 10:
        return "softener_plus" if generation >= 18 else "fragrance_plus"
    return _AUTO_COURSES.get(course_id)
