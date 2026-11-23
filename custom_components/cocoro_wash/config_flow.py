"""Config flow for the Sharp COCORO WASH integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AuthError,
    CocoroWashClient,
    CocoroWashConnectionError,
    CocoroWashError,
    InvalidCredentialsError,
)
from .const import (
    CONF_SCAN_INTERVAL_IDLE,
    CONF_SCAN_INTERVAL_RUNNING,
    DEFAULT_SCAN_INTERVAL_IDLE,
    DEFAULT_SCAN_INTERVAL_RUNNING,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import CocoroWashConfigEntry

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR})

_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=1,
        unit_of_measurement="s",
        mode=NumberSelectorMode.BOX,
    )
)


async def _validate(hass: HomeAssistant, email: str, password: str) -> str | None:
    """Sign in and look for a washer; return an error key, or None on success."""
    # A throwaway session so a failed attempt leaves no cookies behind.
    session = async_create_clientsession(hass, auto_cleanup=False)
    client = CocoroWashClient(session, email, password)
    try:
        await client.login()
        devices = await client.get_devices()
    except InvalidCredentialsError:
        return "invalid_auth"
    except CocoroWashConnectionError:
        return "cannot_connect"
    except AuthError as err:
        _LOGGER.warning("COCORO WASH sign-in did not complete: %s", err)
        return "login_failed"
    except CocoroWashError:
        _LOGGER.exception("Unexpected error from COCORO WASH")
        return "unknown"
    finally:
        session.detach()
    if not any(device.is_washer for device in devices):
        return "no_devices"
    return None


class CocoroWashConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for COCORO WASH."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: CocoroWashConfigEntry) -> CocoroWashOptionsFlow:
        """Return the options flow."""
        return CocoroWashOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the COCORO ID and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            error = await _validate(self.hass, email, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after the password was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the current password of the configured COCORO ID."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )


class CocoroWashOptionsFlow(OptionsFlowWithReload):
    """Let the user tune how often the washer is polled."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the polling intervals."""
        if user_input is not None:
            return self.async_create_entry(
                data={key: int(value) for key, value in user_input.items()}
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_RUNNING,
                    default=options.get(CONF_SCAN_INTERVAL_RUNNING, DEFAULT_SCAN_INTERVAL_RUNNING),
                ): _INTERVAL_SELECTOR,
                vol.Required(
                    CONF_SCAN_INTERVAL_IDLE,
                    default=options.get(CONF_SCAN_INTERVAL_IDLE, DEFAULT_SCAN_INTERVAL_IDLE),
                ): _INTERVAL_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
