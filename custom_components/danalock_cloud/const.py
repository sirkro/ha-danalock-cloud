"""Constants for the Danalock Cloud integration."""
from typing import Final
from datetime import timedelta

DOMAIN: Final = "danalock_cloud"
PLATFORMS: Final = ["lock", "sensor"] # Supported entity platforms

# Configuration Constants
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password" # Only used during initial setup/reauth

# API Endpoints
API_BASE_URL: Final = "https://api.danalock.com"
BRIDGE_API_BASE_URL: Final = "https://bridge.danalockservices.com/bridge/v1"
TOKEN_URL: Final = f"{API_BASE_URL}/oauth2/token"
LOCKS_URL: Final = f"{API_BASE_URL}/locks/v1"
EXECUTE_URL: Final = f"{BRIDGE_API_BASE_URL}/execute"
POLL_URL: Final = f"{BRIDGE_API_BASE_URL}/poll"

# API Constants
CLIENT_ID: Final = "danalock-web"
DEFAULT_TIMEOUT: Final = 20  # seconds for API requests
JOB_POLL_INTERVAL: Final = 2  # seconds between job status polls
JOB_POLL_TIMEOUT: Final = 30 # seconds total timeout for a bridge job
UPDATE_INTERVAL: Final = timedelta(minutes=5) # Default polling interval
COMMAND_UPDATE_DELAY: Final = timedelta(seconds=15) # Delay after command before forcing coordinator refresh

# Data Keys (Stored in ConfigEntry and Coordinator)
ACCESS_TOKEN: Final = "access_token"
REFRESH_TOKEN: Final = "refresh_token"
EXPIRES_IN: Final = "expires_in" # Received from API, used to calculate expiry
TOKEN_EXPIRES_AT: Final = "token_expires_at" # Calculated timestamp stored in ConfigEntry
LOCK_SERIAL: Final = "serial_number"
LOCK_NAME: Final = "name"
LOCK_STATE: Final = "state"
LOCK_BATTERY: Final = "battery_level"

# Lock States from API
API_STATE_LOCKED: Final = "Locked"
API_STATE_UNLOCKED: Final = "Unlocked"

# Bridge Operations
OP_GET_STATE: Final = "afi.lock.get-state"
OP_GET_BATTERY: Final = "afi.power-source.get-information2"
OP_LOCK: Final = "afi.lock.operate"
OP_UNLOCK: Final = "afi.lock.operate"

# Arguments for Bridge Operations
ARG_LOCK: Final = "lock"
ARG_UNLOCK: Final = "unlock"

# Bridge Job Status
JOB_STATUS_SUCCEEDED: Final = "Succeeded"
JOB_STATUS_FAILED: Final = "Failed"
JOB_STATUS_IN_PROGRESS: Final = "InProgress"

# Service Names
SERVICE_REFRESH_DEVICES: Final = "refresh_devices"

# Event Types
EVENT_LOCK_COMMAND_SUCCESS: Final = f"{DOMAIN}_command_success"
EVENT_LOCK_COMMAND_FAILURE: Final = f"{DOMAIN}_command_failure"

