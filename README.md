# visionair-ble

Unofficial Python library for controlling VisionAir ventilation devices over Bluetooth Low Energy.

> **Disclaimer:** This project is not affiliated with Ventilairsec, Purevent, VisionAir, or any related companies. All trademarks are the property of their respective owners. This library was developed through reverse engineering for interoperability purposes.

---

## Start here (newcomers)

If you only need to **read status** and **set airflow mode**, start with this section and ignore the rest for now.

### What this library gives you

- Read device status (airflow, temperatures, humidity, filter life)
- Read fresh sensor probes
- Control airflow mode / boost / holiday / preheat / summer limit
- Read and write 24-hour schedule

### Supported devices

All devices advertise as `VisionAir` over BLE (MAC prefix `00:A0:50`).

- **Purevent Vision'R** (350 m³/h) - Tested
- **Urban Vision'R** (201 m³/h) - Untested
- **Cube Vision'R** - Untested

### Install

```bash
pip install visionair-ble
```

If you connect through an ESPHome Bluetooth proxy:

```bash
pip install visionair-ble[proxy]
```

### 5-minute quick start

```python
import asyncio
from visionair_ble import VisionAirClient
from visionair_ble.connect import connect_direct

async def main():
    async with connect_direct("00:A0:50:XX:XX:XX") as client:
        vmi = VisionAirClient(client)

        # Read current status
        status = await vmi.get_status()
        print(f"Airflow: {status.airflow} m³/h ({status.airflow_mode})")
        print(f"Room: {status.temp_remote}°C, {status.humidity_remote}%")
        print(f"Filter: {status.filter_days} days remaining")

        # Change airflow mode
        await vmi.set_airflow_mode("medium")  # "low" | "medium" | "high"

asyncio.run(main())
```

If this works, you’re up and running.

---

## Connection options

Use one of these depending on your setup.

### 1) Direct BLE (device in range)

```python
from visionair_ble.connect import connect_direct

async with connect_direct("00:A0:50:XX:XX:XX") as client:
    ...
```

### 2) ESPHome proxy (device out of range)

```python
from visionair_ble.connect import connect_via_proxy

async with connect_via_proxy("192.168.1.100", api_key="your_noise_psk") as client:
    ...
```

Requires: `pip install visionair-ble[proxy]`.

### 3) Home Assistant context (HA Bluetooth stack)

```python
from bleak import BleakClient
ble_device = async_ble_device_from_address(hass, "00:A0:50:XX:XX:XX")
async with BleakClient(ble_device) as client:
    visionair = VisionAirClient(client)
    ...
```

### Scan for devices

```python
from visionair_ble.connect import scan_direct, scan_via_proxy

# Scan locally
devices = await scan_direct(timeout=10.0)

# Scan via ESPHome proxy
devices = await scan_via_proxy("192.168.1.100", api_key="...", scan_timeout=10.0)

for address, name in devices:
    print(f"Found: {address} ({name})")
```

---

## Common tasks cookbook

```python
# Given: vmi = VisionAirClient(client)

status = await vmi.get_status()           # config + settings + readings
sensors = await vmi.get_sensors()         # probe readings
fresh = await vmi.get_fresh_status()      # status + fresh probes

await vmi.set_airflow_mode("high")       # "low" | "medium" | "high"
await vmi.set_boost(True)                 # 30-min BOOST
await vmi.set_holiday(7)                  # 7-day holiday mode
await vmi.clear_holiday()                 # holiday OFF
await vmi.set_preheat(True)
await vmi.set_summer_limit(True)

schedule = await vmi.get_schedule()
await vmi.set_schedule(schedule)
```

---

## API reference

### `VisionAirClient`

