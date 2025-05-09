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
        self._session = async_get_clientsession(hass)
        self._lock = asyncio.Lock()

    async def _persist_updated_tokens(self) -> None:
        """Save potentially updated tokens and password back to the ConfigEntry."""
        if not self._entry:
            _LOGGER.debug("API Client instance has no ConfigEntry, skipping token persistence.")
            return

        # Construct the data to be saved, ensuring all necessary fields are present
        # and reflect the current state of the API client.
        new_data = {
            CONF_USERNAME: self._username, # Username should always be there
            CONF_PASSWORD: self._password, # Persist current password state (could be None if cleared)
            ACCESS_TOKEN: self._access_token,
            REFRESH_TOKEN: self._refresh_token,
            TOKEN_EXPIRES_AT: self._token_expires_at,
        }

        # Get a fresh copy of the current entry data to compare against
        current_entry_data = self._entry.data.copy()

        # Only update if there's an actual change in the relevant fields
        if (current_entry_data.get(ACCESS_TOKEN) != new_data[ACCESS_TOKEN] or
            current_entry_data.get(REFRESH_TOKEN) != new_data[REFRESH_TOKEN] or
            current_entry_data.get(TOKEN_EXPIRES_AT) != new_data[TOKEN_EXPIRES_AT] or
            current_entry_data.get(CONF_PASSWORD) != new_data[CONF_PASSWORD]):
            _LOGGER.info("[%s] Persisting updated tokens/password to config entry.", self._entry.entry_id)
            self._hass.config_entries.async_update_entry(
                self._entry, data=new_data
            )
        else:
            _LOGGER.debug("[%s] Tokens/password checked, no changes needed for persistence.", self._entry.entry_id)


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
        if use_auth:
            await self._ensure_token_valid()
            req_headers = headers.copy() if headers else {}
            if not self._access_token:
                 _LOGGER.error("Access token missing after validation check for %s.", url)
                 raise ConfigEntryAuthFailed("Access token missing after validation check.")
            req_headers["Authorization"] = f"Bearer {self._access_token}"
        else:
            req_headers = headers

        _LOGGER.debug("Request: %s %s (Headers: %s, Data: %s, Json: %s)", method, url, req_headers, data, json)

        try:
            async with self._session.request(
                method,
                url,
                headers=req_headers,
                data=data,
                json=json,
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT),
            ) as response:
                _LOGGER.debug("Response Status: %s", response.status)

                if response.status == 401:
                     _LOGGER.warning("API request to %s failed with 401 (Unauthorized).", url)
                     if use_auth: # Only clear tokens if auth was supposed to be used
                         async with self._lock:
                             self._access_token = None
                             self._token_expires_at = 0.0
                             # Do not clear refresh_token here, _ensure_token_valid will handle it
                     raise ConfigEntryAuthFailed(f"Authentication failed (401) for {url}")

                if not (200 <= response.status < 300):
                    error_text = await response.text()
                    _LOGGER.error("API Error %s for %s %s: %s", response.status, method, url, error_text)
                    raise DanalockApiError(f"API request failed: {response.status} - {error_text}")

                if expect_json:
                    try:
                        resp_json = await response.json(content_type=None)
                        _LOGGER.debug("Response JSON: %s", resp_json)
                        return resp_json
                    except ValueError as json_err:
                        resp_text_err = await response.text()
                        _LOGGER.error("API response was not valid JSON. Content: %s. Error: %s", resp_text_err, json_err)
                        raise DanalockApiError(f"Invalid JSON response from API: {json_err}")
                    except Exception as e:
                         _LOGGER.error("Error parsing JSON response: %s", e)
                         raise DanalockApiError(f"Failed to parse JSON response: {e}")
                else:
                    resp_text = await response.text()
                    _LOGGER.debug("Response Text: %s", resp_text)
                    return resp_text

        except aiohttp.ClientConnectorError as e:
            _LOGGER.error("Connection error to %s: %s", url, e)
            raise DanalockApiClientError(f"Connection error: {e}") from e
        except asyncio.TimeoutError:
            _LOGGER.error("Request timed out after %s seconds for URL %s", DEFAULT_TIMEOUT, url)
            raise DanalockApiClientError("Request timed out") from TimeoutError
        except ConfigEntryAuthFailed:
             raise
        except DanalockApiAuthError as e: # Should be caught by ConfigEntryAuthFailed already
             raise ConfigEntryAuthFailed("Authentication required") from e
        except Exception as e:
            _LOGGER.exception("An unexpected error occurred during API request to %s", url)
            raise DanalockApiClientError(f"Unexpected error during request: {e}") from e


    async def _ensure_token_valid(self) -> None:
        """Ensure the access token is valid, refreshing or re-authenticating if necessary."""
        async with self._lock:
            current_time = time()
            if self._access_token and self._token_expires_at and self._token_expires_at >= (current_time + 60):
                return

            _LOGGER.debug("Token invalid or expiring soon. Attempting recovery.")
            auth_successful = False
            last_auth_error = None

            if self._refresh_token:
                _LOGGER.debug("Attempting token refresh using refresh token.")
                try:
                    await self._refresh_access_token() # Persists on success internally
                    if self._access_token and self._token_expires_at and self._token_expires_at >= (current_time + 60):
                        _LOGGER.debug("Token refresh successful.")
                        auth_successful = True
                except (DanalockApiAuthError, ConfigEntryAuthFailed) as err:
                     _LOGGER.warning("Refresh token failed (%s). Invalidating tokens and attempting password auth.", err)
                     last_auth_error = err
                     self._access_token = None
                     self._refresh_token = None
                     self._token_expires_at = 0.0
                except Exception as e:
                     _LOGGER.error("Unexpected error during token refresh: %s", e, exc_info=True)
                     last_auth_error = e
                     self._access_token = None
                     self._refresh_token = None
                     self._token_expires_at = 0.0

            if not auth_successful and self._password:
                _LOGGER.info("Attempting full authentication using stored password.")
                try:
                    await self.authenticate(self._username, self._password) # Persists on success internally
                    if self._access_token and self._token_expires_at and self._token_expires_at >= (current_time + 60):
                        _LOGGER.info("Password authentication successful.")
                        auth_successful = True
                        last_auth_error = None
                    else:
                         _LOGGER.error("Password authentication attempt finished, but tokens are still invalid.")
                         if not last_auth_error:
                             last_auth_error = ConfigEntryAuthFailed("Password authentication failed unexpectedly.")
                except (DanalockApiAuthError, ConfigEntryAuthFailed) as err:
                     _LOGGER.error("Password authentication failed: %s. Clearing stored password.", err)
                     last_auth_error = err
                     self._password = None
                     self._access_token = None
                     self._refresh_token = None
                     self._token_expires_at = 0.0
                     await self._persist_updated_tokens() # Persist cleared password
                except Exception as e:
                    _LOGGER.error("Unexpected error during password authentication: %s. Clearing stored password.", e, exc_info=True)
                    last_auth_error = e
                    self._password = None
                    self._access_token = None
                    self._refresh_token = None
                    self._token_expires_at = 0.0
                    await self._persist_updated_tokens()

            if not auth_successful:
                final_error_msg = "Authentication required. All recovery attempts (refresh token, stored password) failed."
                _LOGGER.error(final_error_msg)
                if self._entry:
                    _LOGGER.warning("[%s] Triggering reauth flow due to persistent authentication failure.", self._entry.entry_id)
                    self._entry.async_start_reauth(self._hass)
                raise ConfigEntryAuthFailed(final_error_msg) from last_auth_error


    async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate with username/password. Updates internal state and persists."""
        _LOGGER.info("Authenticating user %s", username)
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": CLIENT_ID,
        }
        headers = {"content-type": "application/x-www-form-urlencoded"}

        try:
            response = await self._request(
                "POST", TOKEN_URL, data=data, headers=headers, use_auth=False
            )
            if not isinstance(response, dict) or not all(k in response for k in [ACCESS_TOKEN, REFRESH_TOKEN, EXPIRES_IN]):
                 _LOGGER.error("Authentication response missing required keys: %s", response)
                 raise DanalockApiAuthError("Invalid authentication response format")

            self._access_token = response[ACCESS_TOKEN]
            self._refresh_token = response[REFRESH_TOKEN]
            self._token_expires_at = time() + response[EXPIRES_IN]
            self._username = username
            self._password = password # Store the valid password

            _LOGGER.info("Authentication successful. Persisting new tokens.")
            await self._persist_updated_tokens()

            return {
                ACCESS_TOKEN: self._access_token,
                REFRESH_TOKEN: self._refresh_token,
                EXPIRES_IN: response[EXPIRES_IN],
                TOKEN_EXPIRES_AT: self._token_expires_at,
            }
        except (DanalockApiError, DanalockApiClientError, ConfigEntryAuthFailed) as e:
            _LOGGER.error("Authentication failed: %s", e)
            err_str = str(e).lower()
            if "invalid_grant" in err_str or "invalid credentials" in err_str or "unauthorized" in err_str or "401" in err_str:
                 raise DanalockApiAuthError("Invalid username or password") from e
            raise DanalockApiAuthError(f"Authentication failed due to API error: {e}") from e


    async def _refresh_access_token(self) -> None:
        """Refresh the access token. Updates internal state and persists."""
        _LOGGER.info("Refreshing access token for user %s", self._username)
        if not self._refresh_token:
            # This should ideally be caught by _ensure_token_valid before calling.
            raise DanalockApiAuthError("Missing refresh token for refresh attempt.")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": CLIENT_ID,
        }
        headers = {"content-type": "application/x-www-form-urlencoded"}

        try:
            response = await self._request(
                "POST", TOKEN_URL, data=data, headers=headers, use_auth=False
            )
            if not isinstance(response, dict) or not all(k in response for k in [ACCESS_TOKEN, REFRESH_TOKEN, EXPIRES_IN]):
                 _LOGGER.error("Token refresh response missing required keys: %s", response)
                 raise DanalockApiAuthError("Invalid token refresh response format")

            self._access_token = response[ACCESS_TOKEN]
            new_refresh_token = response.get(REFRESH_TOKEN)
            if new_refresh_token and new_refresh_token != self._refresh_token:
                _LOGGER.info("Received new refresh token during refresh.")
                self._refresh_token = new_refresh_token
            elif not new_refresh_token:
                 _LOGGER.warning("Refresh token response did not contain a new refresh token; old one will be reused if still valid.")

            self._token_expires_at = time() + response[EXPIRES_IN]
            _LOGGER.info("Access token refreshed successfully.")
            await self._persist_updated_tokens() # Persist new tokens

        except (DanalockApiError, DanalockApiClientError, ConfigEntryAuthFailed) as e:
            _LOGGER.error("Failed to refresh access token: %s", e)
            if "invalid_grant" in str(e).lower() or "401" in str(e):
                 raise DanalockApiAuthError("Invalid refresh token") from e
            raise DanalockApiAuthError(f"Token refresh failed due to API error: {e}") from e

    async def get_locks(self) -> List[Dict[str, Any]]:
        """Retrieve a list of locks associated with the account."""
        _LOGGER.info("Fetching list of locks")
        headers = {
            "content-type": "application/json",
            "Accept": "application/json",
        }
        response = await self._request("GET", LOCKS_URL, headers=headers)

        locks = []
        if isinstance(response, list):
            for lock_data in response:
                try:
                    afi_data = lock_data.get("afi") if isinstance(lock_data, dict) else None
                    serial = afi_data.get("serial_number") if isinstance(afi_data, dict) else None
                    name = lock_data.get("name") if isinstance(lock_data, dict) else None

                    if serial and name:
                        locks.append({LOCK_SERIAL: serial, LOCK_NAME: name})
                    else:
                        _LOGGER.warning("Found lock entry with missing serial or name: %s", lock_data)
                except Exception as e:
                     _LOGGER.warning("Error processing lock data entry %s: %s", lock_data, e, exc_info=True)
        else:
             _LOGGER.error("Unexpected format for locks response (expected list): %s", response)
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
        _LOGGER.info("Executing operation '%s' with args %s for lock %s",
                     operation, arguments, serial_number)
        payload = {
            "device": serial_number,
            "operation": operation,
        }
        if arguments:
            payload["arguments"] = arguments

        _LOGGER.debug("Full API payload for %s: %s", operation, payload)

        headers = {
            "content-type": "application/json",
            "Accept": "application/json",
        }

        try:
            exec_response = await self._request("POST", EXECUTE_URL, json=payload, headers=headers)
            if not isinstance(exec_response, dict):
                 _LOGGER.error("Execute response for %s was not a dictionary: %s", operation, exec_response)
                 raise DanalockJobError("Invalid format for execute response")

            job_id = exec_response.get("id")
            if not job_id:
                _LOGGER.error("Execute response for %s missing job ID: %s", operation, exec_response)
                raise DanalockJobError("Failed to get job ID from execute response")
            _LOGGER.debug("Job ID %s received for operation %s", job_id, operation)

        except ConfigEntryAuthFailed:
            _LOGGER.error("Authentication error during execute step for %s on %s", operation, serial_number)
            raise
        except (DanalockApiError, DanalockApiClientError) as e:
            _LOGGER.error("Failed to execute command %s for %s: %s", operation, serial_number, e)
            raise DanalockJobError(f"Failed to execute command {operation}") from e
        except Exception as e:
            _LOGGER.exception("Unexpected error during execute step for %s on %s", operation, serial_number)
            raise DanalockJobError(f"Unexpected error executing command {operation}") from e

        start_time = time()
        poll_count = 0
        last_status = None
        while time() < start_time + JOB_POLL_TIMEOUT:
            poll_count += 1
            _LOGGER.debug("Polling job %s for %s (Attempt %d)", job_id, operation, poll_count)

            if poll_count > 1:
                await asyncio.sleep(JOB_POLL_INTERVAL)

            try:
                poll_payload = {"id": job_id}
                poll_response = await self._request("POST", POLL_URL, json=poll_payload, headers=headers)

                if not isinstance(poll_response, dict):
                    _LOGGER.warning("Poll response for job %s was not a dictionary: %s", job_id, poll_response)
                    continue

                status = poll_response.get("status")
                result = poll_response.get("result", {})
                last_status = status

                _LOGGER.debug("Poll response for job %s: Status=%s, Result=%s", job_id, status, result)

                if status == JOB_STATUS_SUCCEEDED:
                    _LOGGER.info("Job %s for %s succeeded", job_id, operation)
                    return result if isinstance(result, dict) else {}
                elif status == JOB_STATUS_FAILED:
                    error_detail = "Unknown failure reason"
                    if isinstance(result, dict):
                        error_detail = result.get("bridge_server_status_text") \
                                    or result.get("afi_status_text") \
                                    or result.get("dmi_status_text") \
                                    or str(result)
                    _LOGGER.error("Job %s for %s failed: %s (Full Result: %s)", job_id, operation, error_detail, result)
                    raise DanalockJobError(f"Operation {operation} failed: {error_detail}")
                elif status == JOB_STATUS_IN_PROGRESS:
                    _LOGGER.debug("Job %s for %s still in progress...", job_id, operation)
                    continue
                elif status == "Created": # Handle 'Created' status explicitly if it persists
                    _LOGGER.debug("Job %s for %s still in 'Created' state. Continuing poll.", job_id, operation)
                    continue
                else:
                    _LOGGER.warning("Job %s for %s returned unexpected status: %s (Response: %s)", job_id, operation, status, poll_response)
                    raise DanalockJobError(f"Operation {operation} returned unexpected status: {status}")

            except ConfigEntryAuthFailed:
                 _LOGGER.error("Authentication error during polling job %s: %s", job_id)
                 raise
            except (DanalockApiError, DanalockApiClientError) as e:
                _LOGGER.error("Polling job %s failed: %s", job_id, e)
                raise DanalockJobError(f"Polling failed for operation {operation}") from e
            except Exception as e:
                _LOGGER.exception("Unexpected error during polling job %s", job_id)
                raise DanalockJobError(f"Unexpected polling error for operation {operation}") from e

        _LOGGER.error("Job %s for %s timed out after %s seconds (Last Status: %s)", job_id, operation, JOB_POLL_TIMEOUT, last_status)
        raise DanalockJobError(f"Operation {operation} timed out")


    async def get_lock_state(self, serial_number: str) -> Optional[str]:
        """Get the current state (Locked/Unlocked) of a lock."""
        _LOGGER.debug("Attempting to get lock state for %s", serial_number)
        try:
            result = await self._execute_and_poll(serial_number, OP_GET_STATE)
            state = result.get("state") if isinstance(result, dict) else None
            _LOGGER.debug("Received state '%s' for lock %s", state, serial_number)
            if state in (API_STATE_LOCKED, API_STATE_UNLOCKED):
                 return state
            else:
                 _LOGGER.warning("Received unexpected state '%s' for lock %s", state, serial_number)
                 return None
        except DanalockJobError as e:
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
            battery = result.get("battery_level") if isinstance(result, dict) else None
            _LOGGER.debug("Received battery level '%s' for lock %s", battery, serial_number)
            if isinstance(battery, int) and 0 <= battery <= 100:
                return battery
            else:
                 if battery == 0:
                     return 0
                 _LOGGER.warning("Received invalid battery level '%s' (type: %s) for lock %s", battery, type(battery).__name__, serial_number)
                 return None
        except DanalockJobError as e:
            _LOGGER.error("Failed to get battery level for lock %s: %s", serial_number, e)
            return None
        except Exception as e:
            _LOGGER.exception("Unexpected error getting battery level for %s", serial_number)
            return None

    async def lock(self, serial_number: str) -> bool:
        """Send lock command."""
        _LOGGER.info("Starting lock operation for %s", serial_number)
        try:
            _LOGGER.debug("Lock payload: operation=%s, arguments=%s", OP_LOCK, [ARG_LOCK])
            result = await self._execute_and_poll(serial_number, OP_LOCK, arguments=[ARG_LOCK])
            _LOGGER.info("Lock command successful for %s with result: %s", serial_number, result)
            return True
        except DanalockJobError as e:
            _LOGGER.error("Failed to lock %s: %s", serial_number, e)
            return False
        except Exception as e:
            _LOGGER.exception("Unexpected error during lock operation for %s: %s", serial_number, e)
            return False

    async def unlock(self, serial_number: str) -> bool:
        """Send unlock command."""
        _LOGGER.info("Starting unlock operation for %s", serial_number)
        try:
            _LOGGER.debug("Unlock payload: operation=%s, arguments=%s", OP_UNLOCK, [ARG_UNLOCK])
            result = await self._execute_and_poll(serial_number, OP_UNLOCK, arguments=[ARG_UNLOCK])
            _LOGGER.info("Unlock command successful for %s with result: %s", serial_number, result)
            return True
        except DanalockJobError as e:
            _LOGGER.error("Failed to unlock %s: %s", serial_number, e)
            return False
        except Exception as e:
            _LOGGER.exception("Unexpected error during unlock operation for %s: %s", serial_number, e)
            return False

    async def get_lock_data(self, serial_number: str) -> Dict[str, Any]:
        """Fetch both state and battery level for a lock concurrently."""
        _LOGGER.debug("Fetching concurrent data for lock %s", serial_number)

        async def _safe_get_state(serial):
            try:
                return await self.get_lock_state(serial)
            except ConfigEntryAuthFailed:
                raise
            except Exception as e:
                _LOGGER.warning("Failed to get state during concurrent fetch for %s: %s", serial, e)
                return None

        async def _safe_get_battery(serial):
            try:
                return await self.get_battery_level(serial)
            except ConfigEntryAuthFailed:
                raise
            except Exception as e:
                _LOGGER.warning("Failed to get battery during concurrent fetch for %s: %s", serial, e)
                return None

        state_task = asyncio.create_task(_safe_get_state(serial_number))
        battery_task = asyncio.create_task(_safe_get_battery(serial_number))

        try:
            state, battery = await asyncio.gather(state_task, battery_task)
        except ConfigEntryAuthFailed:
            _LOGGER.error("Authentication failure during concurrent data fetch for %s", serial_number)
            raise

        return {
            LOCK_STATE: state,
            LOCK_BATTERY: battery,
        }
