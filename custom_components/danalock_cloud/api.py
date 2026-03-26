"""API Client for Danalock Cloud."""
import asyncio
import logging
from time import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ACCESS_TOKEN,
    API_BASE_URL,
    ARG_LOCK,
    ARG_UNLOCK,
    BRIDGE_API_BASE_URL,
    CLIENT_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_TIMEOUT,
    EXECUTE_URL,
    EXPIRES_IN,
    JOB_POLL_INTERVAL,
    JOB_POLL_TIMEOUT,
    JOB_STATUS_FAILED,
    JOB_STATUS_IN_PROGRESS,
    JOB_STATUS_SUCCEEDED,
    LOCKS_URL,
    LOCK_BATTERY,
    LOCK_NAME,
    LOCK_SERIAL,
    LOCK_STATE,
    OP_GET_BATTERY,
    OP_GET_STATE,
    OP_LOCK,
    OP_UNLOCK,
    POLL_URL,
    REFRESH_TOKEN,
    TOKEN_URL,
    API_STATE_LOCKED,
    API_STATE_UNLOCKED,
    TOKEN_EXPIRES_AT,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"

# Backoff settings for consecutive token refresh failures
_BACKOFF_BASE: float = 2.0       # seconds
_BACKOFF_MAX: float = 300.0      # 5 minutes cap

class DanalockApiClientError(Exception):
    """Base exception for API client errors."""
class DanalockApiAuthError(DanalockApiClientError):
    """Exception for authentication errors."""
class DanalockApiError(DanalockApiClientError):
    """Exception for general API errors."""
class DanalockJobError(DanalockApiClientError):
    """Exception for job execution/polling errors."""


