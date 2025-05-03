"""Sensor platform for Danalock Cloud."""
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo


from .const import DOMAIN, LOCK_BATTERY, LOCK_NAME, LOCK_SERIAL
from .coordinator import DanalockDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Danalock sensor entities based on a config entry."""
    # Ensure domain data exists
    if DOMAIN not in hass.data or entry.entry_id not in hass.data[DOMAIN]:
        _LOGGER.error("Danalock Cloud domain data not found for entry %s", entry.entry_id)
        return

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanalockDataUpdateCoordinator = data["coordinator"]
    locks_info: List[Dict[str, str]] = data["locks"]

    entities = []
    if not locks_info:
         _LOGGER.info("No Danalock locks found to set up sensors for entry %s", entry.title)
         return

    for lock_info in locks_info:
        serial = lock_info.get(LOCK_SERIAL)
        if not serial:
            _LOGGER.warning("Skipping battery sensor due to missing lock serial number: %s", lock_info)
            continue

        # Create the sensor entity even if initial data is missing.
        # It will become available when the coordinator gets data.
        entities.append(DanalockBatterySensor(coordinator, lock_info))

    if entities:
        async_add_entities(entities)
        _LOGGER.info("Added %d Danalock battery sensor entities for %s", len(entities), entry.title)


class DanalockBatterySensor(CoordinatorEntity[DanalockDataUpdateCoordinator], SensorEntity):
    """Representation of a Danalock battery sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True # Enable by default

    def __init__(
        self,
        coordinator: DanalockDataUpdateCoordinator,
        lock_info: Dict[str, str],
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self._lock_info = lock_info
        self._serial = lock_info[LOCK_SERIAL]
        self._attr_name = "Battery" # Entity name suffix
        self._attr_unique_id = f"danalock_cloud_{self._serial}_battery"
        
        # Link to the same device as the lock entity
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            # No need to redefine name, manufacturer etc. here,
            # it merges with the lock's device info.
        )
        
        # Initialize state based on coordinator's initial data
        self._update_state()
        
        # Initialize as available even if state isn't known yet
        self._attr_available = True

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Updating battery state for lock %s from coordinator", self._serial)
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Update internal state attributes based on coordinator data."""
        # Default behavior: keep entity available even if no value
        self._attr_available = True
        
        if not self.coordinator.data:
            _LOGGER.debug("No coordinator data available for battery sensor %s", self._serial)
            return
            
        if self._serial not in self.coordinator.data:
            _LOGGER.debug("Battery sensor for lock %s not found in coordinator data", self._serial)
            return
            
        lock_data = self.coordinator.data[self._serial]
        battery_level = lock_data.get(LOCK_BATTERY)
        
        if battery_level is not None:
            # Validate type and range, allow 0
            if isinstance(battery_level, int) and 0 <= battery_level <= 100:
                self._attr_native_value = battery_level
                _LOGGER.debug("Battery sensor %s updated to %s%%", 
                             self._serial, battery_level)
            else:
                _LOGGER.warning("Invalid battery level value '%s' for %s", 
                               battery_level, self._serial)
        else:
            _LOGGER.debug("No battery data available for %s", self._serial)