| Method | Description |
|--------|-------------|
| `get_status()` | Device config, settings, and sensor readings |
| `get_sensors()` | Live probe temperature and humidity readings |
| `get_fresh_status()` | Status with fresh readings from all sensors |
| `set_airflow_mode(mode)` | Set airflow to `"low"`, `"medium"`, or `"high"` |
| `set_airflow_low/medium/high()` | Convenience methods for airflow control |
| `set_boost(enable)` | Enable/disable 30-minute BOOST mode |
| `set_holiday(days)` | Set holiday mode (`0=OFF`, `1-255=days`) |
| `clear_holiday()` | Disable holiday mode |
| `set_preheat(enable)` | Enable/disable winter preheat |
| `set_summer_limit(enable)` | Control summer limit |
| `get_schedule()` | Read 24-hour time slot configuration |
| `set_schedule(config)` | Write 24-hour time slot configuration |

### Data classes

- **`DeviceStatus`** (from `get_status()`): airflow settings, temperatures, humidity, filter life, holiday mode, and device configuration. Temperature readings may be cached.
- **`SensorData`** (from `get_sensors()`): fresh probe temperature/humidity readings.
- **`ScheduleConfig` / `ScheduleSlot`**: 24-hour schedule with per-slot airflow mode and preheat temperature.

Full field docs: [docs/protocol.md](docs/protocol.md)

### Airflow calculation

Actual m³/h values are installation-specific, derived from configured volume:

| Mode | Formula |
|------|---------|
| LOW | volume × 0.36 |
| MEDIUM | volume × 0.45 |
| HIGH | volume × 0.55 |

Access via `status.airflow_low`, `status.airflow_medium`, `status.airflow_high`.

---

## Troubleshooting (quick)

### `Device not found`

Most common cause: BLE connection contention.

- VisionAir device accepts **one BLE connection at a time**
- ESPHome proxy accepts **one client at a time**
- Ensure phone app and HA integrations are not currently holding BLE/proxy

### `No module named aioesphomeapi`

Install proxy extras:

```bash
pip install visionair-ble[proxy]
```

### Writes seem to "work" but physical behavior doesn’t change

The protocol state can update without obvious physical effect. See physical verification notes below.

---

## Project docs (pick what you need)

- [Protocol Specification](docs/protocol.md) - packet formats, fields, offsets
- [Implementation Status](docs/implementation-status.md) - feature tracking
- [Reverse Engineering Playbook](docs/reverse-engineering/playbook.md) - capture workflow
- [Physical Verification](docs/reverse-engineering/physical-verification.md) - vibration-based validation
- [Firmware Analysis](docs/implementation-speculation.md) - PSoC heritage and protocol structure

---

## Advanced: how the protocol was reverse-engineered

No official protocol documentation exists. The BLE protocol was decoded through traffic analysis, controlled experiments, and physical measurements.

### Approach

The vendor **VMI+ Android app** was used as the reference implementation. By capturing BLE traffic while performing known app actions, packet fields could be mapped and validated.

Typical loop:

1. **Capture** — Enable BT HCI snoop, perform one app action, pull Bluetooth log
2. **Extract** — Filter writes/notifications on VisionAir characteristics
3. **Correlate** — Match packet timing with timestamped app screenshots
4. **Hypothesize** — Propose byte/field meaning
5. **Verify** — Reproduce from code and confirm BLE + physical behavior

### Tooling used

- **Traffic capture:** Android + BT snoop logging + [`vmictl`](scripts/capture/vmictl.py) for ADB automation and session checkpoints
- **Packet analysis:** [`extract_packets.py`](scripts/capture/extract_packets.py)
- **BLE bridge:** [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html) on M5Stack ESP32
- **Physical validation:** accelerometer on device housing to verify real motor-speed changes

### Firmware observations

- Device appears based on **Cypress PSoC 4 BLE** demo profile heritage
- Uses fixed-size 182-byte packets with `0xa5 0xb6` magic + XOR checksum
- Field layout is fixed-offset (raw struct-style), no self-describing format

Details: [implementation-speculation.md](docs/implementation-speculation.md)

### Practical challenges discovered

- **Schedule interference:** internal schedule can override manual mode changes quickly
- **Single-connection bottleneck:** device + proxy each enforce one active client
- **Stale sensor data:** remote sensor updates infrequently
- **Low-audibility speed changes:** physical changes can be inaudible without instrumentation

---

## License

MIT License - see [LICENSE](LICENSE) for details.
