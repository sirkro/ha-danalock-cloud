"""API Client for Danalock Cloud."""
import asyncio
import logging
from time import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

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

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: Optional[str] = None, # Only used for initial auth if passed
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        token_expires_at: Optional[float] = None,
    ) -> None:
        """Initialize the API client."""
        self._hass = hass
        self._username = username
        self._password = password # Store temporarily if provided for initial auth
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expires_at = token_expires_at or 0.0
        self._session = async_get_clientsession(hass)
        self._lock = asyncio.Lock() # Lock for token refresh

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
        """Make an API request."""
        if use_auth:
            await self._ensure_token_valid()
            req_headers = headers.copy() if headers else {}
            # Ensure token is still valid after potential refresh before adding header
            if not self._access_token:
                 raise DanalockApiAuthError("Access token became invalid during request preparation.")
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
                # _LOGGER.debug("Response Headers: %s", response.headers) # Can be verbose

                if response.status == 401 and use_auth:
                     _LOGGER.warning("Authentication failed (401). Token might be invalid.")
                     # Clear potentially invalid token and raise specific error
                     async with self._lock:
                         self._access_token = None
                         self._refresh_token = None
                         self._token_expires_at = 0.0
                     raise DanalockApiAuthError("Authentication failed (401)")

                if not (200 <= response.status < 300):
                    try:
                        error_text = await response.text()
                        _LOGGER.error("API Error %s for %s %s: %s", response.status, method, url, error_text)
                    except Exception:
                        error_text = "Failed to get error details"
                        _LOGGER.error("API Error %s for %s %s: %s", response.status, method, url, error_text)
                    raise DanalockApiError(f"API request failed: {response.status} - {error_text}")

                if expect_json:
                    try:
                        resp_json = await response.json(content_type=None) # Allow any content type for json parsing
                        _LOGGER.debug("Response JSON: %s", resp_json)
                        return resp_json
                    except ValueError as json_err: # Catch JSON decode errors
                        resp_text_err = await response.text()
                        _LOGGER.error("API response was not valid JSON, though expected. Content: %s. Error: %s", resp_text_err, json_err)
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
        except DanalockApiAuthError: # Re-raise auth errors
             raise
        except Exception as e:
            _LOGGER.exception("An unexpected error occurred during API request to %s", url)
            raise DanalockApiClientError(f"Unexpected error during request: {e}") from e


    async def _ensure_token_valid(self) -> None:
        """Ensure the access token is valid, refreshing if necessary."""
        async with self._lock:
            needs_refresh = False
            current_time = time()

            if not self._access_token:
                _LOGGER.debug("Access token is missing.")
                needs_refresh = True
            elif self._token_expires_at and self._token_expires_at < (current_time + 60):
                 _LOGGER.debug("Access token expired or nearing expiry (expires at %s).", self._token_expires_at)
                 needs_refresh = True

            if needs_refresh:
                _LOGGER.debug("Attempting token refresh or re-authentication.")
                refreshed = False
                if self._refresh_token:
                    try:
                        await self._refresh_access_token()
                        refreshed = True # Mark as refreshed successfully
                    except DanalockApiAuthError as auth_err:
                         _LOGGER.warning("Refresh token failed (%s). Attempting full re-authentication.", auth_err)
                         # Fall through to password auth if possible
                    except Exception as e:
                         _LOGGER.error("Unexpected error during token refresh: %s", e)
                         # Don't try password auth if refresh had unexpected error
                         raise DanalockApiAuthError("Failed to refresh token") from e
                else:
                     _LOGGER.debug("No refresh token available.")

                # Attempt password auth if refresh failed or wasn't possible, and password exists
                if not refreshed:
                    if self._password:
                        _LOGGER.info("Attempting full authentication using stored password.")
                        try:
                            await self.authenticate(self._username, self._password)
                            # Clear password after successful re-auth if desired (more secure)
                            # self._password = None
                        except DanalockApiAuthError as e:
                             _LOGGER.error("Full re-authentication failed: %s", e)
                             raise # Re-raise auth error
                        except Exception as e:
                            _LOGGER.error("Unexpected error during full re-authentication: %s", e)
                            raise DanalockApiAuthError("Full re-authentication failed unexpectedly") from e
                    else:
                        _LOGGER.error("Token needs refresh/auth, but no refresh token or password available.")
                        raise ConfigEntryAuthFailed("Authentication required, but no credentials available.")

            # Final check: Do we have a token now?
            if not self._access_token:
                 _LOGGER.error("No valid access token available after refresh/auth attempt.")
                 raise DanalockApiAuthError("Missing access token after refresh/auth attempt")


    async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate with username and password to get tokens."""
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
                 _LOGGER.error("Authentication response missing required keys or not a dict: %s", response)
                 raise DanalockApiAuthError("Invalid authentication response format")

            self._access_token = response[ACCESS_TOKEN]
            self._refresh_token = response[REFRESH_TOKEN]
            self._token_expires_at = time() + response[EXPIRES_IN]
            self._username = username # Store username in case needed later
            # Store password temporarily if passed, might be cleared after use
            self._password = password
            _LOGGER.info("Authentication successful.")
            return {
                ACCESS_TOKEN: self._access_token,
                REFRESH_TOKEN: self._refresh_token,
                EXPIRES_IN: response[EXPIRES_IN], # Return original expires_in for storage
                TOKEN_EXPIRES_AT: self._token_expires_at, # Return calculated expiry time
            }
        except DanalockApiError as e:
            _LOGGER.error("Authentication failed: %s", e)
            # Check for specific invalid credential messages if API provides them
            err_str = str(e).lower()
            if "invalid_grant" in err_str or "invalid credentials" in err_str or "unauthorized" in err_str:
                 raise DanalockApiAuthError("Invalid username or password") from e
            raise DanalockApiAuthError(f"Authentication failed: {e}") from e


    async def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        _LOGGER.info("Refreshing access token for user %s", self._username)
        if not self._refresh_token:
            _LOGGER.error("Cannot refresh token: No refresh token available.")
            raise DanalockApiAuthError("Missing refresh token")

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
                 _LOGGER.error("Token refresh response missing required keys or not a dict: %s", response)
                 raise DanalockApiAuthError("Invalid token refresh response format")

            self._access_token = response[ACCESS_TOKEN]
            # Sometimes refresh might return a new refresh token
            self._refresh_token = response.get(REFRESH_TOKEN, self._refresh_token)
            self._token_expires_at = time() + response[EXPIRES_IN]
            _LOGGER.info("Access token refreshed successfully. New expiry: %s", self._token_expires_at)
        except DanalockApiError as e:
            _LOGGER.error("Failed to refresh access token: %s", e)
            # If refresh token is invalid, we need full re-auth
            if "invalid_grant" in str(e).lower():
                 raise DanalockApiAuthError("Invalid refresh token") from e
            raise DanalockApiAuthError(f"Token refresh failed: {e}") from e


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
                    # Defensive access to nested dictionary keys
                    afi_data = lock_data.get("afi") if isinstance(lock_data, dict) else None
                    serial = afi_data.get("serial_number") if isinstance(afi_data, dict) else None
                    name = lock_data.get("name") if isinstance(lock_data, dict) else None

                    if serial and name:
                        locks.append({LOCK_SERIAL: serial, LOCK_NAME: name})
                    else:
                        _LOGGER.warning("Found lock entry with missing serial or name: %s", lock_data)
                except Exception as e: # Catch any unexpected error during processing
                     _LOGGER.warning("Error processing lock data entry %s: %s", lock_data, e, exc_info=True)
        else:
             _LOGGER.error("Unexpected format for locks response (expected list): %s", response)
             raise DanalockApiError("Invalid format received for locks list")

        _LOGGER.info("Found %d locks: %s", len(locks), [l[LOCK_NAME] for l in locks])
        return locks


    async def _execute_and_poll(
        self,
        serial_number: str,
        operation: str,
        arguments: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Execute a command via the bridge and poll for its result."""
        # Enhanced logging
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

        # --- Step 1: Execute Command ---
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

        except (DanalockApiAuthError, DanalockApiError, DanalockApiClientError) as e:
            _LOGGER.error("Failed to execute command %s for %s: %s", operation, serial_number, e)
            raise DanalockJobError(f"Failed to execute command {operation}") from e
        except Exception as e:
            _LOGGER.exception("Unexpected error during execute step for %s on %s", operation, serial_number)
            raise DanalockJobError(f"Unexpected error executing command {operation}") from e


        # --- Step 2: Poll Job Status ---
        start_time = time()
        poll_count = 0
        last_status = None
        while time() < start_time + JOB_POLL_TIMEOUT:
            poll_count += 1
            _LOGGER.debug("Polling job %s for %s (Attempt %d)", job_id, operation, poll_count)

            # Add delay *before* polling (except first poll implicitly handled by loop start)
            if poll_count > 1:
                await asyncio.sleep(JOB_POLL_INTERVAL)

            try:
                poll_payload = {"id": job_id}
                poll_response = await self._request("POST", POLL_URL, json=poll_payload, headers=headers)

                if not isinstance(poll_response, dict):
                    _LOGGER.warning("Poll response for job %s was not a dictionary: %s", job_id, poll_response)
                    # Decide how to handle: continue polling or fail? Let's continue for now.
                    continue

                status = poll_response.get("status")
                result = poll_response.get("result", {})
                last_status = status # Keep track of the last seen status

                _LOGGER.debug("Poll response for job %s: Status=%s, Result=%s", job_id, status, result)

                if status == JOB_STATUS_SUCCEEDED:
                    _LOGGER.info("Job %s for %s succeeded", job_id, operation)
                    return result if isinstance(result, dict) else {} # Return result, ensure it's a dict
                elif status == JOB_STATUS_FAILED:
                    error_text = result.get("afi_status_text") or result.get("dmi_status_text") or "Unknown failure reason"
                    _LOGGER.error("Job %s for %s failed: %s (Result: %s)", job_id, operation, error_text, result)
                    raise DanalockJobError(f"Operation {operation} failed: {error_text}")
                elif status == JOB_STATUS_IN_PROGRESS:
                    _LOGGER.debug("Job %s for %s still in progress...", job_id, operation)
                    continue # Continue polling
                else:
                    _LOGGER.warning("Job %s for %s returned unexpected status: %s (Response: %s)", job_id, operation, status, poll_response)
                    # Treat unexpected status as failure? Let's raise immediately.
                    raise DanalockJobError(f"Operation {operation} returned unexpected status: {status}")

            except DanalockApiAuthError as e:
                 _LOGGER.error("Authentication error during polling job %s: %s", job_id, e)
                 raise # Re-raise auth errors immediately
            except (DanalockApiError, DanalockApiClientError) as e:
                _LOGGER.error("Polling job %s failed: %s", job_id, e)
                # Don't immediately fail the whole operation on a single poll error, maybe retry?
                # For simplicity now, let's fail it. Could add retry logic here later.
                raise DanalockJobError(f"Polling failed for operation {operation}") from e
            except Exception as e:
                _LOGGER.exception("Unexpected error during polling job %s", job_id)
                raise DanalockJobError(f"Unexpected polling error for operation {operation}") from e


        # If loop finishes, it timed out
        _LOGGER.error("Job %s for %s timed out after %s seconds (Last Status: %s)", job_id, operation, JOB_POLL_TIMEOUT, last_status)
        raise DanalockJobError(f"Operation {operation} timed out")


    async def get_lock_state(self, serial_number: str) -> Optional[str]:
        """Get the current state (Locked/Unlocked) of a lock."""
        _LOGGER.debug("Attempting to get lock state for %s", serial_number) # Added debug log
        try:
            result = await self._execute_and_poll(serial_number, OP_GET_STATE)
            state = result.get("state") if isinstance(result, dict) else None
            _LOGGER.debug("Received state '%s' for lock %s", state, serial_number) # Added debug log
            if state == API_STATE_LOCKED or state == API_STATE_UNLOCKED:
                 return state
            else:
                 _LOGGER.warning("Received unexpected state '%s' for lock %s", state, serial_number)
                 return None # Or raise an error? Returning None indicates unknown state.
        except DanalockJobError as e:
            _LOGGER.error("Failed to get state for lock %s: %s", serial_number, e)
            return None # Indicate state couldn't be retrieved
        except Exception as e: # Catch any other unexpected error
            _LOGGER.exception("Unexpected error getting lock state for %s", serial_number)
            return None

    async def get_battery_level(self, serial_number: str) -> Optional[int]:
        """Get the current battery level of a lock."""
        _LOGGER.debug("Attempting to get battery level for %s", serial_number) # Added debug log
        try:
            result = await self._execute_and_poll(serial_number, OP_GET_BATTERY)
            battery = result.get("battery_level") if isinstance(result, dict) else None
            _LOGGER.debug("Received battery level '%s' for lock %s", battery, serial_number) # Added debug log
            if isinstance(battery, int) and 0 <= battery <= 100:
                return battery
            else:
                 # Allow 0 as a valid level
                 if battery == 0:
                     return 0
                 _LOGGER.warning("Received invalid battery level '%s' (type: %s) for lock %s", battery, type(battery).__name__, serial_number)
                 return None
        except DanalockJobError as e:
            _LOGGER.error("Failed to get battery level for lock %s: %s", serial_number, e)
            return None
        except Exception as e: # Catch any other unexpected error
            _LOGGER.exception("Unexpected error getting battery level for %s", serial_number)
            return None

    async def lock(self, serial_number: str) -> bool:
        """Send lock command."""
        # Enhanced logging
        _LOGGER.info("Starting lock operation for %s", serial_number)
        try:
            # Explicitly log the exact payload being sent
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
        # Enhanced logging
        _LOGGER.info("Starting unlock operation for %s", serial_number)
        try:
            # Explicitly log the exact payload being sent
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
        """Fetch both state and battery level for a lock, handling partial failures."""
        _LOGGER.debug("Fetching concurrent data for lock %s", serial_number)

        async def _safe_get_state(serial):
            try:
                return await self.get_lock_state(serial)
            except Exception as e: # Catch broadly here, specific errors logged deeper
                _LOGGER.warning("Failed to get state during concurrent fetch for %s: %s", serial, e)
                return None

        async def _safe_get_battery(serial):
            try:
                return await self.get_battery_level(serial)
            except Exception as e:
                _LOGGER.warning("Failed to get battery during concurrent fetch for %s: %s", serial, e)
                return None

        # Run concurrently
        state_task = asyncio.create_task(_safe_get_state(serial_number))
        battery_task = asyncio.create_task(_safe_get_battery(serial_number))

        # Wait for both tasks to complete
        state, battery = await asyncio.gather(state_task, battery_task)

        return {
            LOCK_STATE: state,
            LOCK_BATTERY: battery,
        }

