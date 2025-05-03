"""The Danalock Cloud integration."""
import asyncio
import logging
from time import time
from typing import Any, Dict, List, Optional
from datetime import timedelta # Added for options listener

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, Platform
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
    CONF_PASSWORD,
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    TOKEN_EXPIRES_AT,
    LOCK_SERIAL,
    LOCK_NAME,
    UPDATE_INTERVAL,
    SERVICE_REFRESH_DEVICES,
)
from .coordinator import DanalockDataUpdateCoordinator
from .diagnostics import async_get_config_entry_diagnostics


_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH_SCHEMA = vol.Schema({})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Danalock Cloud component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Danalock Cloud from a config entry."""
    _LOGGER.info("Setting up Danalock Cloud entry for %s (%s)", entry.title, entry.entry_id)

    access_token = entry.data.get(ACCESS_TOKEN)
    refresh_token = entry.data.get(REFRESH_TOKEN)
    token_expires_at = entry.data.get(TOKEN_EXPIRES_AT)
    username = entry.data[CONF_USERNAME]

    if not access_token or not refresh_token:
        _LOGGER.error("[%s] Stored tokens missing, cannot initialize API client.", entry.entry_id)
        raise ConfigEntryAuthFailed("Authentication tokens missing.")

    api_client = DanalockApiClient(
        hass,
        username=username,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
    )

    try:
        _LOGGER.debug("[%s] Ensuring token validity before fetching locks.", entry.entry_id)
        await api_client._ensure_token_valid() # Check token early
        _LOGGER.debug("[%s] Fetching initial list of locks.", entry.entry_id)
        locks = await api_client.get_locks()
        if not locks:
            _LOGGER.warning("[%s] No Danalock locks found for account %s.", entry.entry_id, username)

    except DanalockApiAuthError as err:
        _LOGGER.error("[%s] Authentication failed during setup: %s", entry.entry_id, err)
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
    except (DanalockApiClientError, Exception) as err:
        _LOGGER.error("[%s] Failed to connect or get locks during setup: %s", entry.entry_id, err, exc_info=True)
        raise ConfigEntryNotReady(f"Failed to initialize Danalock API: {err}") from err

    update_interval_minutes = entry.options.get(
        "update_interval", int(UPDATE_INTERVAL.total_seconds() / 60)
    )

    coordinator = DanalockDataUpdateCoordinator(
        hass,
        api_client=api_client,
        locks=locks or [],
        update_interval_minutes=update_interval_minutes,
    )

    _LOGGER.debug("[%s] Performing initial data refresh.", entry.entry_id)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "api_client": api_client,
        "coordinator": coordinator,
        "locks": locks or [],
    }

    _LOGGER.debug("[%s] Forwarding setup to platforms: %s", entry.entry_id, PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add listener for options updates (uses the new function below)
    entry.async_on_unload(entry.add_update_listener(options_update_listener))

    # --- Register Refresh Service ---
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_DEVICES):
        _LOGGER.info("Registering service: %s.%s", DOMAIN, SERVICE_REFRESH_DEVICES)

        async def handle_refresh_devices(call: ServiceCall) -> None:
            """Handle the service call to refresh device data for all configured entries."""
            _LOGGER.info("Service %s.%s called, forcing data refresh for all entries", DOMAIN, SERVICE_REFRESH_DEVICES)
            coordinators = [
                entry_data["coordinator"]
                for entry_id, entry_data in hass.data.get(DOMAIN, {}).items() # Added .get() for safety
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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_id = entry.entry_id
    _LOGGER.info("Unloading Danalock Cloud entry for %s (%s)", entry.title, entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry_id, None)
        _LOGGER.info("Danalock Cloud entry %s data removed.", entry_id)

        # --- Unregister Service ---
        if not hass.data.get(DOMAIN): # Check if domain data is empty
             _LOGGER.info("Last Danalock Cloud entry unloaded, removing service %s.%s", DOMAIN, SERVICE_REFRESH_DEVICES)
             hass.services.async_remove(DOMAIN, SERVICE_REFRESH_DEVICES)
        # --- End Service Unregistration ---

    _LOGGER.info("Danalock Cloud entry %s unloaded result: %s", entry_id, unload_ok)
    return unload_ok

# --- NEW Options Update Listener ---
async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update without reloading the entry."""
    entry_id = entry.entry_id
    _LOGGER.info("Danalock Cloud options updating for %s", entry_id)

    if entry_id not in hass.data.get(DOMAIN, {}):
        _LOGGER.error("[%s] Cannot apply options update - entry data not found in hass.data", entry_id)
        return # Or force reload: await hass.config_entries.async_reload(entry.entry_id)

    data = hass.data[DOMAIN][entry_id]
    coordinator: Optional[DanalockDataUpdateCoordinator] = data.get("coordinator")

    if not coordinator:
        _LOGGER.error("[%s] Cannot apply options update - coordinator not found", entry_id)
        # Fall back to full reload if coordinator isn't there for some reason
        _LOGGER.info("[%s] Falling back to full reload due to missing coordinator during options update.", entry_id)
        await hass.config_entries.async_reload(entry_id)
        return

    # Get the new update interval from options
    update_interval_minutes = entry.options.get(
        "update_interval", int(UPDATE_INTERVAL.total_seconds() / 60) # Fallback to default
    )

    # Calculate the new interval timedelta
    new_interval = timedelta(minutes=max(1, update_interval_minutes)) # Ensure at least 1 minute

    if coordinator.update_interval == new_interval:
        _LOGGER.debug("[%s] Options updated, but update interval (%s) is unchanged.", entry_id, new_interval)
        return # No change needed

    _LOGGER.info(
        "[%s] Updating polling interval from %s to %s",
        entry_id,
        coordinator.update_interval,
        new_interval
    )

    # Update the coordinator's interval directly
    coordinator.update_interval = new_interval

    # The coordinator's internal scheduling logic will automatically
    # use the new interval the next time it schedules an update.
    # We can optionally trigger an immediate refresh to apply it sooner,
    # but it's not strictly necessary. Let's trigger one for responsiveness.
    _LOGGER.debug("[%s] Requesting immediate refresh to apply new interval.", entry_id)
    await coordinator.async_request_refresh()

    _LOGGER.info("[%s] Successfully updated polling interval.", entry_id)

# --- End NEW Options Update Listener ---

# Link diagnostics function (already imported)
# async_get_config_entry_diagnostics = async_get_config_entry_diagnostics
