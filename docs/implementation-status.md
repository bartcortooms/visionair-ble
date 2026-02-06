# Implementation Status

This document tracks which protocol features from [protocol.md](protocol.md) are implemented in the library (`visionair_ble/protocol.py`).

## Commands (Write Operations)

| Feature | Documented | Implemented | Function |
|---------|------------|-------------|----------|
| Status Request (0x10, param 0x03) | Yes | Yes | `build_status_request()` |
| Full Data Request (0x10, param 0x06) | Yes | Yes | `build_full_data_request()` |
| Sensor Request (0x10, param 0x07) | Yes | Yes | `build_sensor_request()` |
| Sensor Select Request (0x10, param 0x18) | Yes | Yes | `build_sensor_select_request(sensor)` — verified 2026-02-05 |
| BOOST ON/OFF (0x10, param 0x19) | Yes | Yes | `build_boost_command()` |
| Settings (0x1a) - airflow/preheat/summer | Yes | Yes | `build_settings_packet()` |
| Holiday Command (0x10, param 0x1a) | Yes | Yes | `build_holiday_command(days)`, `VisionAirClient.set_holiday()` / `clear_holiday()` |
| Holiday Status Query (0x10, param 0x2c) | Yes | Yes | `build_holiday_status_query()` |
| Night Ventilation (0x1a, byte7=0x04) — hypothetical | Partial | Experimental | `build_night_ventilation_activate()` — [#6](https://github.com/bartcortooms/visionair-ble/issues/6) |
| Fixed Air Flow (0x1a, byte7=0x04) — hypothetical | Partial | Experimental | `build_fixed_airflow_activate()` — packet captured ([#7](https://github.com/bartcortooms/visionair-ble/issues/7)) but protocol path uncertain ([#14](https://github.com/bartcortooms/visionair-ble/issues/14)) |
| Schedule Config Write (0x40) | Experimental | Experimental | `build_schedule_write()`, `VisionAirClient.set_schedule()` — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Config Read (0x46) | Experimental | Experimental | `parse_schedule_config()`, `VisionAirClient.get_schedule()` — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Query (0x47) | Experimental | No | Direction/structure unclear — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Command (0x1a, byte7=0x05) | Partial | No | — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |

## Responses (Notification Parsing)

| Feature | Documented | Implemented | Function |
|---------|------------|-------------|----------|
| Status (0x01) - core fields | Yes | Yes | `parse_status()` |
| Status - diagnostic bitfield (byte 54) | Partial | No | Bit mapping unverified — [#4](https://github.com/bartcortooms/visionair-ble/issues/4) |
| Status - bypass state | Partial | No | — [#5](https://github.com/bartcortooms/visionair-ble/issues/5) |
| Sensor/History (0x03) | Yes | Yes | `parse_sensors()` |
| Schedule (0x02) - current time | Yes | No | — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Config Response (0x46) | Experimental | Experimental | `parse_schedule_config()` — needs e2e verification |
| Settings Ack (0x23) | Partial | No | — |
| Status - holiday_days (byte 43) | Yes | Yes | `parse_status()` → `DeviceStatus.holiday_days` |
| Holiday Status (0x50) | Partial | No | Constant response, not useful for state |

## Data Structures

| Feature | Documented | Implemented | Notes |
|---------|------------|-------------|-------|
| `DeviceStatus` dataclass | Yes | Yes | Core status fields |
| `SensorData` dataclass | Yes | Yes | Live sensor readings |
| `ScheduleSlot` dataclass | Yes | Yes | Per-hour schedule slot (preheat temp + mode) |
| `ScheduleConfig` dataclass | Yes | Yes | 24-hour schedule (list of slots) |
| Schedule mode byte mapping | Partial | Yes | LOW=0x28, MEDIUM=0x32, HIGH=unknown |
| Airflow mode mapping | Yes | Yes | LOW/MEDIUM/HIGH — byte meaning unknown |
| Volume-based calculation | Yes | Yes | ACH multipliers |
| Sensor metadata for HA | Yes | Yes | Auto-discovery support |

## Experimental Features

Features marked "Experimental" require `_experimental=True` flag to use. They have known gaps in protocol understanding:

- **Night Ventilation / Fixed Air Flow** — Hypothetical SETTINGS-based activation (byte7=0x04):
  - Never observed in current captures; packet mapping is unconfirmed
  - We don't know how the device distinguishes between these three modes
  - May require different preceding queries or internal state

- **Schedule Config (0x40, 0x46)** — Implemented as experimental (`_experimental=True` required):
  - `build_schedule_write()` / `set_schedule()`: Builds 0x40 packet (55 bytes, 24 slots)
  - `parse_schedule_config()` / `get_schedule()`: Parses 0x46 response (182 bytes)
  - `ScheduleSlot` / `ScheduleConfig`: Data structures for schedule representation
  - Unknown: HIGH mode byte, 0x47 trigger/purpose, device ack after 0x40 write
  - Unknown: Whether Full Data Request triggers 0x46 (or if a separate command is needed)
  - Needs: controlled VMI capture session (issue #2, Phase 1) for e2e verification

## Needs Verification

Features that need more data before implementing:

- **Diagnostic bitfield (byte 54)** — Only value 0x0F (all healthy) observed. Bit-to-component mapping is assumed based on UI order. Need a device with a faulty component to verify.

- **Schedule Mode 3 (HIGH)** — Byte value not captured. Only Mode 1 (0x28) and Mode 2 (0x32) observed.

- **Airflow setting bytes** — The byte pairs (0x19/0x0A, 0x28/0x15, 0x07/0x30) work for LOW/MEDIUM/HIGH but their actual meaning (PWM? calibration?) is unknown.
