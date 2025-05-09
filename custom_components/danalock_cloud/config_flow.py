# custom_components/danalock_cloud/config_flow.py

"""Config flow for Danalock Cloud integration."""
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from time import time
from datetime import timedelta

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

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
    EXPIRES_IN,
    TOKEN_EXPIRES_AT,
    UPDATE_INTERVAL
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)

OPTIONS_SCHEMA = vol.Schema({
    vol.Optional(
        "update_interval",
        default=int(UPDATE_INTERVAL.total_seconds() / 60)
    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
})

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(OPTIONS_SCHEMA),
}


class DanalockConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Danalock Cloud."""

    VERSION = 1
    reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial user setup step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            username_lower = username.lower()

            await self.async_set_unique_id(username_lower)
            self._abort_if_unique_id_configured()

            auth_result = await self._test_credentials(
                username=username,
                password=password,
                return_data=True
            )

            if isinstance(auth_result, dict) and ACCESS_TOKEN in auth_result:
                entry_data = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password, # Store password
                    ACCESS_TOKEN: auth_result[ACCESS_TOKEN],
                    REFRESH_TOKEN: auth_result[REFRESH_TOKEN],
                    TOKEN_EXPIRES_AT: auth_result[TOKEN_EXPIRES_AT],
                }
                return self.async_create_entry(
                    title=username, data=entry_data
                )
            else:
                errors = auth_result

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle re-authentication when credentials become invalid."""
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        errors: Dict[str, str] = {}

        if user_input is not None and self.reauth_entry:
            password = user_input[CONF_PASSWORD]
            username = self.reauth_entry.data[CONF_USERNAME]

            auth_result = await self._test_credentials(
                username=username,
                password=password,
                return_data=True
            )

            if isinstance(auth_result, dict) and ACCESS_TOKEN in auth_result:
                new_data = self.reauth_entry.data.copy()
                new_data[CONF_PASSWORD] = password # Update stored password
                new_data[ACCESS_TOKEN] = auth_result[ACCESS_TOKEN]
                new_data[REFRESH_TOKEN] = auth_result[REFRESH_TOKEN]
                new_data[TOKEN_EXPIRES_AT] = auth_result[TOKEN_EXPIRES_AT]

                self.hass.config_entries.async_update_entry(
                    self.reauth_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            else:
                errors = auth_result

        username_for_form = self.reauth_entry.data.get(CONF_USERNAME, "Unknown User") if self.reauth_entry else "Unknown User"

        return self.async_show_form(
            step_id="reauth",
            description_placeholders={"username": username_for_form},
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
        )

    async def _test_credentials(
        self, username: str, password: str, return_data: bool = False
    ) -> Dict[str, str] | Dict[str, Any]:
        """Test credentials against the API."""
        # Create client WITHOUT entry for testing only
        api_client = DanalockApiClient(self.hass, username=username, password=password) # No entry passed
        try:
            _LOGGER.debug("Attempting authentication for %s", username)
            auth_data = await api_client.authenticate(username, password)
            _LOGGER.debug("Authentication successful for %s", username)
            return auth_data if return_data else {}
        except DanalockApiAuthError:
            _LOGGER.warning("Authentication failed for user %s", username)
            return {"base": "invalid_auth"}
        except DanalockApiClientError as e:
            _LOGGER.error("API client error during authentication: %s", e)
            return {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected exception during authentication")
            return {"base": "unknown"}


    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SchemaOptionsFlowHandler:
        """Get the options flow for this handler."""
        return SchemaOptionsFlowHandler(config_entry, OPTIONS_FLOW)

