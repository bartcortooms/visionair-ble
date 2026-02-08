# visionair-ble

Unofficial Python library for controlling VisionAir ventilation devices over Bluetooth Low Energy.

> **Disclaimer:** This project is not affiliated with Ventilairsec, Purevent, VisionAir, or any related companies. All trademarks are the property of their respective owners. This library was developed through reverse engineering for interoperability purposes.

## Supported Devices

All devices advertise as "VisionAir" over BLE (MAC prefix `00:A0:50`):

- **Purevent Vision'R** (350 m³/h) - Tested
- **Urban Vision'R** (201 m³/h) - Untested
- **Cube Vision'R** - Untested

## Installation

```bash
pip install visionair-ble
```

For ESPHome proxy support:

```bash
pip install visionair-ble[proxy]
```

## Quick Start

```python
import asyncio
from visionair_ble import VisionAirClient
from visionair_ble.connect import connect_direct

async def main():
    async with connect_direct("00:A0:50:XX:XX:XX") as client:
        visionair = VisionAirClient(client)

        # Get device status
        status = await visionair.get_status()
        print(f"Airflow: {status.airflow} m³/h ({status.airflow_mode})")
        print(f"Room: {status.temp_remote}°C, {status.humidity_remote}%")
        print(f"Filter: {status.filter_days} days remaining")

        # Control airflow
        await visionair.set_airflow_mode("medium")  # or "low", "high"

        # Other controls
        await visionair.set_boost(True)             # 30-min high airflow
        await visionair.set_holiday(7)              # 7-day holiday mode
        await visionair.set_preheat(True)
        await visionair.set_summer_limit(True)

asyncio.run(main())
```

### Connection Methods

**Direct BLE** (device in range):
```python
from visionair_ble.connect import connect_direct
async with connect_direct("00:A0:50:XX:XX:XX") as client:
    ...
```

**Via ESPHome proxy** (device out of range):
```python
from visionair_ble.connect import connect_via_proxy
async with connect_via_proxy("192.168.1.100", api_key="your_noise_psk") as client:
    ...
```

