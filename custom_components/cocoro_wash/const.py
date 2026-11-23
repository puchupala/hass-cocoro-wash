"""Constants for the Sharp COCORO WASH integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "cocoro_wash"
MANUFACTURER = "Sharp"

CONF_SCAN_INTERVAL_RUNNING = "scan_interval_running"
CONF_SCAN_INTERVAL_IDLE = "scan_interval_idle"

# Every poll is a live query that wakes the washer for a few seconds, and the
# service's rate limits are not documented, so the defaults are conservative.
DEFAULT_SCAN_INTERVAL_RUNNING = 60
DEFAULT_SCAN_INTERVAL_IDLE = 300
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 3600

REQUEST_TIMEOUT = timedelta(seconds=40)
