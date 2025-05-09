# custom_components/danalock_cloud/coordinator.py

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DanalockApiClient, DanalockApiClientError, DanalockApiAuthError
from .const import DOMAIN, LOCK_SERIAL, LOCK_NAME

_LOGGER = logging.getLogger(__name__)

class DanalockDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching Danalock data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api_client: DanalockApiClient,
        locks: List[Dict[str, str]],
        update_interval_minutes: int,
    ) -> None:
        """Initialize."""
        self.api_client = api_client
        self.locks = {lock[LOCK_SERIAL]: lock for lock in locks if LOCK_SERIAL in lock}
        self.config_entry = config_entry

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
        lock_data_results = {}
        try:
            # The _ensure_token_valid call is implicitly handled by api_client methods now
            tasks = {
                serial: self.hass.async_create_task(
                    self.api_client.get_lock_data(serial)
                )
                for serial in self.locks
            }

            # Gather results, allowing individual tasks to fail without stopping all
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            for serial, result in zip(tasks.keys(), results):
                if isinstance(result, ConfigEntryAuthFailed):
                    # If any lock fetch fails auth, this will be the primary error
                    _LOGGER.error("Authentication failed during data update for lock %s", serial)
                    raise result # Propagate the auth error to stop further processing
                elif isinstance(result, Exception):
                    _LOGGER.warning(
                        "Error fetching data for lock %s: %s. This lock's data will be unavailable.", serial, result
                    )
                    lock_data_results[serial] = {} # Mark as failed for this lock
                elif isinstance(result, dict):
                    # Add lock name for easier identification in diagnostics/logs
                    result[LOCK_NAME] = self.locks.get(serial, {}).get(LOCK_NAME, "Unknown")
                    lock_data_results[serial] = result
                else:
                     _LOGGER.warning("Unexpected result type for lock %s: %s", serial, type(result))
                     lock_data_results[serial] = {}

            _LOGGER.debug("Coordinator update finished. Data: %s", lock_data_results)
            return lock_data_results

        except ConfigEntryAuthFailed as err:
            _LOGGER.warning("Authentication error during coordinator update: %s. This will trigger reauth flow if needed.", err)
            # Let HA handle the reauth state based on this exception
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except DanalockApiClientError as err: # Catch specific client errors that are not auth
            _LOGGER.error("API Client error during coordinator update: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err: # Catch any other unexpected errors
             _LOGGER.exception("Unexpected error during coordinator update")
             raise UpdateFailed(f"Unexpected error: {err}") from err