**Home Assistant** (uses HA's Bluetooth stack):
```python
from bleak import BleakClient
ble_device = async_ble_device_from_address(hass, "00:A0:50:XX:XX:XX")
async with BleakClient(ble_device) as client:
    visionair = VisionAirClient(client)
    ...
```

### Device Scanning

```python
from visionair_ble.connect import scan_direct, scan_via_proxy

# Scan locally
devices = await scan_direct(timeout=10.0)

# Scan via ESPHome proxy
devices = await scan_via_proxy("192.168.1.100", api_key="...", scan_timeout=10.0)

for address, name in devices:
    print(f"Found: {address} ({name})")
```

## API Reference

### VisionAirClient

| Method | Description |
|--------|-------------|
| `get_status()` | Device config, settings, and sensor readings |
| `get_sensors()` | Live probe temperature and humidity readings |
| `get_fresh_status()` | Status with fresh readings from all sensors |
| `set_airflow_mode(mode)` | Set airflow to "low", "medium", or "high" |
| `set_airflow_low/medium/high()` | Convenience methods for airflow control |
| `set_boost(enable)` | Enable/disable 30-minute BOOST mode |
| `set_holiday(days)` | Set holiday mode (0=OFF, 1-255=days) |
| `clear_holiday()` | Disable holiday mode |
| `set_preheat(enable)` | Enable/disable winter preheat |
| `set_summer_limit(enable)` | Control summer limit |
| `get_schedule()` | Read 24-hour time slot configuration |
| `set_schedule(config)` | Write 24-hour time slot configuration |

### Data Classes

**DeviceStatus** (from `get_status()`): Contains airflow settings, temperatures, humidity, filter life, holiday mode, and device configuration. Temperature readings may be cached.

**SensorData** (from `get_sensors()`): Contains fresh probe temperature and humidity readings.

**ScheduleConfig** / **ScheduleSlot**: 24-hour schedule with per-slot airflow mode and preheat temperature.

See [docs/protocol.md](docs/protocol.md) for complete field documentation.

### Airflow Calculation

Actual m³/h values are installation-specific, calculated from configured volume:

| Mode | Formula |
|------|---------|
| LOW | volume × 0.36 |
| MEDIUM | volume × 0.45 |
| HIGH | volume × 0.55 |

Access via `status.airflow_low`, `status.airflow_medium`, `status.airflow_high`.

## How the Protocol Was Reverse-Engineered

No official protocol documentation exists. The BLE protocol was decoded entirely through traffic analysis, controlled experiments, and physical measurements.

### Approach

The vendor's **VMI+ mobile app** (Android) served as the reference implementation. By capturing the Bluetooth traffic between the app and the device, then correlating specific app actions with the packets on the wire, each protocol field was identified and mapped.

The general workflow for decoding a new feature:

1. **Capture** — Enable Android's BT HCI snoop logging, perform a specific action in the VMI+ app (e.g. toggle preheat, change fan speed), and pull the full Bluetooth log from the phone.
2. **Extract** — Filter the capture for writes and notifications on the two GATT characteristics the device uses. Classify packets by type byte.
3. **Correlate** — Match packets to timestamped screenshots of the app, narrowing down which bytes changed in response to which user action.
4. **Hypothesize** — Form a theory about what a byte offset or command parameter means.
5. **Verify** — Send the command from our own code and confirm the device responds correctly, both in BLE state and physical behavior.

### Tools

**Traffic capture:** An Android phone running the VMI+ app, with BT HCI snoop logging enabled in Developer Options. A custom CLI tool ([`vmictl`](scripts/capture/vmictl.py)) automates the phone over ADB — launching the app, navigating screens, taking screenshots, and managing capture sessions. Each session records timestamped checkpoints alongside the Bluetooth log, so packets can be correlated with observed app state.

**Packet analysis:** [`extract_packets.py`](scripts/capture/extract_packets.py) parses btsnoop logs, extracts VisionAir packets by matching the `0xa5 0xb6` magic prefix, and displays them alongside checkpoint data within configurable time windows.

**BLE connectivity:** The device is in a garage, out of direct BLE range from the development machine. An [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html) on an M5Stack ESP32 bridges the gap, allowing the library and test scripts to communicate with the device over WiFi.

**Physical verification:** BLE state bytes can change without the fan motor actually changing speed. To get ground truth, an accelerometer (MPU6886 on an M5StickC Plus2) is mounted on the device housing. It measures vibration caused by the fan motor — higher speed means higher vibration. This caught cases where commands changed protocol bytes but had no physical effect, and confirmed that the fan speed command (`REQUEST` param `0x18`) does change the real motor speed. Details in [physical-verification.md](docs/reverse-engineering/physical-verification.md).

### What we learned about the firmware

The device uses a **Cypress PSoC 4 BLE** chip. The GATT service UUIDs and characteristic handles are identical to Cypress's "Day003 Custom Profile" demo project, suggesting the firmware was built on that template. The protocol uses fixed-size 182-byte packets with `0xa5 0xb6` magic bytes and an XOR checksum — a pattern typical of serial (UART) protocols, likely predating the BLE interface. Fields are at fixed byte offsets with no self-describing format (no TLV, no protobuf), consistent with raw C struct serialization. See [implementation-speculation.md](docs/implementation-speculation.md) for the full analysis.

### Challenges

- **Schedule interference.** The device enforces its internal 24-hour schedule autonomously, overriding manual mode changes within seconds. Early experiments produced contradictory results until this was identified and the schedule was disabled before testing.
- **Single-connection bottleneck.** The device accepts one BLE connection at a time, and the ESPHome proxy accepts one client at a time. Testing requires carefully disconnecting the phone app and Home Assistant before running scripts.
- **Stale sensor data.** The wireless remote sensor transmits infrequently (battery-powered RF). Temperature readings can take 20+ minutes to update after environmental changes, which initially looked like protocol bugs.
- **Fan speed changes below human hearing.** The LOW-to-HIGH speed change (+37% vibration) is inaudible at typical distances. Early "listen tests" concluded that commands had no physical effect. The accelerometer proved otherwise.

## Documentation

- [Protocol Specification](docs/protocol.md) - BLE protocol details, packet formats, field offsets
- [Implementation Status](docs/implementation-status.md) - Feature tracking
- [Reverse Engineering Playbook](docs/reverse-engineering/playbook.md) - Capture setup and methodology
- [Physical Verification](docs/reverse-engineering/physical-verification.md) - Vibration-based fan speed measurement
- [Firmware Analysis](docs/implementation-speculation.md) - PSoC heritage and protocol structure

## License

MIT License - see [LICENSE](LICENSE) for details.
