# Implementation Status

This document tracks which protocol features from [protocol.md](protocol.md) are implemented in the library (`visionair_ble/protocol.py`).

## Commands (Write Operations)

| Feature | Documented | Implemented | Function |
|---------|------------|-------------|----------|
| Status Request (0x10, param 0x03) | Yes | Yes | `build_status_request()` |
| Full Data Request (0x10, param 0x06) | Yes | Yes | `build_full_data_request()` |
| Sensor Request (0x10, param 0x07) | Yes | Yes | `build_sensor_request()` |
| Mode Select (0x10, param 0x18) | Yes | Yes | `build_mode_select_request(mode)` — controls fan speed. Physical speed change verified via vibration sensor 2026-02-08 ([#22](https://github.com/bartcortooms/visionair-ble/issues/22)) |
| BOOST ON/OFF (0x10, param 0x19) | Yes | Yes | `build_boost_command()` |
| Preheat Toggle (0x10, param 0x2F) | Yes | Yes | `build_preheat_request()` |
| Settings (0x1a) - clock sync | Yes | No | Phone sends clock sync only; library sends config-mode packet (unverified, see #21) |
| Holiday Command (0x10, param 0x1a) | Yes | Yes | `build_holiday_command(days)`, `VisionAirClient.set_holiday()` / `clear_holiday()` |
| Unknown Query (0x10, param 0x2c) | Yes | Yes | `build_unknown_2c_query()` |
| Night Ventilation (0x1a, byte7=0x04) — hypothetical | Partial | Experimental | `build_night_ventilation_activate()` — [#6](https://github.com/bartcortooms/visionair-ble/issues/6) |
| Fixed Air Flow (0x1a, byte7=0x04) — hypothetical | Partial | Experimental | `build_fixed_airflow_activate()` — packet captured ([#7](https://github.com/bartcortooms/visionair-ble/issues/7)) but protocol path uncertain ([#14](https://github.com/bartcortooms/visionair-ble/issues/14)) |
| Schedule Config Request (0x10, param 0x27) | Yes | Yes | `build_schedule_config_request()` — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Toggle (0x10, param 0x1d) | Yes | Yes | `build_schedule_toggle()` — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Config Write (0x40) | Yes | Yes | `build_schedule_write()`, `VisionAirClient.set_schedule()` — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Config Read (0x46) | Yes | Yes | `parse_schedule_config()`, `VisionAirClient.get_schedule()` — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Query (0x47) | Partial | No | Triggered by param 0x26, structure unclear — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Command (0x1a, byte7=0x05) | Partial | No | — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |

## Responses (Notification Parsing)

| Feature | Documented | Implemented | Function |
|---------|------------|-------------|----------|
| Status (0x01) - core fields | Yes | Yes | `parse_status()` |
| Status - diagnostic bitfield (byte 54) | Partial | No | Bit mapping unverified — [#4](https://github.com/bartcortooms/visionair-ble/issues/4) |
| Status - bypass state | Partial | No | — [#5](https://github.com/bartcortooms/visionair-ble/issues/5) |
| Sensor/History (0x03) | Yes | Yes | `parse_sensors()` |
| Schedule (0x02) - current time | Yes | No | — [#2](https://github.com/bartcortooms/visionair-ble/issues/2) |
| Schedule Config Response (0x46) | Yes | Yes | `parse_schedule_config()` — validated against real captures |
| Settings Ack (0x23) | Partial | No | — |
| Status - holiday_days (byte 43) | Yes | Yes | `parse_status()` → `DeviceStatus.holiday_days` |
| Unknown (0x50) | Partial | No | Constant response, purpose unknown |

## Data Structures

| Feature | Documented | Implemented | Notes |
|---------|------------|-------------|-------|
| `DeviceStatus` dataclass | Yes | Yes | Core status fields |
| `SensorData` dataclass | Yes | Yes | Live sensor readings |
| `ScheduleSlot` dataclass | Yes | Yes | Per-hour schedule slot (preheat temp + mode) |
| `ScheduleConfig` dataclass | Yes | Yes | 24-hour schedule (list of slots) |
| Schedule mode byte mapping | Yes | Yes | LOW=0x28, MEDIUM=0x32, HIGH=0x3C |
| `AIRFLOW_BYTES` | Partial | Yes | Config-mode byte pairs keyed by airflow level; unverified — may be clock sync artifacts (see #21) |
| Volume-based calculation | Yes | Yes | ACH multipliers |
| Sensor metadata for HA | Yes | Yes | Auto-discovery support |

## Experimental Features

Features marked "Experimental" require `_experimental=True` flag to use. They have known gaps in protocol understanding:

- **Night Ventilation / Fixed Air Flow** — Hypothetical SETTINGS-based activation (byte7=0x04):
  - Never observed in current captures; packet mapping is unconfirmed
  - We don't know how the device distinguishes between these three modes
  - May require different preceding queries or internal state

## Needs Verification

Features that need more data before implementing:

- **Diagnostic bitfield (byte 54)** — Only value 0x0F (all healthy) observed. Bit-to-component mapping is assumed based on UI order. Need a device with a faulty component to verify.

- **~~SETTINGS byte-pair semantics~~** — SETTINGS bytes 7-10 carry clock sync (day, hour, minute, second). The `AIRFLOW_BYTES` pairs (0x19/0x0A, 0x28/0x15, 0x07/0x30) are plausible timestamp values; their role as airflow configuration is unverified. See protocol.md §7.1 and #21.
