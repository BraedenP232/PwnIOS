# Pwnagotchi Companion (PwnIOS)

**PwnIOS** is an iOS companion app for [Pwnagotchi](https://pwnagotchi.ai).

Connect your iPhone or iPad to your Pwnagotchi over WebSocket and get live stats, screen mirroring, GPS sharing, network information, events, and remote control from the app.

---

## Features

- **Live dashboard** — uptime, battery, temperature, mode, and connection status
- **Screen mirroring** — mirror the Pwnagotchi display directly on your iOS device
- **Network monitoring** — discovered access points and current-session handshakes
- **GPS sharing** — send occasional or live iOS location updates to Pwnagotchi
- **Handshake location** — write the latest coordinates beside captured handshakes
- **Events** — a focused activity log with optional verbose detail
- **Remote control** — switch modes and reboot Pwnagotchi remotely
- **PiSugar support** — battery monitoring through PiSugar
- **Optional authentication** — protect the WebSocket endpoint with a shared token
- **WebSocket connection** — resilient reconnect, heartbeat, and clean shutdown handling

---

## Requirements

- iOS **16.0+**
- [jayofelony's Pwnagotchi fork](https://github.com/jayofelony/pwnagotchi)
- iPhone or iPad with Bluetooth tethering enabled
- Python **3.13** with the [`websockets`](https://websockets.readthedocs.io/) package

PwnIOS 2.0.0 is tested with Python 3.13.5 and `websockets` 17.0.1. Verify the package in Pwnagotchi's own Python environment:

```bash
/opt/.pwn/bin/python3 -c "import websockets; print(websockets.__version__)"
```

---

## Installation

### 1. Install the PwnIOS plugin

#### Manual installation

SSH into your Pwnagotchi and copy `pwnios.py` into the custom plugin directory configured by your image. For example:

```bash
cp pwnios.py ~/custom-plugins/pwnios.py
```

The location may differ between images. Use the same directory as your other working custom plugins.

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
host = "0.0.0.0"
port = 8082
display = false
display_gps = false

# PiSugar
pisugar = false

# Authentication (recommended on untrusted networks)
authentication_required = false
# auth_token = "replace-with-a-generated-token"

# GPS
save_gps_log = true
gps_log_path = "/tmp/pwnagotchi_gps.log"
gps_altitude = 10
```

### Configuration options

| Option | Default | Description |
|---|---:|---|
| `enabled` | `true` | Enable the PwnIOS plugin |
| `host` | `0.0.0.0` | Interface on which the WebSocket server listens |
| `port` | `8082` | WebSocket server port |
| `display` | `false` | Display iOS connection status on Pwnagotchi |
| `display_gps` | `false` | Display GPS coordinates on Pwnagotchi |
| `pisugar` | `false` | Enable PiSugar battery monitoring |
| `authentication_required` | `false` | Require clients to authenticate before receiving data or issuing commands |
| `auth_token` | unset | Shared authentication token; required when authentication is enabled |
| `save_gps_log` | `true` | Save GPS data to a log file |
| `gps_log_path` | `/tmp/pwnagotchi_gps.log` | GPS log file location |
| `gps_altitude` | `10` | Default altitude included with GPS data when the client does not provide one |

Generate a strong authentication token with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Enter the same token in the companion app's connection settings.

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

GPS data can also be logged for later use and written to a `.gps.json` sidecar when a handshake is captured.

### Events

View connection events and Pwnagotchi activity as they happen.

### Settings

Configure the connection, appearance, location sharing, and notifications.

---

## Troubleshooting

### PwnIOS won't connect

Check the following:

1. Bluetooth tethering is enabled on your iOS device.
2. The PwnIOS plugin is enabled in `config.toml`.
3. Pwnagotchi has been restarted after installing or changing the plugin.
4. Your iOS device is connected to the Pwnagotchi's Bluetooth network.
5. Port `8082` is listening: `sudo ss -lntp | grep ':8082'`.
6. The plugin reports a startup line in `pwnlog | grep -i pwnios`.

If Bluetooth tethering itself is unreliable, see this [Pwnagotchi tethering writeup](https://www.reddit.com/r/pwnagotchi/comments/1m4riyn/bluetooth_tethering_issues_try_this_fix/).

### Connection keeps dropping

Keep the iOS device close to the Pwnagotchi and check the Pwnagotchi's power stability.

Check `pwnlog | grep -i pwnios` to determine whether the problem is the Bluetooth route, WebSocket listener, or plugin startup.

### Face or screen isn't updating

Check that:

- The Pwnagotchi display is functioning normally.
- The PwnIOS plugin is running.
- WebSocket traffic is being received.
- Debug logging doesn't show connection or parsing errors.

Restarting both the Pwnagotchi and the app can also clear a stale connection.

---

## What's New — v2.0.0

### WebSocket compatibility and resilience

- Updated the server for Python 3.13 and the modern `websockets.asyncio.server` API.
- Added deterministic server startup and shutdown across the plugin's background event-loop thread.
- Improved heartbeat, client cleanup, broadcasting, and connection health behavior.
- Added a server hello message so the app can identify plugin and protocol versions.
- Added optional shared-token authentication negotiated through the server hello message.

### Companion data

- Added current-session handshake retrieval for the app's handshake view.
- Improved AUTO/MANU mode reporting by reading the runtime mode used by Pwnagotchi.
- Preserved GPS sharing, per-handshake GPS exports, face updates, PiSugar data, and remote controls.
- Reduced noisy routine logging while retaining useful lifecycle and error messages.

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
