"""Lock platform for Danalock Cloud."""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DanalockApiClient
from .const import (
    API_STATE_LOCKED,
    API_STATE_UNLOCKED,
    COMMAND_UPDATE_DELAY,
    DOMAIN,
    EVENT_LOCK_COMMAND_FAILURE,  # Import event constants
    EVENT_LOCK_COMMAND_SUCCESS,  # Import event constants
    LOCK_BATTERY,
    LOCK_NAME,
    LOCK_SERIAL,
    LOCK_STATE,
)
from .coordinator import DanalockDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Danalock lock entities based on a config entry."""
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        _LOGGER.error(
            "Danalock Cloud domain data not found for entry %s", entry.entry_id
        )
        return

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanalockDataUpdateCoordinator = data["coordinator"]
    api_client: DanalockApiClient = data["api_client"]
    locks_info: List[Dict[str, str]] = data["locks"]

    entities = []
    if not locks_info:
        _LOGGER.info("No Danalock locks found to set up for entry %s", entry.title)
        return

    for lock_info in locks_info:
        serial = lock_info.get(LOCK_SERIAL)
        if not serial:
            _LOGGER.warning(
                "Skipping lock due to missing serial number: %s", lock_info
            )
            continue

        entities.append(DanalockLockEntity(coordinator, api_client, lock_info))

    if entities:
        async_add_entities(entities)
        _LOGGER.info(
            "Added %d Danalock lock entities for %s", len(entities), entry.title
        )


class DanalockLockEntity(CoordinatorEntity[DanalockDataUpdateCoordinator], LockEntity):
    """Representation of a Danalock lock."""

    _attr_has_entity_name = True
    _attr_is_locked = None
    # Add OPEN feature - assumes 'unlock' also unlatches for now
    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(
        self,
        coordinator: DanalockDataUpdateCoordinator,
        api_client: DanalockApiClient,
        lock_info: Dict[str, str],
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(coordinator)
        self._api_client = api_client
        self._lock_info = lock_info
        self._serial = lock_info[LOCK_SERIAL]
        self._attr_name = lock_info.get(LOCK_NAME, f"Danalock {self._serial}")
        self._attr_unique_id = f"danalock_cloud_{self._serial}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self._attr_name,
            manufacturer="Danalock",
            model="V3 (Cloud)",
        )
        self._update_state()
        self._attr_available = True

        _LOGGER.debug(
            "Created lock entity: %s (Serial: %s, State: %s, Available: %s)",
            self._attr_name,
            self._serial,
            self._attr_is_locked,
            self._attr_available,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug(
            "Updating state for lock %s from coordinator data", self._serial
        )
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Update internal state attributes based on coordinator data."""
        if not self.coordinator.data:
            _LOGGER.debug(
                "No coordinator data available yet for %s", self._serial
            )
            return

        if self._serial not in self.coordinator.data:
            _LOGGER.debug("Lock %s missing from coordinator data", self._serial)
            return

        lock_data = self.coordinator.data[self._serial]
        state = lock_data.get(LOCK_STATE)

        if state == API_STATE_LOCKED:
            if self._attr_is_locked is not True:
                _LOGGER.debug("Lock %s state updated to: LOCKED", self._serial)
            self._attr_is_locked = True
        elif state == API_STATE_UNLOCKED:
            if self._attr_is_locked is not False:
                _LOGGER.debug("Lock %s state updated to: UNLOCKED", self._serial)
            self._attr_is_locked = False
        elif state is None:
            _LOGGER.debug(
                "Lock %s state returned as None from API, keeping previous state: %s",
                self._serial,
                "Locked"
                if self._attr_is_locked
                else "Unlocked"
                if self._attr_is_locked is False
                else "Unknown",
            )
        else:
            _LOGGER.warning(
                "Lock %s received unexpected state from API: %s",
                self._serial,
                state,
            )

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        _LOGGER.info(
            "Locking %s (%s) - current state: %s",
            self._attr_name,
            self._serial,
            "Locked"
            if self._attr_is_locked
            else "Unlocked"
            if self._attr_is_locked is False
            else "Unknown",
        )

        self._attr_is_locking = True
        self._attr_is_locked = True
        self.async_write_ha_state()

        success = False
        error_message = None
        try:
            _LOGGER.debug("Calling api_client.lock for %s", self._serial)
            success = await self._api_client.lock(self._serial)
            _LOGGER.debug(
                "Lock API call completed with result: %s", success
            )
        except Exception as e:
            _LOGGER.exception(
                "Unexpected exception during lock API call: %s", e
            )
            success = False
            error_message = str(e)
        finally:
            self._attr_is_locking = False

        if success:
            _LOGGER.info(
                "Successfully sent lock command for %s", self._attr_name
            )
            self.hass.bus.async_fire(
                EVENT_LOCK_COMMAND_SUCCESS,
                {
                    "entity_id": self.entity_id,
                    "serial_number": self._serial,
                    "command": "lock",
                },
            )
            self.hass.async_create_task(self._delayed_update())
        else:
            _LOGGER.error(
                "Failed to lock %s - API returned failure or exception occurred",
                self._attr_name,
            )
            self.hass.bus.async_fire(
                EVENT_LOCK_COMMAND_FAILURE,
                {
                    "entity_id": self.entity_id,
                    "serial_number": self._serial,
                    "command": "lock",
                    "error": error_message or "API returned failure",
                },
            )
            self._attr_is_locked = None
            await self.coordinator.async_request_refresh()

        self.async_write_ha_state()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        _LOGGER.info(
            "Unlocking %s (%s) - current state: %s",
            self._attr_name,
            self._serial,
            "Locked"
            if self._attr_is_locked
            else "Unlocked"
            if self._attr_is_locked is False
            else "Unknown",
        )

        self._attr_is_unlocking = True
        self._attr_is_locked = False
        self.async_write_ha_state()

        success = False
        error_message = None
        try:
            _LOGGER.debug("Calling api_client.unlock for %s", self._serial)
            success = await self._api_client.unlock(self._serial)
            _LOGGER.debug(
                "Unlock API call completed with result: %s", success
            )
        except Exception as e:
            _LOGGER.exception(
                "Unexpected exception during unlock API call: %s", e
            )
            success = False
            error_message = str(e)
        finally:
            self._attr_is_unlocking = False

        if success:
            _LOGGER.info(
                "Successfully sent unlock command for %s", self._attr_name
            )
            self.hass.bus.async_fire(
                EVENT_LOCK_COMMAND_SUCCESS,
                {
                    "entity_id": self.entity_id,
                    "serial_number": self._serial,
                    "command": "unlock",
                },
            )
            self.hass.async_create_task(self._delayed_update())
        else:
            _LOGGER.error(
                "Failed to unlock %s - API returned failure or exception occurred",
                self._attr_name,
            )
            self.hass.bus.async_fire(
                EVENT_LOCK_COMMAND_FAILURE,
                {
                    "entity_id": self.entity_id,
                    "serial_number": self._serial,
                    "command": "unlock",
                    "error": error_message or "API returned failure",
                },
            )
            self._attr_is_locked = None
            await self.coordinator.async_request_refresh()

        self.async_write_ha_state()

    async def async_open(self, **kwargs: Any) -> None:
        """Open the lock (unlatch). Assumes same as unlock for now."""
        _LOGGER.info(
            "Opening (unlatching) %s - calling unlock", self._attr_name
        )
        # If Danalock has a specific 'open' or 'unlatch' command,
        # call a dedicated api_client method here.
        # For now, we assume 'open' means 'unlock'.
        await self.async_unlock(**kwargs)

    async def _delayed_update(self) -> None:
        """Perform a delayed update to get the actual lock state."""
        _LOGGER.debug(
            "Scheduling delayed update for %s in %s seconds",
            self._attr_name,
            COMMAND_UPDATE_DELAY.total_seconds(),
        )
        await asyncio.sleep(COMMAND_UPDATE_DELAY.total_seconds())
        if self.coordinator:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.warning(
                "Coordinator not available for delayed update of %s",
                self._attr_name,
            )
