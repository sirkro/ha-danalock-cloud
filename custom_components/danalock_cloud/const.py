"""Constants for the Danalock Cloud integration."""
from typing import Final
from datetime import timedelta

DOMAIN: Final = "danalock_cloud"
PLATFORMS: Final = ["lock", "sensor", "diagnostics"] # Added diagnostics

# Configuration Constants
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"

# API Endpoints
API_BASE_URL: Final = "https://api.danalock.com"
BRIDGE_API_BASE_URL: Final = "https://bridge.danalockservices.com/bridge/v1"
TOKEN_URL: Final = f"{API_BASE_URL}/oauth2/token"
LOCKS_URL: Final = f"{API_BASE_URL}/locks/v1"
EXECUTE_URL: Final = f"{BRIDGE_API_BASE_URL}/execute"
POLL_URL: Final = f"{BRIDGE_API_BASE_URL}/poll"

# API Constants
CLIENT_ID: Final = "danalock-web"
DEFAULT_TIMEOUT: Final = 20  # seconds
JOB_POLL_INTERVAL: Final = 2  # seconds between job status polls
JOB_POLL_TIMEOUT: Final = 30 # seconds total timeout for a job
UPDATE_INTERVAL: Final = timedelta(minutes=5) # How often to poll lock state/battery
COMMAND_UPDATE_DELAY: Final = timedelta(seconds=15) # How long to wait after command before forcing update

# Data Keys
ACCESS_TOKEN: Final = "access_token"
REFRESH_TOKEN: Final = "refresh_token"
EXPIRES_IN: Final = "expires_in"
TOKEN_EXPIRES_AT: Final = "token_expires_at" # Key for storing expiry timestamp
LOCK_SERIAL: Final = "serial_number"
LOCK_NAME: Final = "name"
LOCK_STATE: Final = "state"
LOCK_BATTERY: Final = "battery_level"

# Lock States from API/NodeRed logic
API_STATE_LOCKED: Final = "Locked"
API_STATE_UNLOCKED: Final = "Unlocked"

# Operations
OP_GET_STATE: Final = "afi.lock.get-state"
OP_GET_BATTERY: Final = "afi.power-source.get-information2"
OP_LOCK: Final = "afi.lock.operate"
OP_UNLOCK: Final = "afi.lock.operate"
# OP_OPEN: Final = "afi.lock.operate" # Example if 'open' uses same operation but different arg
# ARG_OPEN: Final = "open" # Example argument for open/unlatch

# Arguments for Operations
ARG_LOCK: Final = "lock"
ARG_UNLOCK: Final = "unlock"

# Job Status
JOB_STATUS_SUCCEEDED: Final = "Succeeded"
JOB_STATUS_FAILED: Final = "Failed"
JOB_STATUS_IN_PROGRESS: Final = "InProgress"

# Service Names
SERVICE_REFRESH_DEVICES: Final = "refresh_devices"

# Event Types (NEW)
EVENT_LOCK_COMMAND_SUCCESS: Final = f"{DOMAIN}_command_success"
EVENT_LOCK_COMMAND_FAILURE: Final = f"{DOMAIN}_command_failure"

