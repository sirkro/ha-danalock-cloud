"""Config flow for Danalock Cloud integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from time import time
from datetime import timedelta # Added for default interval calculation

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
# Removed selector import as we are using standard vol schema
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)


from .api import (
    DanalockApiClient,
    DanalockApiAuthError,
    DanalockApiClientError,
)
from .const import (
    DOMAIN,
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    EXPIRES_IN, # Used for calculation, not stored directly
    TOKEN_EXPIRES_AT, # Stored instead of expires_in
    UPDATE_INTERVAL # Import for options flow default
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

# --- Options Schema using standard Voluptuous ---
# The label "Update Interval (Minutes)" should come from strings.json
# based on the key "update_interval"
OPTIONS_SCHEMA = vol.Schema({
    vol.Optional(
        "update_interval",
        default=int(UPDATE_INTERVAL.total_seconds() / 60) # Keep the default value logic
    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)), # Use standard validation
})
# --- End Options Schema ---

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(OPTIONS_SCHEMA),
}


class DanalockConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Danalock Cloud."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            username_lower = user_input[CONF_USERNAME].lower()
            # Check if this username is already configured
            await self.async_set_unique_id(username_lower)
            self._abort_if_unique_id_configured(updates=user_input)

            # Create temporary client just for authentication test
            api_client = DanalockApiClient(
                self.hass,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
            )

            try:
                # Authenticate to verify credentials and get initial tokens
                _LOGGER.debug("Attempting authentication for %s", user_input[CONF_USERNAME])
                auth_data = await api_client.authenticate(
                    user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
                _LOGGER.debug("Authentication successful for %s", user_input[CONF_USERNAME])

                # Store necessary data, including tokens and expiry time
                entry_data = {
                    CONF_USERNAME: user_input[CONF_USERNAME], # Store original case for display
                    ACCESS_TOKEN: auth_data[ACCESS_TOKEN],
                    REFRESH_TOKEN: auth_data[REFRESH_TOKEN],
                    TOKEN_EXPIRES_AT: auth_data[TOKEN_EXPIRES_AT],
                }

                return self.async_create_entry(
                    title=user_input[CONF_USERNAME], data=entry_data
                )

            except DanalockApiAuthError:
                _LOGGER.warning("Authentication failed for user %s", user_input[CONF_USERNAME])
                errors["base"] = "invalid_auth"
            except DanalockApiClientError as e:
                _LOGGER.error("API client error during authentication: %s", e)
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during authentication")
                errors["base"] = "unknown"

        # Show the form
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SchemaOptionsFlowHandler:
        """Get the options flow for this handler."""
        # Ensure we are using the correct options flow dictionary
        return SchemaOptionsFlowHandler(config_entry, OPTIONS_FLOW)

