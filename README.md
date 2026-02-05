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
        await visionair.set_preheat(True, temperature=16)
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
| `set_preheat(enable, temperature)` | Control winter preheat |
| `set_summer_limit(enable)` | Control summer limit |

### Data Classes

**DeviceStatus** (from `get_status()`): Contains airflow settings, temperatures, humidity, filter life, and device configuration. Temperature readings may be cached.

**SensorData** (from `get_sensors()`): Contains fresh probe temperature and humidity readings.

See [docs/protocol.md](docs/protocol.md) for complete field documentation.

### Airflow Calculation

Actual m³/h values are installation-specific, calculated from configured volume:

| Mode | Formula |
|------|---------|
| LOW | volume × 0.36 |
| MEDIUM | volume × 0.45 |
| HIGH | volume × 0.55 |

Access via `status.airflow_low`, `status.airflow_medium`, `status.airflow_high`.

## Documentation

- [Protocol Specification](docs/protocol.md) - BLE protocol details, packet formats, field offsets
- [Implementation Status](docs/implementation-status.md) - Feature tracking

## License

MIT License - see [LICENSE](LICENSE) for details.