class DanalockApiClient:
    """Danalock Cloud API Client."""

    _hass: HomeAssistant
    _entry: Optional[ConfigEntry]
    _username: str
    _password: Optional[str]
    _access_token: Optional[str]
    _refresh_token: Optional[str]
    _token_expires_at: float
    _pending_refresh_token: Optional[str] # For "use-then-save" logic

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: Optional[str] = None,
        entry: Optional[ConfigEntry] = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[float] = None,
    ) -> None:
        """Initialize the API client."""
        self._hass = hass
        self._entry = entry
        self._username = username
        self._password = password
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = token_expires_at or 0.0
        self._pending_refresh_token = None # Initialize pending token
        self._session = async_get_clientsession(hass)
        self._lock = asyncio.Lock()
        self._consecutive_auth_failures: int = 0
        self._next_auth_attempt_at: float = 0.0

    async def _persist_updated_tokens(self) -> None:
        """Save current tokens back to the ConfigEntry. Password is NOT persisted here."""
        if not self._entry:
            return

        new_data = {
            CONF_USERNAME: self._username,
            # Password is kept from the existing entry data to avoid writing it
            # back on every token refresh. It is only written during explicit
            # user-initiated auth (initial setup / reauth flow).
            CONF_PASSWORD: self._entry.data.get(CONF_PASSWORD),
            ACCESS_TOKEN: self._access_token,
            REFRESH_TOKEN: self._refresh_token,
            TOKEN_EXPIRES_AT: self._token_expires_at,
        }

        if self._entry.data != new_data:
            _LOGGER.info("[%s] Persisting updated tokens to config entry.", self._entry.entry_id)
            self._hass.config_entries.async_update_entry(
                self._entry, data=new_data
            )

    async def _activate_pending_refresh_token(self) -> None:
        """Promote the pending refresh token to the active one and persist."""
        if self._pending_refresh_token:
            _LOGGER.info("Activating and persisting new refresh token after successful API call.")
            self._refresh_token = self._pending_refresh_token
            self._pending_refresh_token = None
            await self._persist_updated_tokens()

    async def _request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        expect_json: bool = True,
        use_auth: bool = True,
    ) -> Any:
        """Make an API request, handling authentication and errors."""
        final_headers = {"User-Agent": DEFAULT_USER_AGENT}
        if headers:
            final_headers.update(headers)

        if use_auth:
            await self._ensure_token_valid()
            if not self._access_token:
                 raise ConfigEntryAuthFailed("Access token missing after validation check.")
            final_headers["Authorization"] = f"Bearer {self._access_token}"

        log_headers = {k: ("[REDACTED]" if k.lower() == "authorization" else v) for k, v in final_headers.items()}
        _LOGGER.debug("Request: %s %s (Headers: %s, Data: %s, Json: %s)", method, url, log_headers, data, json)

        try:
            async with self._session.request(
                method,
                url,
                headers=final_headers,
                data=data,
                json=json,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as response:
                _LOGGER.debug("Response Status: %s for %s", response.status, url)
                response_text_content = None

                if not (200 <= response.status < 300):
                    try:
                        response_text_content = await response.text()
                    except Exception:
                        response_text_content = "Could not read response text."
                    is_auth_endpoint = url == TOKEN_URL
                    log_body = "[REDACTED - auth endpoint]" if is_auth_endpoint else response_text_content
                    _LOGGER.error("API Error %s for %s %s: %s", response.status, method, url, log_body)
                    if response.status == 401:
                        raise ConfigEntryAuthFailed(f"Authentication failed (401) for {url}")
                    raise DanalockApiError(f"API request failed: {response.status} - {response_text_content}")

                # After a successful authenticated call, activate any pending refresh token
                if use_auth and self._pending_refresh_token:
                    await self._activate_pending_refresh_token()

                if expect_json:
                    try:
                        return await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        response_text_content = await response.text()
                        _LOGGER.error("API response was not valid JSON. Content: %s. Error: %s", response_text_content, err)
                        raise DanalockApiError(f"Invalid JSON response from API: {err}")
                else:
                    return await response.text()

        except aiohttp.ClientConnectorError as e:
            raise DanalockApiClientError(f"Connection error: {e}") from e
        except asyncio.TimeoutError:
            raise DanalockApiClientError("Request timed out") from TimeoutError
        except (ConfigEntryAuthFailed, DanalockApiError, DanalockApiClientError):
             raise
        except Exception as e:
            _LOGGER.exception("An unexpected error occurred during API request to %s", url)
            raise DanalockApiClientError(f"Unexpected error during request: {e}") from e


    async def async_validate_auth(self) -> None:
        """Public method to ensure the token is valid. Raises ConfigEntryAuthFailed if not."""
        await self._ensure_token_valid()

    async def _ensure_token_valid(self) -> None:
        """Ensure the access token is valid, refreshing or triggering reauth if necessary."""
        async with self._lock:
            current_time = time()
            if self._access_token and self._token_expires_at and self._token_expires_at >= (current_time + 60):
                return

            # Enforce backoff if previous refresh attempts have failed
            if self._next_auth_attempt_at > current_time:
                wait_seconds = round(self._next_auth_attempt_at - current_time)
                _LOGGER.warning(
                    "Auth backoff active: skipping token refresh for another %ds after %d consecutive failure(s).",
                    wait_seconds,
                    self._consecutive_auth_failures,
                )
                raise ConfigEntryAuthFailed(
                    f"Auth backoff active. Retry in {wait_seconds}s."
                )

            _LOGGER.debug("Token invalid or expiring soon. Attempting recovery.")
            last_auth_error = None

            if self._refresh_token:
                _LOGGER.debug("Attempting token refresh.")
                try:
                    await self._refresh_access_token()
                    if self._access_token and self._token_expires_at and self._token_expires_at >= (current_time + 60):
                        _LOGGER.debug("Token refresh successful.")
                        self._consecutive_auth_failures = 0
                        self._next_auth_attempt_at = 0.0
                        return
                except (DanalockApiAuthError, ConfigEntryAuthFailed) as err:
                    _LOGGER.warning("Refresh token failed (%s). Triggering re-authentication.", err)
                    last_auth_error = err
                    self._access_token = self._refresh_token = self._pending_refresh_token = None
                    self._token_expires_at = 0.0

            self._consecutive_auth_failures += 1
            backoff = min(_BACKOFF_BASE ** self._consecutive_auth_failures, _BACKOFF_MAX)
            self._next_auth_attempt_at = current_time + backoff
            _LOGGER.error(
                "Authentication required. Failure #%d. Next attempt allowed in %.0fs.",
                self._consecutive_auth_failures,
                backoff,
            )
            if self._entry:
                self._entry.async_start_reauth(self._hass)
            raise ConfigEntryAuthFailed(
                f"Authentication required. Token refresh failed or no tokens available. "
                f"Retry in {backoff:.0f}s."
            ) from last_auth_error


    async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate with username/password. Updates internal state and persists."""
        _LOGGER.info("Authenticating user %s", username)
        data = { "grant_type": "password", "username": username, "password": password, "client_id": CLIENT_ID }
        headers = {"content-type": "application/x-www-form-urlencoded"}
        try:
            response = await self._request("POST", TOKEN_URL, data=data, headers=headers, use_auth=False)
            if not isinstance(response, dict) or not all(k in response for k in [ACCESS_TOKEN, REFRESH_TOKEN, EXPIRES_IN]):
                 raise DanalockApiAuthError("Invalid authentication response format")
            self._access_token = response[ACCESS_TOKEN]
            self._refresh_token = response[REFRESH_TOKEN]
            self._token_expires_at = time() + response[EXPIRES_IN]
            self._username = username
            self._password = password
            self._pending_refresh_token = None
            self._consecutive_auth_failures = 0
            self._next_auth_attempt_at = 0.0
            _LOGGER.info("Authentication successful. Persisting new tokens.")
            await self._persist_updated_tokens()
            return response
        except (DanalockApiError, ConfigEntryAuthFailed) as e:
            raise DanalockApiAuthError("Invalid username or password") from e


    async def _refresh_access_token(self) -> None:
        """Refresh the access token. Updates internal state but does not persist new refresh token until used."""
        _LOGGER.info("Refreshing access token for user %s", self._username)
        if not self._refresh_token:
            raise DanalockApiAuthError("Missing refresh token for refresh attempt.")
        data = { "grant_type": "refresh_token", "refresh_token": self._refresh_token, "client_id": CLIENT_ID }
        headers = {"content-type": "application/x-www-form-urlencoded"}
        try:
            response = await self._request("POST", TOKEN_URL, data=data, headers=headers, use_auth=False)
            if not isinstance(response, dict) or not all(k in response for k in [ACCESS_TOKEN, REFRESH_TOKEN, EXPIRES_IN]):
                 raise DanalockApiAuthError("Invalid token refresh response format")
            self._access_token = response[ACCESS_TOKEN]
            self._token_expires_at = time() + response[EXPIRES_IN]
            self._pending_refresh_token = response.get(REFRESH_TOKEN)
            # Persist only the access token and expiry for now
            await self._persist_updated_tokens()
            _LOGGER.info("Access token refreshed. New refresh token is pending activation.")
        except (DanalockApiError, ConfigEntryAuthFailed) as e:
            raise DanalockApiAuthError("Invalid refresh token") from e

    async def get_lock_data(self, serial_number: str) -> Dict[str, Any]:
        """Fetch both state and battery level for a lock sequentially."""
        _LOGGER.debug("Fetching sequential data for lock %s", serial_number)
        state, battery = None, None
        try:
            state = await self.get_lock_state(serial_number)
            await asyncio.sleep(1) # Small delay between execute calls
            battery = await self.get_battery_level(serial_number)
        except ConfigEntryAuthFailed:
            _LOGGER.error("Authentication failure during sequential data fetch for %s", serial_number)
            raise
        except Exception as e:
            _LOGGER.exception("Unexpected error during sequential get_lock_data for %s", serial_number)

        return { LOCK_STATE: state, LOCK_BATTERY: battery }

    async def get_lock_state(self, serial_number: str) -> Optional[str]:
        """Get the current state (Locked/Unlocked) of a lock."""
        _LOGGER.debug("Attempting to get lock state for %s", serial_number)
        try:
            result = await self._execute_and_poll(serial_number, OP_GET_STATE)
            state = result.get("state")
            if state in (API_STATE_LOCKED, API_STATE_UNLOCKED):
                 return state
            _LOGGER.warning("Received unexpected state '%s' for lock %s", state, serial_number)
            return None
        except DanalockJobError as e:
            if "bridgebusy" in str(e).lower() or "timed out" in str(e).lower():
                _LOGGER.warning("API issue getting state for lock %s: %s", serial_number, e)
            else:
                _LOGGER.error("Failed to get state for lock %s: %s", serial_number, e)
            return None
        except Exception as e:
            _LOGGER.exception("Unexpected error getting lock state for %s", serial_number)
            return None

    async def get_battery_level(self, serial_number: str) -> Optional[int]:
        """Get the current battery level of a lock."""
        _LOGGER.debug("Attempting to get battery level for %s", serial_number)
        try:
            result = await self._execute_and_poll(serial_number, OP_GET_BATTERY)
            battery = result.get("battery_level")
            if isinstance(battery, int) and 0 <= battery <= 100:
                return battery
            _LOGGER.warning("Received invalid battery level '%s' for lock %s", battery, serial_number)
            return None
        except DanalockJobError as e:
            if "bridgebusy" in str(e).lower() or "timed out" in str(e).lower():
                _LOGGER.warning("API issue getting battery for lock %s: %s", serial_number, e)
            else:
                _LOGGER.error("Failed to get battery level for lock %s: %s", serial_number, e)
            return None
        except Exception as e:
            _LOGGER.exception("Unexpected error getting battery level for %s", serial_number)
            return None

    async def get_locks(self) -> List[Dict[str, Any]]:
        """Retrieve a list of locks associated with the account."""
        _LOGGER.info("Fetching list of locks")
        headers = { "content-type": "application/json", "Accept": "application/json" }
        response = await self._request("GET", LOCKS_URL, headers=headers)
        locks = []
        if isinstance(response, list):
            for lock_data in response:
                try:
                    afi_data = lock_data.get("afi")
                    serial = afi_data.get("serial_number") if isinstance(afi_data, dict) else None
                    name = lock_data.get("name")
                    if serial and name:
                        locks.append({LOCK_SERIAL: serial, LOCK_NAME: name})
                except Exception as e:
                     _LOGGER.warning("Error processing lock data entry %s: %s", lock_data, e, exc_info=True)
        else:
             raise DanalockApiError("Invalid format received for locks list")
        _LOGGER.info("Found %d locks: %s", len(locks), [l.get(LOCK_NAME, 'Unknown') for l in locks])
        return locks

    async def _execute_and_poll(
        self,
        serial_number: str,
        operation: str,
        arguments: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute a command via the bridge and poll for its result."""
        _LOGGER.info("Executing operation '%s' for lock %s", operation, serial_number)
        payload = { "device": serial_number, "operation": operation }
        if arguments:
            payload["arguments"] = arguments
        headers = { "content-type": "application/json", "Accept": "application/json" }
        try:
            exec_response = await self._request("POST", EXECUTE_URL, json=payload, headers=headers)
            job_id = exec_response.get("id")
            if not job_id:
                raise DanalockJobError("Failed to get job ID from execute response")
        except (ConfigEntryAuthFailed, DanalockApiError, DanalockApiClientError) as e:
            raise DanalockJobError(f"Failed to execute command {operation}") from e

        start_time = time()
        while time() < start_time + JOB_POLL_TIMEOUT:
            await asyncio.sleep(JOB_POLL_INTERVAL)
            try:
                poll_payload = {"id": job_id}
                poll_response = await self._request("POST", POLL_URL, json=poll_payload, headers=headers)
                status = poll_response.get("status")
                if status == JOB_STATUS_SUCCEEDED:
                    _LOGGER.info("Job %s for %s succeeded", job_id, operation)
                    return poll_response.get("result", {})
                elif status == JOB_STATUS_FAILED:
                    error_detail = poll_response.get("result", {}).get("bridge_server_status_text", "Unknown failure")
                    raise DanalockJobError(f"Operation {operation} failed: {error_detail}")
                elif status in (JOB_STATUS_IN_PROGRESS, "Created"):
                    _LOGGER.debug("Job %s still in progress... (Status: %s)", job_id, operation, status)
                    continue
                else:
                    raise DanalockJobError(f"Operation {operation} returned unexpected status: {status}")
            except (ConfigEntryAuthFailed, DanalockApiError, DanalockApiClientError) as e:
                raise DanalockJobError(f"Polling failed for operation {operation}") from e
        raise DanalockJobError(f"Operation {operation} timed out")

    async def lock(self, serial_number: str) -> bool:
        """Send lock command."""
        try:
            await self._execute_and_poll(serial_number, OP_LOCK, arguments=[ARG_LOCK])
            return True
        except DanalockJobError as e:
            _LOGGER.error("Failed to lock %s: %s", serial_number, e)
            return False

    async def unlock(self, serial_number: str) -> bool:
        """Send unlock command."""
        try:
            await self._execute_and_poll(serial_number, OP_UNLOCK, arguments=[ARG_UNLOCK])
            return True
        except DanalockJobError as e:
            _LOGGER.error("Failed to unlock %s: %s", serial_number, e)
            return False
