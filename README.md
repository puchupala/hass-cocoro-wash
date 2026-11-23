# Sharp COCORO WASH for Home Assistant

A custom integration that shows the status of Sharp washer-dryers connected to
the COCORO WASH cloud service (Japan).

It is read-only: it reports what the washer is doing and never sends it a
command.

> **Unofficial.** This uses the same web backend as the COCORO WASH web app.
> Sharp does not document or support it, and it can stop working whenever
> Sharp changes that service.

## Entities

One device per washer registered to your COCORO ID.

| Entity | Type | Values |
|---|---|---|
| Operation state | sensor | running, standby, stopped |
| Stage | sensor | washing, rinsing, spinning, drying, wrinkle minimizing, paused, finished, standby, running |
| Course | sensor | the selected course, e.g. Standard (標準コース) |
| Cycle type | sensor | wash, dry, wash and dry |
| Remaining time | sensor | minutes |
| Progress | sensor | percent of the running cycle |
| Completion time | sensor | estimated end of the running cycle |
| Detergent level, Softener level | sensor (diagnostic) | OK, low, empty |
| Running | binary sensor | on while a cycle runs |
| Door | binary sensor | on when open |
| Problem | binary sensor (diagnostic) | on when the washer reports a fault |
| Timer reserved | binary sensor | on when a start timer is set |

Entities for properties a washer does not report are not created. State names
are translated to English and Japanese.

## Installation

Copy `custom_components/cocoro_wash` into the `custom_components` folder of
your Home Assistant configuration and restart Home Assistant.

## Setup

1. Go to **Settings → Devices & services → Add integration** and pick
   **Sharp COCORO WASH**.
2. Enter your COCORO ID (the email address of your COCORO MEMBERS account) and
   its password. The washer must already be registered in the COCORO WASH or
   COCORO HOME app.

### Options

Each poll makes the cloud ask the washer itself for its state, which takes a
few seconds. The defaults are 60 seconds while a cycle is running and 300
seconds otherwise; both can be changed under **Configure**.

## Things to know

- Signing in drives the COCORO MEMBERS login pages with your ID and password,
  which Home Assistant stores in its configuration. Those pages turn away
  non-browser clients with a security challenge, so the integration sends a
  browser-style `User-Agent`. If Sharp adds a CAPTCHA or a second factor to
  the login, the integration can no longer sign in.
- A washer that is powered off or offline shows its entities as unavailable.
- Courses downloaded through the app are reported as "Downloaded course".
- Developed against one drum washer-dryer (ES-W114). Vertical and other models
  follow the web app's rules for them but have not been tested on hardware.

## Development

```sh
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

`scripts/probe.py` signs in with the `COCORO_ID` and `COCORO_PASSWORD` from a
`.env` file (see `.env.example`) and prints each washer's decoded state. It
only reads.
