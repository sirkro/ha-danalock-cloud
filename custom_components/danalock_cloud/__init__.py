"""The Danalock Cloud integration."""
import asyncio
import logging
from time import time
from typing import Any, Dict, List, Optional
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, Platform, CONF_PASSWORD
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv
import voluptuous as vol


from .api import (
    DanalockApiClient,
    DanalockApiAuthError,
    DanalockApiClientError,
)
from .const import (
    DOMAIN,
    PLATFORMS,
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    TOKEN_EXPIRES_AT,
    LOCK_SERIAL,
    LOCK_NAME,
    UPDATE_INTERVAL,
    SERVICE_REFRESH_DEVICES,
)
from .coordinator import DanalockDataUpdateCoordinator


_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH_SCHEMA = vol.Schema({})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Danalock Cloud component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Danalock Cloud from a config entry."""
    _LOGGER.info("Setting up Danalock Cloud entry for %s (%s)", entry.title, entry.entry_id)

    username = entry.data[CONF_USERNAME]
    password = entry.data.get(CONF_PASSWORD)
    access_token = entry.data.get(ACCESS_TOKEN)
    refresh_token = entry.data.get(REFRESH_TOKEN)
    token_expires_at = entry.data.get(TOKEN_EXPIRES_AT)

    # --- Pass the entry object to the client ---
    api_client = DanalockApiClient(
        hass,
        entry=entry, # Pass the config entry itself
        username=username,
        password=password,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
    )

    try:
        _LOGGER.debug("[%s] Ensuring token validity or attempting initial auth.", entry.entry_id)
        # This will now attempt self-healing and persist updated tokens if needed
        await api_client._ensure_token_valid()

        _LOGGER.debug("[%s] Fetching initial list of locks.", entry.entry_id)
        locks = await api_client.get_locks()
        if not locks:
            _LOGGER.warning("[%s] No Danalock locks found for account %s.", entry.entry_id, username)

    except ConfigEntryAuthFailed as err:
        _LOGGER.error("[%s] Authentication failed during setup: %s", entry.entry_id, err)
        # No need to explicitly trigger reauth here, HA should do it based on the exception
        raise
    except (DanalockApiClientError, Exception) as err:
        _LOGGER.error("[%s] Failed to connect or get locks during setup: %s", entry.entry_id, err, exc_info=True)
        raise ConfigEntryNotReady(f"Failed to initialize Danalock API: {err}") from err

    # Token persistence is now handled within the ApiClient after successful validation/refresh

    update_interval_minutes = entry.options.get(
        "update_interval", int(UPDATE_INTERVAL.total_seconds() / 60)
    )

    coordinator = DanalockDataUpdateCoordinator(
        hass,
        config_entry=entry, # Pass entry to coordinator too
        api_client=api_client,
        locks=locks or [],
        update_interval_minutes=update_interval_minutes,
    )

    _LOGGER.debug("[%s] Performing initial data refresh.", entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    if not coordinator.last_update_success and isinstance(coordinator.last_exception, ConfigEntryAuthFailed):
         _LOGGER.error("[%s] Initial data refresh failed authentication.", entry.entry_id)
         raise coordinator.last_exception

    hass.data[DOMAIN][entry.entry_id] = {
        "api_client": api_client,
        "coordinator": coordinator,
        "locks": locks or [],
    }

    _LOGGER.debug("[%s] Forwarding setup to platforms: %s", entry.entry_id, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(options_update_listener))

    # --- Register Refresh Service ---
    # (Service registration code remains the same)
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_DEVICES):
        _LOGGER.info("Registering service: %s.%s", DOMAIN, SERVICE_REFRESH_DEVICES)

        async def handle_refresh_devices(call: ServiceCall) -> None:
            """Handle the service call to refresh device data for all configured entries."""
            _LOGGER.info("Service %s.%s called, forcing data refresh for all entries", DOMAIN, SERVICE_REFRESH_DEVICES)
            coordinators = [
                entry_data["coordinator"]
                for entry_id, entry_data in hass.data.get(DOMAIN, {}).items()
                if "coordinator" in entry_data
            ]
            if not coordinators:
                 _LOGGER.warning("Refresh service called, but no coordinators found.")
                 return

            await asyncio.gather(
                *[coord.async_request_refresh() for coord in coordinators]
            )
            _LOGGER.info("Refresh requested for %d coordinator(s).", len(coordinators))

        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_DEVICES,
            handle_refresh_devices,
            schema=SERVICE_REFRESH_SCHEMA,
        )
    # --- End Service Registration ---


    _LOGGER.info("[%s] Danalock Cloud setup complete for %s", entry.entry_id, entry.title)
    return True

# async_unload_entry and options_update_listener remain the same

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_id = entry.entry_id
    _LOGGER.info("Unloading Danalock Cloud entry for %s (%s)", entry.title, entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry_id, None)
        _LOGGER.info("Danalock Cloud entry %s data removed.", entry_id)

        # --- Unregister Service ---
        if not any(e.domain == DOMAIN for e in hass.config_entries.async_loaded_entries(hass)):
             _LOGGER.info("Last Danalock Cloud entry unloaded, removing service %s.%s", DOMAIN, SERVICE_REFRESH_DEVICES)
             hass.services.async_remove(DOMAIN, SERVICE_REFRESH_DEVICES)
        # --- End Service Unregistration ---

    _LOGGER.info("Danalock Cloud entry %s unloaded result: %s", entry_id, unload_ok)
    return unload_ok

async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update without reloading the entry."""
    entry_id = entry.entry_id
    _LOGGER.info("Danalock Cloud options updating for %s", entry_id)

    if DOMAIN not in hass.data or entry_id not in hass.data.get(DOMAIN, {}):
        _LOGGER.warning("[%s] Cannot apply options update - entry data not found in hass.data. Triggering reload.", entry_id)
        await hass.config_entries.async_reload(entry_id)
        return

    data = hass.data[DOMAIN][entry_id]
    coordinator: Optional[DanalockDataUpdateCoordinator] = data.get("coordinator")

    if not coordinator:
        _LOGGER.error("[%s] Cannot apply options update - coordinator not found. Triggering reload.", entry_id)
        await hass.config_entries.async_reload(entry_id)
        return

    update_interval_minutes = entry.options.get(
        "update_interval", int(UPDATE_INTERVAL.total_seconds() / 60)
    )
    new_interval = timedelta(minutes=max(1, update_interval_minutes))

    if coordinator.update_interval == new_interval:
        _LOGGER.debug("[%s] Options updated, but update interval (%s) is unchanged.", entry_id, new_interval)
        return

    _LOGGER.info(
        "[%s] Updating polling interval from %s to %s",
        entry_id,
        coordinator.update_interval,
        new_interval
    )
    coordinator.update_interval = new_interval
    _LOGGER.info("[%s] Successfully updated polling interval.", entry_id)
