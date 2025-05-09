[![HACS Custom][hacs-shield]][hacs-url]
[![GitHub Release][releases-shield]][releases-url]
[![License][license-shield]][license-url]

<p align="center">
  <img src="images/danalock_logo.png" alt="Danalock Logo" width="150"/>
</p>

# Danalock Cloud Integration for Home Assistant

This is a custom integration for Home Assistant to control [Danalock V3](https://danalock.com/) smart locks via the Danalock Cloud API and the Danabridge V3. It provides native `lock` and `sensor` (battery) entities, offering a more integrated experience than relying on complex Node-RED flows or REST commands for basic cloud control.

**Important Note:** This integration communicates with your Danalock devices through the Danalock Cloud. This means it requires an active internet connection for both Home Assistant and your Danabridge. Cloud communication inherently involves some latency.

## Acknowledgements

This integration was inspired by and utilizes understanding of the Danalock API derived from the work done by **[@erikwihlborg76](https://github.com/erikwihlborg76)** on the [unofficial Danalock Node-RED flow](https://github.com/erikwihlborg76/unofficial-danalock-web-api). Many thanks for the foundational work in understanding the API interactions!

## Features

*   **Lock Control:** Lock and unlock your Danalock devices.
*   **State Reporting:** Reports the current lock state (Locked/Unlocked) polled from the cloud.
*   **Battery Level:** Provides a sensor entity for the lock's battery percentage.
*   **Cloud Polling:** Periodically fetches status updates from the Danalock Cloud. The interval is configurable.
*   **UI Configuration:** Easy setup and configuration directly through the Home Assistant user interface.
*   **Automatic Re-authentication:** Attempts to automatically re-authenticate if tokens expire, minimizing user intervention.
*   **Diagnostics:** Provides diagnostic information via the Home Assistant UI to aid in troubleshooting.
*   **Refresh Service:** Allows manual triggering of data updates for all locks via a Home Assistant service call.

## Important Requirements & Limitations

*   **Danabridge V3 Required:** This integration **requires** a Danabridge V3 connected to your lock(s) and your local network. It does not communicate directly with the lock via Bluetooth.
*   **No 2FA Support:** The Danalock account used with this integration **must have Two-Factor Authentication (2FA) disabled**. The underlying API methods do not support interactive 2FA prompts. Please carefully consider the security implications before disabling 2FA on any account.
*   **Owner Account Highly Recommended:** It is strongly recommended (and likely required) to use the Danalock account that **owns and manages** the lock and bridge. Accounts with only shared access may lack the necessary API permissions for this integration to function correctly.
*   **Cloud Dependency & Latency:** All communication goes through the Danalock cloud, meaning an internet connection is essential. Operations may experience delays typical of cloud services.

## Installation

### Prerequisites

*   A working Home Assistant installation.
*   [HACS (Home Assistant Community Store)](https://hacs.xyz/) installed and configured.
*   Your Danalock account username (email) and password.
*   A Danalock V3 lock correctly paired with a Danabridge V3 that is connected to your network.
*   2FA disabled on the Danalock account you intend to use.

### Installation via HACS

1.  **Add Custom Repository:**
    *   In HACS, go to "Integrations".
    *   Click the three dots (⋮) in the top right corner and select "Custom repositories".
    *   Enter the URL of this repository: `https://github.com/furth3st/ha-danalock-cloud`
    *   Select `Integration` as the category.
    *   Click "Add".
2.  **Install Integration:**
    *   Close the custom repositories dialog.
    *   The "Danalock Cloud" integration should now appear in your HACS integrations list (you might need to search for it).
    *   Click "Install" and follow the prompts.
3.  **Restart Home Assistant:** After HACS completes the installation, restart Home Assistant as prompted.

## Configuration

1.  After restarting Home Assistant, navigate to **Settings** -> **Devices & Services**.
2.  Click the **+ ADD INTEGRATION** button in the bottom right corner.
3.  Search for "Danalock Cloud" and select it.
4.  You will be prompted to enter your Danalock account **Username** (email) and **Password**.
    *   Remember, this account must be the **owner** of the lock/bridge and have **2FA disabled**.
5.  Click **Submit**.

The integration will attempt to authenticate with the Danalock Cloud, discover your locks associated with the bridge, and create the corresponding `lock` and `sensor` (for battery) entities in Home Assistant.

## Options

After setup, you can configure the polling interval:

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the "Danalock Cloud" integration card.
3.  Click **CONFIGURE**.
4.  Adjust the **Polling Interval (minutes)**.
    *   The default is 5 minutes.
    *   Lower values increase the frequency of API requests and may lead to your IP being temporarily rate-limited by Danalock (manifesting as "BridgeBusy" errors). Higher values are gentler on the API.
5.  Click **Submit**. The integration will use the new interval for subsequent polls.

## Services

This integration provides the following service:

*   **`danalock_cloud.refresh_devices`**:
    *   **Description:** Forces an immediate refresh of all Danalock device states and battery levels from the cloud API for all configured Danalock Cloud accounts.
    *   **Use Cases:** Useful in automations after a lock/unlock command if you want to try and get an updated state sooner than the next scheduled poll, or for debugging if you suspect the state is stale.
    *   **Example Service Call in Automation:**
    ```yaml
    action:
      - service: danalock_cloud.refresh_devices

## Troubleshooting

*   **Authentication Failed / Invalid Auth:**
    *   Ensure 2FA is disabled on the Danalock account.
    *   Verify you are using the Danalock account that *owns* the lock and bridge.
    *   Double-check your username and password.
    *   If tokens have become invalid, Home Assistant should prompt for re-authentication. If it doesn't, try restarting Home Assistant.

*   **Lock State "Unknown" or Not Updating / `BridgeBusy` Errors in Logs:**
    *   The Danalock bridge can sometimes become temporarily unresponsive, especially during or immediately after a lock/unlock operation, or if polled too frequently. This often results in `BridgeBusy` errors in the Home Assistant logs.
    *   **Try Increasing Polling Interval:** Go to the integration options (Settings -> Devices & Services -> Danalock Cloud -> Configure) and increase the polling interval (e.g., to 15, 30, or 60 minutes). This reduces load on the API.
    *   **Restart Danabridge:** Power cycle your physical Danabridge V3 device.
    *   **Check Network:** Ensure your Danabridge has a stable Wi-Fi connection.
    *   The integration is designed to recover from these transient errors, but if they are persistent, the issue may lie with the bridge or its connection.

*   **"No locks found":**
    *   Confirm the Danalock account used is the owner of the locks and the bridge.
    *   Ensure the Danabridge is online and correctly paired with your locks in the Danalock app.

*   **Diagnostics:**
    If you encounter persistent issues, download diagnostic information to help troubleshoot:
    1.  Go to **Settings** -> **Devices & Services**.
    2.  Find the Danalock Cloud integration card.
    3.  Click the three dots (...) menu on the card.
    4.  Select **Download diagnostics**.
    This will download a text file. Please review it for any obvious errors and attach it (after redacting any sensitive information you don't want to share) when reporting an issue.

## Contributing

Contributions are welcome! Please feel free to open an issue or submit a pull request.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---
**Disclaimer:**

This is an unofficial, community-developed integration. Danalock® and the Danalock logo are trademarks of Danalock International ApS. This project is not affiliated with, endorsed by, or sponsored by Danalock International ApS. The logo is used here for identification purposes only, to indicate the product this integration is designed to work with.


<!-- Badges -->
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://hacs.xyz/
[releases-shield]: https://img.shields.io/github/v/release/furth3st/ha-danalock-cloud.svg?style=flat-square
[releases-url]: https://github.com/furth3st/ha-danalock-cloud/releases
[license-shield]: https://img.shields.io/github/license/furth3st/ha-danalock-cloud.svg?style=flat-square
[license-url]: https://github.com/furth3st/ha-danalock-cloud/blob/main/LICENSE
