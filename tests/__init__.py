"""Tests for the Sharp COCORO WASH integration."""

# Properties read from a real drum washer-dryer (ES-W114) while it was drying.
DRYING_PROPERTIES: dict[str, str] = {
    "0x88": "0x42",
    "0x90": "0x42",
    "0xB0": "0x42",
    "0xD0": "0xA1",
    "0xE2": "0x52",
    "0xED": "0x0128",
    "0xF0": "0x000000000B00036E3C0200070100000000000000000000000000004A50000101",
    "0xF4": ("0x0000000203670000002000000000000E000000000000000000000000830000005F74" + "00" * 62),
    "0xF9": "0x0A01FF000AFF0000",
    "0xFC": "0x0207E5",
}

# What the cloud kept as that washer's last report after the cycle ended and
# it powered itself off: finished, with a remaining time from minutes earlier.
LAST_REPORT_PROPERTIES: dict[str, str] = {**DRYING_PROPERTIES, "0xE2": "0x54", "0xED": "0x0002"}

DEVICE_ID = "a" * 64
