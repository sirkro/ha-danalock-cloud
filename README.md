# Danalock Cloud Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

This is a custom integration for Home Assistant to control [Danalock V3](https://danalock.com/) smart locks via the Danalock Cloud API and Bridge. It provides native `lock` and `sensor` entities, replacing the need for complex Node-RED flows or REST commands for basic cloud control.

**Note:** This integration relies on the Danalock Cloud API, which involves internet connectivity and communication delays inherent to cloud services.

## Acknowledgements

This integration was inspired by and utilizes understanding of the Danalock API derived from the work done by **[@erikwihlborg76](https://github.com/erikwihlborg76)** on the [unofficial Danalock Node-RED flow](https://github.com/erikwihlborg76/unofficial-danalock-web-api). Many thanks for figuring out the API interactions!

## Features

*   **Lock Control:** Lock and unlock your Danalock devices via the cloud.
*   **State Reporting:** Reports the current state (Locked/Unlocked) polled from the cloud.
*   **Battery Level:** Provides a sensor for the lock's battery percentage.
*   **Cloud Polling:** Periodically fetches status updates from the Danalock Cloud.
*   **UI Configuration:** Setup and configuration via the Home Assistant user interface.
*   **Diagnostics:** Provides diagnostic information for troubleshooting.
*   **Refresh Service:** Allows manual triggering of data updates.

## Important Requirements & Limitations

*   **No 2FA Support:** This integration **cannot** authenticate with Danalock accounts that have Two-Factor Authentication (2FA) enabled. The underlying API method used does not support interactive 2FA prompts. You **must disable 2FA** on the Danalock account used with this integration for it to work. Please consider the security implications before disabling 2FA.
*   **Owner Account Recommended:** It is strongly recommended (and likely required) to use the Danalock account that **owns/manages** the lock and bridge. Accounts that only have shared access might not have the necessary API permissions to control the lock via this integration.
*   **Danabridge V3 Required:** Cloud access requires a Danabridge V3 connected to your lock and your network.

## Installation

### Prerequisites

*   Home Assistant installation.
*   [HACS](https://hacs.xyz/) (Home Assistant Community Store) installed and configured.
*   Your Danalock account username and password (see Requirements above).
*   A Danalock V3 lock paired with a Danabridge V3.

### Installation via HACS

1.  Open HACS in your Home Assistant instance.
2.  Go to **Integrations**.
3.  Click the three dots in the top right corner and select **Custom repositories**.
4.  Enter the URL of this repository: `https://github.com/furth3st/ha-danalock-cloud`
5.  Select `Integration` as the category.
6.  Click **Add**.
7.  Close the custom repositories dialog.
8.  You should now see the "Danalock Cloud" integration listed. Click **Install**.
9.  Follow the HACS installation prompts and restart Home Assistant when required.

## Configuration

1.  After restarting Home Assistant, go to **Settings** -> **Devices & Services**.
2.  Click the **+ Add Integration** button in the bottom right corner.
3.  Search for "Danalock Cloud" and select it.
4.  Enter the **Username** and **Password** for your Danalock **owner** account (with **2FA disabled**).
5.  Click **Submit**.

The integration will attempt to authenticate, discover your locks linked to your bridge, and create corresponding `lock` and `sensor` (battery) entities.

## Options

You can configure the polling interval after setup:

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the Danalock Cloud integration card.
3.  Click **Configure**.
4.  Adjust the **Polling Interval (minutes)**. The default is 5 minutes. Lower values increase API requests.
5.  Click **Submit**. The integration will reload with the new interval.

## Diagnostics

If you encounter issues, you can download diagnostic information to help troubleshoot:

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the Danalock Cloud integration card.
3.  Click the three dots (...) menu on the card.
4.  Select **Download diagnostics**.

This will download a text file containing redacted configuration, discovered devices, and recent status information from the integration. Attach this file when reporting issues.

## Services

This integration provides the following service:

*   **`danalock_cloud.refresh_devices`**: Forces an immediate refresh of all Danalock device states and battery levels from the cloud API for all configured accounts. This can be useful in automations or for debugging if you suspect the state is stale.

    *Example Service Call in Automation:*
    ```yaml
    action:
      - service: danalock_cloud.refresh_devices
