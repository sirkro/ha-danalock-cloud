# Danalock Cloud Integration for Home Assistant

[![HACS Custom][hacs-shield]][hacs-url]
[![GitHub Release][releases-shield]][releases-url]
[![License][license-shield]][license-url]

<!-- Assumes you'll add 'danalock_logo.png' to an 'images' folder in your repo root -->
<p align="center">
  <img src="images/danalock_logo.png" alt="Danalock Logo" width="150"/>
</p>

This is a custom integration for Home Assistant to control [Danalock V3](https://danalock.com/) smart locks via the Danalock Cloud API and the Danabridge V3. It provides native `lock` and `sensor` (battery) entities, offering a more integrated experience than relying on complex Node-RED flows or REST commands for basic cloud control.

**Important Note:** This integration communicates with your Danalock devices through the Danalock Cloud. This means it requires an active internet connection for both Home Assistant and your Danabridge. Cloud communication inherently involves some latency.

## Acknowledgements

This integration was inspired by and utilizes understanding of the Danalock API derived from the work done by **[@erikwihlborg76](https://github.com/erikwihlborg76)** on the [unofficial Danalock Node-RED flow](https://github.com/erikwihlborg76/unofficial-danalock-web-api). Many thanks for the foundational work in understanding the API interactions!

## Features

*   **Lock Control:** Lock and unlock your Danalock devices.
*   **State Reporting:** Reports the current lock state (Locked/Unlocked) polled from the cloud.
*   **Battery Level:** Provides a sensor entity for the lock's battery percentage.
*   **Cloud Polling:** Periodically fetches status updates from the Danalock Cloud. The interval is configurable.
*   **Optional Optimistic State:** Choose to have the UI update instantly after sending a command (see Options section).
*   **UI Configuration:** Easy setup and configuration directly through the Home Assistant user interface.
*   **Automatic Re-authentication:** Attempts to automatically re-authenticate if tokens expire, minimizing user intervention.
*   **Diagnostics:** Provides diagnostic information via the Home Assistant UI to aid in troubleshooting.
*   **Refresh Service:** Allows manual triggering of data updates for all locks via a Home Assistant service call.

## Important Requirements & Limitations

*   **Danabridge V3 Required:** This integration **requires** a Danabridge V3 connected to your lock(s) and your local network. It does not communicate directly with the lock via Bluetooth.
*   **No 2FA Support:** The Danalock account used with this integration **must have Two-Factor Authentication (2FA) disabled**. The underlying API methods do not support interactive 2FA prompts. Please carefully consider the security implications before disabling 2FA on any account.
*   **Owner Account Highly Recommended:** It is strongly recommended (and likely required) to use the Danalock account that **owns and manages** the lock and bridge. Accounts with only shared access may lack the necessary API permissions for this integration to function correctly.
*   **Cloud Dependency & Latency:** All communication goes through the Danalock cloud, meaning an internet connection is essential. Operations may experience delays typical of cloud services. (See "Notice on State Updates and Delays" below).

## Notice on State Updates and Delays

Due to the nature of cloud-based control and the Danalock API:

*   **Command Execution Delay:** When you send a lock or unlock command from Home Assistant, the command goes to the Danalock Cloud, then to your Danabridge, and finally to the lock via Bluetooth. This process takes several seconds.
*   **State Confirmation:** After sending a command, the integration waits for a short period (currently 15 seconds) and then attempts to refresh the lock's actual state from the cloud.
*   **Polling Interval:** The primary way the lock's state is updated is through periodic polling, which defaults to every 5 minutes (configurable in options).
*   **"Bridge Busy" is Expected Behavior:** The Danalock API can only handle **one operation at a time** per bridge. If you send a command and then immediately try to poll for the state, the bridge will report "Busy".
    *   The lock state in Home Assistant will **retain its last known valid state** and will *not* become "unknown" due to a transient `BridgeBusy` error.
    *   The actual state will be updated once a subsequent poll is successful.
*   **Optimistic Mode:** To provide faster UI feedback, you can enable "Optimistic State Updates" in the integration options. See the "Options" section for more details.

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

After setup, you can configure the integration's behavior:

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the "Danalock Cloud" integration card.
3.  Click **CONFIGURE**.
4.  Adjust the available options:
    *   **Polling Interval (minutes):** The default is 5 minutes. Higher values are gentler on the API and recommended if you see frequent `BridgeBusy` errors.
    *   **Use Optimistic State Updates:**
        *   **Disabled (Default):** The lock's state only changes after the API confirms it. This is more accurate but has a delay.
        *   **Enabled:** The lock's state changes instantly in the UI when you send a command. The integration will verify and correct the state later if the command failed.
5.  Click **Submit**.

## Services

This integration provides the following service:

*   **`danalock_cloud.refresh_devices`**:
    *   **Description:** Forces an immediate refresh of all Danalock device states and battery levels from the cloud API for all configured Danalock Cloud accounts.
    *   **Use Cases:** Useful in automations after a lock/unlock command if you want to try and get an updated state sooner than the next scheduled poll, or for debugging if you suspect the state is stale.
    *   **Example Service Call in Automation:**

        action:
          - service: danalock_cloud.refresh_devices

## Troubleshooting

*   **Authentication Failed / Invalid Auth:**
    *   Ensure 2FA is disabled on the Danalock account.
    *   Verify you are using the Danalock account that *owns* the lock and bridge.
    *   Double-check your username and password.
    *   If tokens have become invalid, the integration will attempt to re-authenticate silently. If your password has also changed, Home Assistant should prompt for re-authentication.

*   **Lock State Not Updating / `BridgeBusy` Errors in Logs:**
    *   Refer to the "Notice on State Updates and Delays" section above. This is often expected behavior if the API is polled too quickly.
    *   **Try Increasing Polling Interval:** This is the most effective solution. Go to the integration options and increase the polling interval (e.g., to 15, 30, or 60 minutes).
    *   **Restart Danabridge:** Power cycle your physical Danabridge V3 device.

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

## Disclaimers

This is an unofficial, community-developed integration. Danalock® and the Danalock logo are trademarks of Danalock International ApS. This project is not affiliated with, endorsed by, or sponsored by Danalock International ApS. The logo is used here for identification purposes only, to indicate the product this integration is designed to work with.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

<!-- Badges -->
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://hacs.xyz/
[releases-shield]: https://img.shields.io/github/v/release/furth3st/ha-danalock-cloud.svg?style=flat-square
[releases-url]: https://github.com/furth3st/ha-danalock-cloud/releases
[license-shield]: https://img.shields.io/github/license/furth3st/ha-danalock-cloud.svg?style=flat-square
[license-url]: https://github.com/furth3st/ha-danalock-cloud/blob/main/LICENSE
