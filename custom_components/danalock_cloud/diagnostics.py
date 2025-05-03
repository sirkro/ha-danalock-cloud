"""Diagnostics support for Danalock Cloud."""
from __future__ import annotations

import time
import logging
from typing import Any, Dict, Optional

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, ACCESS_TOKEN, REFRESH_TOKEN, TOKEN_EXPIRES_AT

_LOGGER = logging.getLogger(__name__)

TO_REDACT = {
    CONF_PASSWORD,
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    TOKEN_EXPIRES_AT,
    "password",
    "token",
    "tokens",
    "access_token",
    "refresh_token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    try:
        # Start with basic entry information
        diag_data = {
            "entry": {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "version": entry.version,
                "domain": entry.domain,
                "source": entry.source,
                "state": entry.state,
                # Don't include raw data or options to avoid leaking sensitive info
            },
            "options": {
                "update_interval": entry.options.get("update_interval", "not set")
            },
        }

        # Check if the domain data exists
        if DOMAIN not in hass.data or entry.entry_id not in hass.data.get(DOMAIN, {}):
            diag_data["error"] = "Integration data not found. Setup may have failed or is in progress."
            return diag_data

        data = hass.data[DOMAIN][entry.entry_id]
        
        # Safe extraction of coordinator info
        coordinator = data.get("coordinator")
        if coordinator:
            try:
                coordinator_info = {
                    "last_update_success": coordinator.last_update_success,
                    "last_update_timestamp": coordinator.last_update_success_timestamp.isoformat() 
                                            if coordinator.last_update_success_timestamp else None,
                    "update_interval": str(coordinator.update_interval),
                    "has_data": bool(coordinator.data),
                    "data_keys": list(coordinator.data.keys()) if coordinator.data else [],
                }
                
                # Safely extract some coordinator data for diagnostics
                if coordinator.data:
                    # Create a safe copy, only including non-sensitive keys and redacted values
                    safe_data = {}
                    for serial, lock_data in coordinator.data.items():
                        if isinstance(lock_data, dict):
                            safe_data[serial] = {
                                "has_state": "state" in lock_data,
                                "has_battery": "battery_level" in lock_data,
                                "name": lock_data.get("name", "Unknown"),
                            }
                    
                    coordinator_info["data_sample"] = safe_data
                
                diag_data["coordinator"] = coordinator_info
            except Exception as err:
                diag_data["coordinator_error"] = f"Error extracting coordinator info: {err}"
        
        # Safely extract lock info
        locks_info = data.get("locks", [])
        if locks_info:
            try:
                diag_data["locks_discovered"] = [
                    {"name": lock.get("name", "Unknown")} for lock in locks_info
                ]
                diag_data["lock_count"] = len(locks_info)
            except Exception as err:
                diag_data["locks_error"] = f"Error extracting locks info: {err}"
        else:
            diag_data["locks_discovered"] = "No locks found"
        
        # API client info (carefully redacted)
        api_client = data.get("api_client")
        if api_client:
            try:
                # Safe extraction of expiry info
                token_expiry = getattr(api_client, "_token_expires_at", None)
                expiry_info = {}
                
                if token_expiry and isinstance(token_expiry, (int, float)) and token_expiry > 0:
                    try:
                        current_time = time.time()
                        expiry_info = {
                            "expires_in_seconds": max(0, round(token_expiry - current_time)),
                            "expired": token_expiry < current_time,
                            # Don't include the actual timestamp
                        }
                    except Exception:
                        expiry_info = {"error": "Unable to calculate expiry"}
                
                diag_data["api_client_info"] = {
                    "has_access_token": bool(getattr(api_client, "_access_token", None)),
                    "has_refresh_token": bool(getattr(api_client, "_refresh_token", None)),
                    "token_expiry": expiry_info,
                }
            except Exception as err:
                diag_data["api_client_error"] = f"Error extracting API client info: {err}"
                
        # Add version info
        diag_data["diagnostics_version"] = "1.0.1"
        
        return diag_data
        
    except Exception as err:
        _LOGGER.exception("Error generating diagnostics")
        return {
            "error": f"Failed to generate diagnostics: {err}",
            "entry_id": entry.entry_id
        }
