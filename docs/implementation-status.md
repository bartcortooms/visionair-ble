# Implementation Status

This document tracks which protocol features from [protocol.md](protocol.md) are implemented in the library (`visionair_ble/protocol.py`).

## Commands (Write Operations)

| Feature | Documented | Implemented | Function |
|---------|------------|-------------|----------|
| Status Request (0x10, param 0x03) | Yes | Yes | `build_status_request()` |
| Sensor Request (0x10, param 0x07) | Yes | Yes | `build_sensor_request()` |
| Sensor Cycle Request (0x10, param 0x18) | Yes | Yes | `build_sensor_cycle_request()` |
| BOOST ON/OFF (0x10, param 0x19) | Yes | Yes | `build_boost_command()` |
| Settings (0x1a) - airflow/preheat/summer | Yes | Yes | `build_settings_packet()` |
| Holiday Days Query (0x10, param 0x1a) | Partial | Experimental | `build_holiday_days_query()` |
| Holiday Activate (0x1a, byte7=0x04) | Partial | Experimental | `build_holiday_activate()` |
| Holiday Status Query (0x10, param 0x2c) | Yes | Yes | `build_holiday_status_query()` |
| Night Ventilation (0x1a, byte7=0x04) | Partial | Experimental | `build_night_ventilation_activate()` |
| Fixed Air Flow (0x1a, byte7=0x04) | Partial | Experimental | `build_fixed_airflow_activate()` |
| Schedule Config (0x46, 0x47) | Yes | No | — |
| Schedule Command (0x1a, byte7=0x05) | Partial | No | — |

## Responses (Notification Parsing)

| Feature | Documented | Implemented | Function |
|---------|------------|-------------|----------|
| Status (0x01) - core fields | Yes | Yes | `parse_status()` |
| Status - diagnostic bitfield (byte 54) | Partial | No | Bit mapping unverified |
| Status - bypass state | Partial | No | — |
| Sensor/History (0x03) | Yes | Yes | `parse_sensors()` |
| Schedule (0x02) - current time | Yes | No | — |
| Schedule Config (0x46) | Yes | No | — |
| Settings Ack (0x23) | Partial | No | — |
| Holiday Status (0x50) | Partial | No | — |

## Data Structures

| Feature | Documented | Implemented | Notes |
|---------|------------|-------------|-------|
| `DeviceStatus` dataclass | Yes | Yes | Core status fields |
| `SensorData` dataclass | Yes | Yes | Live sensor readings |
| Airflow mode mapping | Yes | Yes | LOW/MEDIUM/HIGH |
| Volume-based calculation | Yes | Yes | ACH multipliers |
| Sensor metadata for HA | Yes | Yes | Auto-discovery support |

## Priority Candidates

Features that are fully documented and ready for implementation:

1. **Schedule Config** — Time slot read/write for automated ventilation profiles
2. **Holiday Status (0x50)** — Parse response from `build_holiday_status_query()`

## Experimental Features

Features marked "Experimental" require `_experimental=True` flag to use. They have known gaps in protocol understanding:

- **Holiday Mode** — Activation sequence captured, but:
  - No deactivation packets captured (how to cancel Holiday mode?)
  - Unclear if the days query is sufficient or if other state is needed

- **Night Ventilation / Fixed Air Flow** — Packet structure appears identical to Holiday mode:
  - We don't know how the device distinguishes between these three modes
  - May require different preceding queries or internal state
  - No deactivation packets captured

## Needs Verification

Features that need more data before implementing:

- **Diagnostic bitfield (byte 54)** — Only value 0x0F (all healthy) observed. Bit-to-component mapping is assumed based on UI order. Need a device with a faulty component to verify.
