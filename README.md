# Pwnagotchi Companion: Advanced Pwnagotchi Companion for iOS

## Overview

**Pwnagotchi Companion** is a sophisticated iOS companion app that provides real-time monitoring and control of your Pwnagotchi device. Using advanced WebSocket technology with intelligent reconnection, message queuing, and health monitoring, Pwnagotchi Companion delivers a seamless experience for managing your Pwnagotchi from your iPhone or iPad.

---

## ✨ Key Features

### 📊 **Real-Time Monitoring**
- **Live Statistics**: Monitor uptime, battery level, temperature, and current operating mode
- **Connection Health**: Advanced network quality detection with automatic degradation handling
- **Performance Metrics**: Track message throughput, ping latency, and connection stability
- **Activity Timeline**: Comprehensive event logging with categorized status updates

### 🎭 **Visual Interface**
- **Live Face Display**: Real-time Pwnagotchi face updates with support for custom faces
- **Screen Mirroring**: Direct display view of your Pwnagotchi's actual screen
- **Dual View Modes**: Switch between face view and full screen display
- **Automatic Refresh**: Configurable refresh intervals for optimal performance

### 🌐 **Advanced Connectivity**
- **Intelligent WebSocket Management**: Auto-reconnection with exponential backoff
- **Message Queue System**: Reliable message delivery with retry logic and priority handling
- **Background Resilience**: Maintains connection state across app lifecycle changes

### 📍 **Location Services**
- **GPS Tracking**: Real-time location sharing
- **Accuracy Metrics**: Display GPS precision and last update timestamps

### 🔧 **Remote Control**
- **Mode Switching**: Change between AUTO, MANUAL
- **System Commands**: Remote reboot and state management

### 📡 **Network Analysis**
- **Access Point Discovery**: Real-time WiFi network detection and analysis
- **Handshake Monitoring**: Live capture status and peer detection
- **Channel Information**: Current operating channel and hop detection
- **Network Statistics**: Comprehensive WiFi environment analysis

---

## 🏗️ Architecture Highlights

### Robust Connection Management
```swift
// Advanced connection states with automatic recovery
enum ConnectionState {
    case disconnected, connecting, connected, reconnecting, failed(Error)
}
```

### Intelligent Message Handling
- **Priority Queue System**: High, normal, and low priority message routing
- **Automatic Retry Logic**: Failed messages are intelligently retried
- **Message Acknowledgment**: Reliable delivery confirmation system
- **Queue Persistence**: Messages survive connection interruptions

### Performance Optimization
- **Background Processing**: JSON parsing and image decoding off main thread
- **Memory Management**: Efficient image handling and data cleanup
- **Timer Coordination**: Sophisticated timer management for different update intervals
- **Resource Conservation**: Automatic pause/resume based on app state

---

## 📱 iOS App Features

### Connection Management
- **Manual Configuration**: Custom IP and port configuration with validation
- **Connection History**: Remember and quickly reconnect to known devices

### User Interface
- **Real-Time Dashboard**: Live stats with beautiful visualizations
- **Event Timeline**: Scrollable history of all Pwnagotchi activities
- **Settings Panel**: Comprehensive configuration options
- **Debug Console**: Advanced logging for troubleshooting

---

## 🚀 Installation

### 1. Pwnagotchi Plugin Setup

Add the custom plugin repository to your `/etc/pwnagotchi/config.toml`:

```toml
main.custom_plugin_repos = [
    "https://github.com/BraedenP232/pwnios/archive/main.zip",
]
```

### 2. Install the Plugin

```bash
# Update plugin repositories
sudo pwnagotchi plugins update

# Install Pwnagotchi Companion plugin
sudo pwnagotchi plugins install pwnios
```

### 3. Configure the Plugin

Edit `/etc/pwnagotchi/config.toml`:

```toml
main.plugins.pwnios.enabled = true
main.plugins.pwnios.display = true              # Show connection count on display
main.plugins.pwnios.display_gps = true          # Show GPS status on display
main.plugins.pwnios.port = 8082                 # WebSocket server port


# Coming soon
# main.plugins.pwnios.save_gps_log = true         # Optional: Enable GPS logging
# main.plugins.pwnios.gps_log_path = "/tmp/pwnagotchi_gps.log"  # GPS log location
```

### 4. Restart Pwnagotchi

```bash
sudo systemctl restart pwnagotchi
```

---

## 📲 iOS App Installation

### Option 1: App Store (Coming Soon)
> 📱 The Pwnagotchi Companion app will be available on the App Store soon!

## 💡 Usage Guide

