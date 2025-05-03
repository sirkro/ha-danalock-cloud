"""DataUpdateCoordinator for the Danalock Cloud integration."""
import asyncio
import logging
from datetime import timedelta, datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import (
    DanalockApiClient,
    DanalockApiAuthError,
    DanalockApiClientError,
    DanalockJobError,
)
from .const import (
    DOMAIN,
    LOCK_NAME,
    LOCK_SERIAL,
    LOCK_STATE,
    LOCK_BATTERY,
    UPDATE_INTERVAL, # Keep for default calculation reference if needed elsewhere
    COMMAND_UPDATE_DELAY,
)

_LOGGER = logging.getLogger(__name__)


class DanalockDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Dict[str, Any]]]):
    """Class to manage fetching Danalock data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: DanalockApiClient,
        locks: List[Dict[str, str]],
        update_interval_minutes: int,
    ) -> None:
        """Initialize the coordinator."""
        self.api_client = api_client
        self.locks = {lock[LOCK_SERIAL]: lock for lock in locks if LOCK_SERIAL in lock}
        self.last_update_success = False
        self.last_update_success_timestamp = None

        interval = timedelta(minutes=max(1, update_interval_minutes))
        _LOGGER.info("Initializing coordinator with update interval: %s", interval)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=interval, # Set initial interval here
        )
        # Note: The update_interval is now managed by the base class and the options listener

    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        """Fetch data from API endpoint."""
        _LOGGER.debug("Starting data update cycle for %d locks", len(self.locks))
        current_data: Dict[str, Dict[str, Any]] = {} # Use a temporary dict for new data

        if not self.locks:
            _LOGGER.debug("No locks to update.")
            self.last_update_success = True # Treat as success if no locks
            self.last_update_success_timestamp = datetime.now()
            return {}

        try:
            await self.api_client._ensure_token_valid()

            tasks = []
            serials = list(self.locks.keys())

            for serial in serials:
                tasks.append(self.api_client.get_lock_data(serial))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            update_successful_for_any_lock = False
            for i, result in enumerate(results):
                serial = serials[i]
                lock_info = self.locks[serial]
                lock_name = lock_info.get(LOCK_NAME, f"Lock {serial}")

                if isinstance(result, Exception):
                    _LOGGER.error("Failed to update data for lock %s (%s): %s", lock_name, serial, result)
                    # Keep existing data for this lock if available, otherwise mark as error
                    if self.data and serial in self.data:
                         current_data[serial] = self.data[serial].copy() # Keep old data
                         current_data[serial]["update_error"] = str(result) # Add error flag
                    else:
                         current_data[serial] = { # No previous data, mark as unavailable
                             LOCK_NAME: lock_name,
                             LOCK_STATE: None,
                             LOCK_BATTERY: None,
                             "update_error": str(result),
                         }
                elif isinstance(result, dict):
                    current_data[serial] = {
                        LOCK_NAME: lock_name,
                        LOCK_STATE: result.get(LOCK_STATE),
                        LOCK_BATTERY: result.get(LOCK_BATTERY),
                    }
                    update_successful_for_any_lock = True # Mark success if at least one lock updated
                    _LOGGER.debug("Data for lock %s: %s", serial, current_data[serial])
                else:
                    _LOGGER.error("Unexpected result type for lock %s (%s): %s", lock_name, serial, type(result))
                    if self.data and serial in self.data:
                         current_data[serial] = self.data[serial].copy()
                         current_data[serial]["update_error"] = f"Unexpected result type: {type(result).__name__}"
                    else:
                         current_data[serial] = {
                             LOCK_NAME: lock_name,
                             LOCK_STATE: None,
                             LOCK_BATTERY: None,
                             "update_error": f"Unexpected result type: {type(result).__name__}",
                         }

            # --- Prevent full unavailability ---
            # If the entire update failed (no data fetched successfully) but we had previous data,
            # return the previous data to keep entities available during transient errors.
            if not update_successful_for_any_lock and self.data:
                _LOGGER.warning("Data update failed for all locks, retaining previous data to maintain availability.")
                # Add error markers to the old data if desired
                for serial in self.data:
                    if serial not in current_data or "update_error" not in current_data[serial]:
                         # Ensure an error marker exists if we're returning old data due to full failure
                         error_msg = "Update failed (retained old data)"
                         if serial in current_data and "update_error" in current_data[serial]:
                            error_msg = current_data[serial]["update_error"] # Use specific error if available

                         # Create a copy to avoid modifying the actual self.data
                         temp_data = self.data[serial].copy()
                         temp_data["update_error"] = error_msg
                         current_data[serial] = temp_data # Overwrite with old data + error

                self.last_update_success = False # Mark overall update as failed
                # Don't update last_update_success_timestamp on failure
                return self.data # Return the *previous* data object

            # --- Update successful ---
            self.last_update_success = True
            self.last_update_success_timestamp = datetime.now()
            _LOGGER.debug("Data update cycle finished. Data points retrieved: %d", len(current_data))
            return current_data # Return the newly fetched data

        except DanalockApiAuthError as err:
            self.last_update_success = False
            _LOGGER.error("Authentication error during update: %s", err)
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except (DanalockApiClientError, DanalockJobError) as err:
            self.last_update_success = False
            _LOGGER.error("Error communicating with Danalock API during update: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            self.last_update_success = False
            _LOGGER.exception("Unexpected error during data update coordinator run")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_request_refresh_after_delay(self, delay: timedelta) -> None:
        """Request refresh after delay."""
        _LOGGER.debug("Scheduling refresh after %s seconds", delay.total_seconds())
        await asyncio.sleep(delay.total_seconds())
        await self.async_request_refresh()

