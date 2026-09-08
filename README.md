# Pwnagotchi Companion (PwnIOS)

**PwnIOS** is an iOS companion app for [Pwnagotchi](https://pwnagotchi.ai).

Connect your iPhone or iPad to your Pwnagotchi over WebSocket and get live stats, screen mirroring, GPS sharing, network information, events, and remote control from the app.

---

## Features

- **Live dashboard** — uptime, battery, temperature, mode, and connection status
- **Screen mirroring** — mirror the Pwnagotchi display directly on your iOS device
- **Network monitoring** — discovered access points and handshake status
- **GPS sharing** — send iOS location data to Pwnagotchi for wardriving
- **GPS logging** — save location data for later use and WiGLE-compatible exports
- **Events** — live activity and connection log
- **Remote control** — switch modes and reboot Pwnagotchi remotely
- **PiSugar support** — battery monitoring through PiSugar
- **WebSocket connection** — automatic reconnect, message queuing, and retry handling

---

## Requirements

- iOS **16.0+**
- [jayofelony's Pwnagotchi fork](https://github.com/jayofelony/pwnagotchi)
- iPhone or iPad with Bluetooth tethering enabled

---

## Installation

### 1. Install the PwnIOS plugin

#### Manual installation

SSH into your Pwnagotchi and create the plugin file:

```bash
cd /etc/pwnagotchi/custom-plugins/
sudo nano pwnios.py
```

Copy the contents of [`pwnios.py`](https://github.com/BraedenP232/PwnIOS/blob/main/pwnios.py) into the file and save.

#### Plugin repository

Alternatively, add the PwnIOS plugin repository to your Pwnagotchi configuration:

```toml
main.custom_plugin_repos = [
    "https://github.com/BraedenP232/pwnios/archive/main.zip",
]
```

Then install it:

```bash
sudo pwnagotchi plugins update
sudo pwnagotchi plugins install pwnios
```

---

### 2. Configure PwnIOS

Edit:

```bash
sudo nano /etc/pwnagotchi/config.toml
```

Add or modify the PwnIOS configuration:

```toml
[main.plugins.pwnios]
enabled = true

# Display
port = 8082
display = false
display_gps = false

# PiSugar
pisugar = false

# GPS
save_gps_log = true
gps_log_path = "/tmp/pwnagotchi_gps.log"
gps_altitude = 10
```

### Configuration options

| Option | Default | Description |
|---|---:|---|
| `enabled` | `true` | Enable the PwnIOS plugin |
| `port` | `8082` | WebSocket server port |
| `display` | `false` | Display iOS connection status on Pwnagotchi |
| `display_gps` | `false` | Display GPS coordinates on Pwnagotchi |
| `pisugar` | `false` | Enable PiSugar battery monitoring |
| `save_gps_log` | `true` | Save GPS data to a log file |
| `gps_log_path` | `/tmp/pwnagotchi_gps.log` | GPS log file location |
| `gps_altitude` | `10` | Fallback altitude in metres for GPS exports |

> `gps_altitude` is used because iOS currently does not provide altitude data to PwnIOS. The value is written to the `.gps.json` data used for WiGLE-compatible exports.

---

### 3. Restart Pwnagotchi

```bash
pwnkill && pwnlog
```

---

### 4. Install the iOS app

**[Download Pwnagotchi Companion from the App Store](https://apps.apple.com/us/app/pwnagotchi-companion/id6751243451)**

---

## Usage

Connect your iPhone or iPad to the Pwnagotchi using [Bluetooth tethering](https://github.com/jayofelony/pwnagotchi/wiki/Step-2-Connecting).

Once the connection is established, the app will show **Live**.

### Dashboard

Live Pwnagotchi statistics including:

- Uptime
- Battery
- Temperature
- Current mode
- Connection status
- Pwnagotchi face

### Screen

Mirrors the Pwnagotchi display directly in the app.

### Network

View discovered access points and handshake activity in real time.

### Location

Share your iOS device's GPS location with Pwnagotchi.

GPS data can also be logged for later use and exported in a format compatible with WiGLE uploads.

### Events

View connection events and Pwnagotchi activity as they happen.

### Settings

Configure the connection, logging, and debugging options.

---

## Troubleshooting

### PwnIOS won't connect

Check the following:

1. Bluetooth tethering is enabled on your iOS device.
2. The PwnIOS plugin is enabled in `config.toml`.
3. Pwnagotchi has been restarted after installing or changing the plugin.
4. Your iOS device is connected to the Pwnagotchi's Bluetooth network.

If Bluetooth tethering itself is unreliable, see this [Pwnagotchi tethering writeup](https://www.reddit.com/r/pwnagotchi/comments/1m4riyn/bluetooth_tethering_issues_try_this_fix/).

### Connection keeps dropping

Keep the iOS device close to the Pwnagotchi and check the Pwnagotchi's power stability.

Enable debug logging in the app if you need to determine whether the problem is related to Bluetooth tethering, the WebSocket connection, or the Pwnagotchi itself.

### Face or screen isn't updating

Check that:

- The Pwnagotchi display is functioning normally.
- The PwnIOS plugin is running.
- WebSocket traffic is being received.
- Debug logging doesn't show connection or parsing errors.

Restarting both the Pwnagotchi and the app can also clear a stale connection.

---

## What's New — v1.0.4.0

### Configuration

- Updated the configuration example to use the current TOML table syntax:
  ```toml
  [main.plugins.pwnios]
  ```
- Added the `gps_altitude` configuration option.

### GPS

- `_handle_gps_data` now captures altitude.
- Uses `gps_altitude` as a fallback because iOS does not currently provide altitude data.
- `gps_export` now includes the required `Altitude` field.
- Renamed `Timestamp` to `Updated` in GPS exports.

The GPS export now uses the field names expected by WiGLE:

```text
Latitude
Longitude
Altitude
Accuracy
Updated
```

This fixes WiGLE CSV uploads rather than simply changing the field names for consistency.

### UI

- Added `ui._lock` protection to:
  - `on_ui_setup`
  - `on_ui_update`
  - `on_unload`
- Updated UI handling to match the current Pwnagotchi default-plugin convention.
- `on_unload` now properly deregisters:
  - `ios_clients`
  - `gps_long`
  - `gps_lat`

---

## Links

- [Pwnagotchi](https://pwnagotchi.ai)
- [jayofelony's Pwnagotchi fork](https://github.com/jayofelony/pwnagotchi)
- [PwnIOS on GitHub](https://github.com/BraedenP232/PwnIOS)
- [Discord](https://discord.gg/VRwTWUGaXb)
- [Issues](https://github.com/BraedenP232/PwnagotchiCompanion/issues)
- [Discussions](https://github.com/BraedenP232/PwnagotchiCompanion/discussions)

---

## License

[MIT License](LICENSE)

---

**PwnIOS is not officially affiliated with the Pwnagotchi project.**
