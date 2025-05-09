"""Lock platform for Danalock Cloud."""
import asyncio # Ensure asyncio is imported
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
    EVENT_LOCK_COMMAND_FAILURE,
    EVENT_LOCK_COMMAND_SUCCESS,
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
    _attr_is_locked = None # Initial state is unknown until first update
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
        # Use the name from lock_info, fallback to a default
        self._attr_name = lock_info.get(LOCK_NAME, f"Danalock {self._serial}")
        self._attr_unique_id = f"danalock_cloud_{self._serial}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=self._attr_name, # Use the same name for the device
            manufacturer="Danalock",
            model="V3 (Cloud)",
        )
        # Initialize state from coordinator if data is already available
        self._update_state_from_coordinator()
        # Entity is available by default, coordinator will update if API fails long-term
        self._attr_available = True


    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # The lock is available if the coordinator is, or if it's the first update.
        # This prevents the lock from becoming unavailable during initial setup.
        return self.coordinator.last_update_success or not self.coordinator.data


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug(
            "Coordinator update received for lock %s.", self._serial
        )
        self._update_state_from_coordinator()
        self.async_write_ha_state()

    def _update_state_from_coordinator(self) -> None:
        """Update internal state attributes based on coordinator data."""
        if not self.coordinator.data or self._serial not in self.coordinator.data:
            _LOGGER.debug("No data for lock %s in coordinator update.", self._serial)
            # Don't change state if no data, keep last known state
            return

        lock_data = self.coordinator.data[self._serial]
        state = lock_data.get(LOCK_STATE) # This could be None if get_lock_data failed

        current_ha_state = self._attr_is_locked
        new_ha_state = current_ha_state # Default to no change

        if state == API_STATE_LOCKED:
            new_ha_state = True
        elif state == API_STATE_UNLOCKED:
            new_ha_state = False
        elif state is None:
            _LOGGER.debug(
                "Lock %s state from API was None. Retaining current HA state: %s",
                self._serial,
                "Locked" if current_ha_state else "Unlocked" if current_ha_state is False else "Unknown"
            )
            # No change to new_ha_state, it remains current_ha_state
        else:
            _LOGGER.warning(
                "Lock %s received unexpected state from API via coordinator: %s. Retaining current HA state.",
                self._serial, state
            )
            # No change to new_ha_state

        if new_ha_state != current_ha_state:
            _LOGGER.info("Lock %s state changing from %s to %s", self._serial, current_ha_state, new_ha_state)
            self._attr_is_locked = new_ha_state
        else:
            _LOGGER.debug("Lock %s state (%s) unchanged by coordinator update.", self._serial, current_ha_state)


    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the device."""
        _LOGGER.info("Attempting to lock %s (%s)", self._attr_name, self._serial)

        self._attr_is_locking = True
        self.async_write_ha_state()

        success = False
        error_message = None
        try:
            success = await self._api_client.lock(self._serial)
        except Exception as e:
            _LOGGER.exception("Exception during lock API call for %s: %s", self._serial, e)
            error_message = str(e)
        finally:
            self._attr_is_locking = False
            self.async_write_ha_state() # Update to remove "locking" attribute

        if success:
            _LOGGER.info("Lock command successful for %s. Requesting delayed update.", self._attr_name)
            self.hass.bus.async_fire(EVENT_LOCK_COMMAND_SUCCESS, {"entity_id": self.entity_id, "command": "lock"})
            self.hass.async_create_task(self._delayed_update())
        else:
            _LOGGER.error("Failed to send lock command for %s. Error: %s. State may be stale.", self._attr_name, error_message or "API returned failure")
            self.hass.bus.async_fire(EVENT_LOCK_COMMAND_FAILURE, {"entity_id": self.entity_id, "command": "lock", "error": error_message or "API returned failure"})
            if self.coordinator:
                await self.coordinator.async_request_refresh()


    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the device."""
        _LOGGER.info("Attempting to unlock %s (%s)", self._attr_name, self._serial)

        self._attr_is_unlocking = True
        self.async_write_ha_state()

        success = False
        error_message = None
        try:
            success = await self._api_client.unlock(self._serial)
        except Exception as e:
            _LOGGER.exception("Exception during unlock API call for %s: %s", self._serial, e)
            error_message = str(e)
        finally:
            self._attr_is_unlocking = False
            self.async_write_ha_state() # Update to remove "unlocking" attribute

        if success:
            _LOGGER.info("Unlock command successful for %s. Requesting delayed update.", self._attr_name)
            self.hass.bus.async_fire(EVENT_LOCK_COMMAND_SUCCESS, {"entity_id": self.entity_id, "command": "unlock"})
            self.hass.async_create_task(self._delayed_update())
        else:
            _LOGGER.error("Failed to send unlock command for %s. Error: %s. State may be stale.", self._attr_name, error_message or "API returned failure")
            self.hass.bus.async_fire(EVENT_LOCK_COMMAND_FAILURE, {"entity_id": self.entity_id, "command": "unlock", "error": error_message or "API returned failure"})
            if self.coordinator:
                await self.coordinator.async_request_refresh()

    async def async_open(self, **kwargs: Any) -> None:
        """Open the lock (unlatch). Assumes same as unlock for now."""
        _LOGGER.info("Opening (unlatching) %s - calling unlock", self._attr_name)
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
            _LOGGER.debug("Requesting refresh from coordinator for %s after delay.", self._attr_name)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.warning(
                "Coordinator not available for delayed update of %s",
                self._attr_name,
            )
