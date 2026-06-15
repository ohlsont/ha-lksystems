"""Config flow for LK Systems integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

# Import at the module level
from .pylksystems import LKSystemsManager
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Define schemas outside of async functions
# The update interval must be at least 1 minute; 0 would make the data
# coordinator poll the LK cloud API in a tight loop.
UPDATE_INTERVAL_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=1))

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(
            CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
        ): UPDATE_INTERVAL_VALIDATOR,
    }
)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate that the user input allows us to connect to LK Systems."""
    async with LKSystemsManager(data[CONF_USERNAME], data[CONF_PASSWORD]) as lk_inst:
        if not await lk_inst.login():
            raise InvalidAuth


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LK Systems."""

    VERSION = 1

    async def async_step_reauth(self, entry_data):
        """Handle reauth upon an authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Confirm reauth by re-entering the password for the existing account.

        The username/account is fixed: reauth only refreshes the password for
        the entry being reauthenticated, so it can never be silently repointed
        to a different LK Systems account.
        """
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            credentials = {
                CONF_USERNAME: reauth_entry.data.get(CONF_USERNAME, ""),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_input(self.hass, credentials)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            errors=errors,
            description_placeholders={
                "username": reauth_entry.data.get(CONF_USERNAME, "")
            },
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check if we already have an entry for this username
            existing_entries = self._async_current_entries()
            for entry in existing_entries:
                if entry.data.get(CONF_USERNAME) == user_input[CONF_USERNAME]:
                    return self.async_abort(reason="already_configured")

            # Credentials are not validated here: the LK cloud client collapses
            # connectivity errors and auth failures into the same result, so
            # validating at setup would block onboarding during a transient
            # outage with a misleading "invalid auth" error. A wrong password
            # instead surfaces via the reauth flow on the first refresh.
            return self.async_create_entry(
                title=f"LK Systems ({user_input[CONF_USERNAME]})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        # Modern HA injects config_entry on the OptionsFlow automatically;
        # the handler must be constructed with no arguments.
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Handle options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Pre-fill using the same precedence the coordinator reads
        # (options -> initial setup data -> default), so opening and submitting
        # the form does not silently overwrite an interval chosen at setup.
        update_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL, default=update_interval
                    ): UPDATE_INTERVAL_VALIDATOR,
                }
            ),
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
