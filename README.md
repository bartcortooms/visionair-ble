# visionair-ble

Unofficial Python library for controlling VisionAir ventilation devices over Bluetooth Low Energy.

> **Disclaimer:** This project is not affiliated with, endorsed by, or connected to Ventilairsec, Purevent, VisionAir, or any related companies. All product names, trademarks, and registered trademarks are the property of their respective owners. This library was developed independently through reverse engineering for interoperability purposes.

## Supported Devices

All devices advertise as "VisionAir" over BLE:

| Model | Hardware Max | Target Use | Status |
|-------|-------------|------------|--------|
| **Purevent Vision'R** | 350 m³/h | Houses (250-300 m²) | ✅ Tested |
| **Urban Vision'R** | 201 m³/h | Apartments (~100 m²) | ⚠️ Untested |
| **Cube Vision'R** | ? | Compact installations | ⚠️ Untested |

## Features

- Read device status (airflow, temperatures, humidity, filter life)
- Set airflow level (LOW, MEDIUM, or HIGH)
- Control preheat and summer limit settings
- Activate/deactivate BOOST mode
- Support for direct BLE and ESPHome proxy connections

## Installation

```bash
pip install visionair-ble
```

For ESPHome proxy support:

```bash
pip install visionair-ble[proxy]
```

## Quick Start

### Direct Connection

```python
import asyncio
from visionair_ble import VisionAirClient, format_sensors
from visionair_ble.connect import connect_direct

async def main():
    async with connect_direct("00:A0:50:XX:XX:XX") as client:
        visionair = VisionAirClient(client)

        # Get and display all sensors using metadata
        status = await visionair.get_status()
        print(format_sensors(status))
        # Output:
        # Airflow: 180 m³/h
        # Airflow mode: medium
        # Room temperature: 21 °C
        # Outlet temperature: 18 °C
        # ...

        # Or access fields directly
        print(f"Airflow: {status.airflow} m³/h ({status.airflow_mode})")

        # Set airflow to medium
        await visionair.set_airflow_mode("medium")

asyncio.run(main())
```

### Via ESPHome Proxy

When the device is out of Bluetooth range, connect through an ESPHome device with `bluetooth_proxy` enabled:

```python
from visionair_ble import VisionAirClient
from visionair_ble.connect import connect_via_proxy

async with connect_via_proxy("192.168.1.100", api_key="your_noise_psk") as client:
    visionair = VisionAirClient(client)
    status = await visionair.get_status()
```

### Home Assistant Integration

For Home Assistant, use HA's Bluetooth stack which handles proxy routing automatically:

```python
from visionair_ble import VisionAirClient
from bleak import BleakClient

# HA provides the BLEDevice
ble_device = async_ble_device_from_address(hass, "00:A0:50:XX:XX:XX")
async with BleakClient(ble_device) as client:
    visionair = VisionAirClient(client)
    status = await visionair.get_status()
```

## API Reference

### VisionAirClient

The main interface for device control.

```python
from visionair_ble import VisionAirClient

visionair = VisionAirClient(ble_client)

# Status and sensors
status = await visionair.get_status()      # Get device config/settings
sensors = await visionair.get_sensors()    # Get live sensor readings (temps, humidity)

# Airflow control (mode-based, recommended)
await visionair.set_airflow_mode("low")    # Low airflow
await visionair.set_airflow_mode("medium") # Medium airflow
await visionair.set_airflow_mode("high")   # High airflow

# Convenience methods
await visionair.set_airflow_low()          # Same as set_airflow_mode("low")
await visionair.set_airflow_medium()       # Same as set_airflow_mode("medium")
await visionair.set_airflow_high()         # Same as set_airflow_mode("high")

# BOOST mode (30 minutes high airflow)
await visionair.set_boost(True)            # Enable
await visionair.set_boost(False)           # Disable

# Settings
await visionair.set_preheat(True, temperature=16)  # Enable preheat at 16°C
await visionair.set_summer_limit(True)             # Enable summer limit
```

### DeviceStatus

Status data returned by `get_status()`:

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | int | Unique device identifier |
| `configured_volume` | int | Configured ventilated space volume (m³) |
| `airflow` | int | Current airflow in m³/h (calculated from volume) |
| `airflow_mode` | str | Current mode ("low", "medium", "high", or "unknown") |
| `airflow_low` | int | Low airflow setting (m³/h) |
| `airflow_medium` | int | Medium airflow setting (m³/h) |
| `airflow_high` | int | High airflow setting (m³/h) |
| `preheat_enabled` | bool | Winter preheat active |
| `preheat_temp` | int | Preheat target temperature (°C) |
| `summer_limit_enabled` | bool | Summer limit active |
| `boost_active` | bool | BOOST mode active |
| `temp_remote` | int | Remote control temperature (°C) |
| `temp_probe1` | int | Probe 1 temperature (°C) |
| `temp_probe2` | int | Probe 2 temperature (°C) |
| `humidity_remote` | float | Remote humidity (%) |
| `filter_days` | int | Filter life remaining (days) |
| `operating_days` | int | Total operating days |

### SensorData

Live sensor readings returned by `get_sensors()`:

| Field | Type | Description |
|-------|------|-------------|
| `temp_probe1` | int | Probe 1 temperature (°C) - fresh reading |
| `temp_probe2` | int | Probe 2 temperature (°C) - fresh reading |
| `humidity_probe1` | int | Probe 1 humidity (%) |
| `filter_percent` | int | Filter percentage (100 = new) |

**Note:** The temperatures in `DeviceStatus` (from `get_status()`) may be stale/cached.
For accurate temperature readings, use `get_sensors()` or check the coordinator which
merges both automatically.

## Protocol Documentation

See [docs/protocol.md](docs/protocol.md) for detailed BLE protocol specification.

## Installation-Specific Airflow Values

The actual m³/h airflow values are **installation-specific**, calculated from your configured volume. The device reports the configured volume in the status response, and the library calculates the actual airflow values:

- LOW = volume × 0.36 ACH
- MEDIUM = volume × 0.45 ACH
- HIGH = volume × 0.55 ACH

Use `status.airflow_low`, `status.airflow_medium`, `status.airflow_high` to get the actual values for your installation.

See [docs/protocol.md](docs/protocol.md#volume-dependent-airflow-configuration) for technical details.

## Disclaimer

This is an **unofficial**, **community-developed** library created through reverse engineering of the BLE protocol for personal interoperability purposes.

- This project is **not affiliated with, endorsed by, or connected to** Ventilairsec, Purevent, VisionAir, or any related companies
- All product names, trademarks, and registered trademarks are the property of their respective owners
- Use this software at your own risk; the authors are not responsible for any damage to your equipment
- This library may stop working if the manufacturer changes the device firmware

## License

MIT License - see [LICENSE](LICENSE) for details.
