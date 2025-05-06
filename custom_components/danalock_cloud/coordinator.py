# custom_components/danalock_cloud/coordinator.py

import logging
from datetime import timedelta
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry # Import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DanalockApiClient, DanalockApiClientError, DanalockApiAuthError
from .const import DOMAIN, LOCK_SERIAL, LOCK_NAME

_LOGGER = logging.getLogger(__name__)

class DanalockDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching Danalock data."""

    # Add config_entry attribute
    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry, # Accept ConfigEntry
        api_client: DanalockApiClient,
        locks: List[Dict[str, str]],
        update_interval_minutes: int,
    ) -> None:
        """Initialize."""
        self.api_client = api_client
        self.locks = {lock[LOCK_SERIAL]: lock for lock in locks}
        self.config_entry = config_entry # Store ConfigEntry

        update_interval = timedelta(minutes=max(1, update_interval_minutes))
        _LOGGER.debug("Danalock coordinator update interval: %s", update_interval)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        _LOGGER.debug("Coordinator attempting to update data for %d locks", len(self.locks))
        lock_data = {}
        try:
            # Token validity check and persistence is handled within the client now
            # await self.api_client._ensure_token_valid() # No longer needed here

            tasks = {
                serial: self.hass.async_create_task(
                    self.api_client.get_lock_data(serial)
                )
                for serial in self.locks
            }

            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            for serial, result in zip(tasks.keys(), results):
                if isinstance(result, ConfigEntryAuthFailed):
                    _LOGGER.error("Authentication failed during data update for lock %s", serial)
                    raise result # Let the main exception handler catch this
                elif isinstance(result, Exception):
                    _LOGGER.warning(
                        "Error fetching data for lock %s: %s", serial, result
                    )
                    lock_data[serial] = {}
                elif isinstance(result, dict):
                    result[LOCK_NAME] = self.locks[serial].get(LOCK_NAME, "Unknown")
                    lock_data[serial] = result
                else:
                     _LOGGER.warning("Unexpected result type for lock %s: %s", serial, type(result))
                     lock_data[serial] = {}

            _LOGGER.debug("Coordinator update finished. Data: %s", lock_data)
            return lock_data

        except ConfigEntryAuthFailed as err:
            # No need to explicitly trigger reauth here anymore,
            # as ApiClient handles password auth attempt.
            # If it still fails, HA should mark entry for reauth based on this exception.
            _LOGGER.warning("Authentication error during coordinator update: %s", err)
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except DanalockApiClientError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
             _LOGGER.exception("Unexpected error during coordinator update")
             raise UpdateFailed(f"Unexpected error: {err}") from err