### Initial Setup
1. **Network Connection**: Connect your iOS device to the Pwnagotchi via [Bluetooth Tethering](https://github.com/jayofelony/pwnagotchi/wiki/Step-2-Connecting)
2. **Verify Connection**: Verify the Bluetooth connection and possibly restart Pwnagotchi
3. **Connection**: Pwnagotchi Companion will present *Live* when the connection is established

### Navigation
- **Dashboard**: Main view with live statistics and face display
- **Screen View**: Swipe to view actual Pwnagotchi display
- **Network**: View discovered APs and some information about them
- **Location**: GPS sharing from iOS device to Pwnagotchi, saved for optional wardriving
- **Events**: Detailed activity log with filtering options
- **Settings**: App configuration and connection management

### Advanced Features
- **Debug Mode**: Enable detailed logging for troubleshooting

---

## 🔍 Troubleshooting

### Connection Issues

#### "Cannot connect to Pwnagotchi"
- ✅ Verify [Bluetooth tethering](https://github.com/jayofelony/pwnagotchi/wiki/Step-2-Connecting) is connected properly
- 🔌 Check if Pwnagotchi is powered on and responsive
- 🌐 Confirm plugin is enabled and Pwnagotchi has restarted
- 🔧 Troubleshoot using [wpa_2's great writeup](https://www.reddit.com/r/pwnagotchi/comments/1m4riyn/bluetooth_tethering_issues_try_this_fix/)

#### "Connection keeps dropping"
- 📶 Ensure Pwnagotchi is close to iOS device
- ⚡ Verify Pwnagotchi power supply is stable
- 📊 Enable debug logging to identify patterns

#### "Face/Screen images not updating"
- 🖼️ Verify Pwnagotchi display is active and changing
- 📡 Check WebSocket message flow in debug logs
- 🔄 Toggle between face and screen view modes
- ⚙️ Restart both app and Pwnagotchi if needed

### Advanced Diagnostics

The app includes comprehensive diagnostic tools:
- **Connection Metrics**: Real-time latency and throughput monitoring
- **Message Inspector**: View raw WebSocket traffic
- **Health Monitor**: Connection quality assessment
- **Network Analyzer**: WiFi environment analysis

---

## 🛠️ Technical Specifications

### System Requirements
- **iOS**: 16.0 or later
- **Devices**: iPhone, iPad, iPod touch
- **Network**: WiFi or Cellular with local network access
- **Pwnagotchi**: [Jayofelony's fork](https://github.com/jayofelony/pwnagotchi/releases/tag/v2.9.5.3)

### Network Protocols
- **WebSocket**: Primary communication protocol (RFC 6455)
- **HTTP**: Screen capture and control commands
- **TCP**: Reliable connection with automatic retry
- **JSON**: Structured data exchange format

### Performance Characteristics
- **Latency**: Sub-second response times on good networks
- **Throughput**: Handles high-frequency updates without blocking
- **Memory**: Optimized for minimal memory footprint
- **Battery**: Efficient background processing to preserve battery life

---

## 🤝 Community & Support

### Related Projects
- 🧠 **jayofelony's Pwnagotchi Fork**: [github.com/jayofelony/pwnagotchi](https://github.com/jayofelony/pwnagotchi)
- 🤖 **PwnDroid (Android)**: [PwnDroid Repository](https://github.com/jayofelony/pwnagotchi-torch-plugins)
- 🔧 **Pwnagotchi Plugins**: [Official Plugin Collection](https://github.com/jayofelony/pwnagotchi/tree/noai/pwnagotchi/plugins/default)

### Community Resources
- 💬 **Discord Server**: [Unofficial Pwnagotchi Community](https://discord.gg/VRwTWUGaXb)
- 📖 **Documentation**: [Official Pwnagotchi Docs](https://pwnagotchi.ai)
- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/BraedenP232/PwnagotchiCompanion/issues)
- 💡 **Feature Requests**: [GitHub Discussions](https://github.com/BraedenP232/PwnagotchiCompanion/discussions)

### Getting Help
1. **Check Documentation**: Most common issues are covered here
2. **Search Issues**: Someone may have already solved your problem
3. **Enable Debug Logging**: Helps identify specific issues
4. **Community Support**: Ask questions in Discord or GitHub Discussions
5. **Bug Reports**: Use provided templates for best results

---

## 🚀 Roadmap

### Upcoming Features
- **watchOS Companion**: Basic stats and notifications on Apple Watch
- **Widget Support**: iOS home screen widgets for quick status
- **Multi-Device**: Manage multiple Pwnagotchi devices
- **Push Notifications**: Alerts for important events
- **Advanced Analytics**: Historical data analysis and trends

### Long-term Goals
- **macOS Version**: Full-featured macOS companion app
- **Automation**: Integration with iOS Shortcuts and HomeKit
- **Cloud Services**: Optional cloud backup and sync
- **Advanced Mapping**: GPS tracking with map visualization

---

## 🤝 Contributing

We welcome contributions from the community! Here's how you can help:

### Development
- 🐛 **Bug Fixes**: Help identify and fix issues
- ✨ **New Features**: Implement requested functionality
- 📚 **Documentation**: Improve guides and API documentation
- 🧪 **Testing**: Beta testing on different devices and networks

### Getting Started
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes with proper documentation
4. Test thoroughly on real devices
5. Submit a pull request with detailed description

### Code Style
- Follow Swift best practices and iOS Human Interface Guidelines
- Use SwiftUI for new UI components
- Include unit tests for new functionality
- Document public APIs with DocC comments

---

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

### Third-Party Libraries
- SwiftUI framework (Apple)
- UIKit framework (Apple)
- Network framework (Apple)
- Combine framework (Apple)

---

## 🙏 Acknowledgments

- **evilsocket**: Original Pwnagotchi creator
- **jayofelony**: Maintaining the active Pwnagotchi fork
- **Pwnagotchi Community**: Continuous inspiration and feedback

---

## 📈 Statistics

![GitHub stars](https://img.shields.io/github/stars/BraedenP232/PwnIOS)
![GitHub forks](https://img.shields.io/github/forks/BraedenP232/PwnIOS) 
![GitHub issues](https://img.shields.io/github/issues/BraedenP232/PwnIOS)
![GitHub license](https://img.shields.io/github/license/BraedenP232/PwnIOS)
![iOS version](https://img.shields.io/badge/iOS-16.0+-blue)
![Swift version](https://img.shields.io/badge/Swift-5.0+-orange)

---

> **Note**: This project is not officially affiliated with the Pwnagotchi project but is developed with love for the community. No Pwnagotchi feelings were harmed in the making of this app. 🤖❤️
