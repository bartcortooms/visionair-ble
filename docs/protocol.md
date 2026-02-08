# VisionAir BLE Protocol Specification

This document describes the BLE GATT protocol used by Ventilairsec VisionAir (Vision'R range) ventilation devices, reverse-engineered for interoperability purposes.

> **Disclaimer:** This is unofficial documentation created through reverse engineering. This project is not affiliated with, endorsed by, or connected to Ventilairsec, Purevent, VisionAir, or any related companies. All product names and trademarks are the property of their respective owners.

## 1. Overview

### Supported Devices

All devices in the Vision'R range advertise as "VisionAir" over BLE:

| Model | Hardware Max | Status |
|-------|-------------|--------|
| **Purevent Vision'R** | 350 m³/h | Tested |
| **Urban Vision'R** | 201 m³/h | Untested |
| **Cube Vision'R** | ? | Untested |

### Device Information

| Property | Value |
|----------|-------|
| BLE Name | `VisionAir` |
| MAC Prefix | `00:A0:50` |
| Chip | Cypress Semiconductor (PSoC BLE) |

## 2. How the Protocol Works

The VisionAir protocol is simple in structure but spread across multiple response packets. Here's the mental model:

**Interface:** Two BLE GATT characteristics — one for writing commands, one for receiving notifications. That's the entire interface.

**One command type does almost everything:** `REQUEST` (type `0x10`) is the primary command. A single parameter byte selects the operation — querying device state, reading sensors, changing fan speed, toggling preheat, and more. A second type, `SETTINGS` (type `0x1a`), handles clock sync and configuration writes.

**Packet structure:** Every packet (commands and responses) uses the same envelope:

```
┌───────┬──────┬─────────────────────┬──────────┐
│ Magic │ Type │ Payload             │ Checksum │
│ a5 b6 │ 1 B  │ variable            │ XOR      │
└───────┴──────┴─────────────────────┴──────────┘

REQUEST command example (param 0x06 = "get everything"):

  a5 b6  10  06 05 06 00 00 00 00  15
  ╰─┬──╯ ╰┬╯ ╰──────┬───────────╯ ╰┬╯
  magic  type    payload          checksum
         (REQUEST)  ╰─ param byte
```

**Three main response packets carry all the data:**

| Packet | Type | Contains |
|--------|------|----------|
| DEVICE_STATE | `0x01` | Config, mode, boost, preheat, holiday, diagnostics |
| SCHEDULE | `0x02` | Time slot schedule, **Remote sensor** (temp + humidity) |
| PROBE_SENSORS | `0x03` | Live probe temperatures and humidity |

**The "get everything" shortcut:** A single `FULL_DATA_Q` request (param `0x06`) triggers all three response packets plus a settings acknowledgment. This is more efficient than querying each individually and is the primary polling method used by the VMI+ phone app.

**Single connection:** The device accepts only one BLE client at a time. Disconnect other clients (phone app, Home Assistant integration) before connecting.

```
  Client                          VisionAir
    │                                │
    │  ── REQUEST (param 0x06) ──►   │   "Get everything"
    │                                │
    │  ◄── SETTINGS_ACK (0x23) ──    │
    │  ◄── DEVICE_STATE (0x01) ──    │   Config + settings
    │  ◄── SCHEDULE    (0x02) ──     │   Schedule + remote sensor
    │  ◄── PROBE_SENSORS (0x03) ──   │   Live probe readings
    │                                │
```

## 3. Connection & Packet Format

### BLE Services

The device uses Cypress PSoC demo profile UUIDs (vendor reused generic UUIDs).

| Service UUID | Purpose |
|-------------|---------|
| `0003cab5-0000-1000-8000-00805f9b0131` | Data Service |
| `0003cbbb-0000-1000-8000-00805f9b0131` | Control Service |

### Characteristics

| UUID | Handle | Properties | Purpose |
|------|--------|------------|---------|
| `0003caa2-...` | 0x000e | Notify | Status notifications (device → app) |
| `0003cbb1-...` | 0x0013 | Write | Commands (app → device) |

### Connection Sequence

1. Scan for device (name "VisionAir" or MAC prefix `00:A0:50`)
2. Connect
3. Discover services
4. Enable notifications: write `0x0100` to handle 0x000f
5. Send status request: write `a5b6100005030000000016` to handle 0x0013
6. Receive status notification on handle 0x000e

**Notes:**
- Only one BLE connection at a time — disconnect other clients first
- Serial number is NOT transmitted over BLE (stored locally in app)
- BOOST mode auto-deactivates after 30 minutes

### Packet Framing

All packets use:
- **Magic prefix:** `0xa5 0xb6`
- **Checksum:** XOR of all bytes after prefix (excluding checksum byte itself)

**Checksum calculation:** XOR all payload bytes (everything between magic prefix and checksum).

**Example:** `a5b6 10 00 05 03 00 00 00 00 16`
- Payload: `10 00 05 03 00 00 00 00`
- Checksum: `0x10 ^ 0x00 ^ 0x05 ^ 0x03 ^ 0x00 ^ 0x00 ^ 0x00 ^ 0x00` = `0x16`

## 4. Reading Device Data

All queries use REQUEST (type `0x10`) with a parameter byte selecting which data to retrieve. Responses arrive as notifications on handle 0x000e.

### 4.1 Full Data Request (param 0x06)

The recommended way to poll the device. A single request triggers four response packets:

```
a5b6 10 06 05 06 00 00 00 00 15
```

**Response sequence:**
1. SETTINGS_ACK (type 0x23)
2. DEVICE_STATE (type 0x01) — device config + Remote sensor
3. SCHEDULE (type 0x02) — schedule + Remote temp/humidity
4. PROBE_SENSORS (type 0x03) — current probe readings

> **Discovered (2026-02-05):** Btsnoop analysis shows the VMI app uses this
> request heavily for polling. It's more efficient than separate DEVICE_STATE and
> PROBE_SENSORS requests since it gets all data in one request sequence.

**VMI+ app polling pattern (observed):**
- **Home screen:** DEVICE_STATE_Q + FULL_DATA_Q every ~10 seconds
- **Measurements screen:** PROBE_SENSORS_Q + FULL_DATA_Q every ~10 seconds

It's unclear why the app sends both an individual query and FULL_DATA_Q, since
FULL_DATA_Q alone returns all three packet types. The extra query may be
redundant. For our purposes, a single FULL_DATA_Q is sufficient.

### 4.2 Device State (type 0x01)

**Query:** REQUEST param 0x03

```
a5b6 10 00 05 03 00 00 00 00 16
     │     │              │  └─ checksum
     │     │              └──── zeros
     │     └───────────────── param 0x03 (DEVICE_STATE)
     └─────────────────────── type 0x10 (REQUEST)
```

**Key response fields** (full byte map in [Reference Tables](#81-device-state-type-0x01-full-byte-map)):

| Offset | Description | Values |
|--------|-------------|--------|
| 22-23 | Configured volume (m³) (LE u16) | e.g. 363 |
| 26-27 | Operating days (LE u16) | e.g. 634 |
| 28-29 | Filter life days (LE u16) | e.g. 330 |
| 34 | Mode selector | 0=LOW, 1=MEDIUM, 2=HIGH |
| 43 | Holiday days remaining | 0=OFF, N=days |
| 44 | BOOST active | 0=OFF, 1=ON |
| 47 | Airflow indicator | 0x68=LOW, 0xC2=MED, 0x26=HIGH |
| 50 | Summer limit enabled | 0x02=ON |
| 53 | Preheat enabled | 0x01=ON, 0x00=OFF |
| 54 | Diagnostic status bitfield | 0x0F=all OK |

> **Note:** Bytes 35 and 42 contain Probe 1/2 temperatures but are unreliable — use PROBE_SENSORS for probe readings.

### 4.3 Probe Sensors (type 0x03)

**Query:** REQUEST param 0x07

```
a5b6 10 06 05 07 00 00 00 00 14
```

**Response fields** (full byte map in [Reference Tables](#82-probe-sensors-type-0x03-full-byte-map)):

| Offset | Description |
|--------|-------------|
| 6 | Probe 1 temperature (°C) |
| 8 | Probe 1 humidity (direct %) |
| 11 | Probe 2 temperature (°C) |
| 13 | Filter percentage (100 = new) |

> **Note:** This packet does NOT contain Remote sensor data. Remote temperature
> and humidity are in the **SCHEDULE packet** (type 0x02, bytes 11 and 13),
> returned by FULL_DATA_Q (param 0x06). Remote humidity is also in
> DEVICE_STATE byte 4.

### 4.4 Remote Sensor Data (in Schedule packet, type 0x02)

The Remote sensor readings (from the wireless RF remote control unit) are
carried in the SCHEDULE packet (type 0x02), returned as part of the FULL_DATA_Q
(param 0x06) response sequence.

| Offset | Description |
|--------|-------------|
| 11 | Remote temperature (direct °C) |
| 13 | Remote humidity (direct %) |

> **Verified (2026-02-08):** Confirmed by moving the wireless remote between
> rooms with different temperatures:
>
> | Location | App Remote temp | byte[11] | App Remote hum | byte[13] |
> |----------|----------------|----------|----------------|----------|
> | Bedroom (19°C) | 21°C | 21 | 51% | 51 |
> | Garage (12°C) | 15°C | 15 | 59% | 59 |

The rest of the SCHEDULE packet contains schedule state data — most of it is
not fully decoded. See the [full byte map](#83-schedule-type-0x02-full-byte-map)
and [Open Questions](#open-questions) for details. Schedule reading/writing uses
separate packets (0x46/0x40), documented in [section 6](#6-schedule-system).

### 4.5 Sensor Summary

Sensor data is spread across three packet types. Use FULL_DATA_Q (param 0x06)
to get all three packets in one request:

| Reading | Packet | Offset | Notes |
|---------|--------|--------|-------|
| Remote temperature | SCHEDULE (0x02) | byte 11 | Direct °C |
| Remote humidity | SCHEDULE (0x02) | byte 13 | Direct % |
| Probe 1 temperature | PROBE_SENSORS (0x03) | byte 6 | Direct °C |
| Probe 1 humidity | PROBE_SENSORS (0x03) | byte 8 | Direct % |
| Probe 2 temperature | PROBE_SENSORS (0x03) | byte 11 | Direct °C |

## 5. Controlling the Device

All control commands use REQUEST (type `0x10`) with a parameter byte. The device typically responds with an updated DEVICE_STATE packet reflecting the change.

### 5.1 Fan Speed (param 0x18)

Sets the physical fan speed to one of three modes.

| Byte 9 | Mode | Indicator | Packet |
|--------|------|-----------|--------|
| 0x00 | LOW | 0x68 | `a5b610060518000000000b` |
| 0x01 | MEDIUM | 0xC2 | `a5b610060518000000010a` |
| 0x02 | HIGH | 0x26 | `a5b6100605180000000209` |

The device responds with an updated DEVICE_STATE packet where:
- Byte 34 matches the requested value
- Byte 47 (indicator) changes to the corresponding value
- Byte 60 changes (purpose unknown)

When the user taps LOW/MEDIUM/HIGH in the phone app, the phone sends a
single 0x18 request with the corresponding value.

**0x18 changes BLE state bytes and the physical fan speed** (verified
via vibration sensor on 2026-02-08, delta ~+0.007 m/s² for LOW→HIGH across
two runs). It updates DEVICE_STATE bytes (34/47/48/60), the VMI's RF
remote control display, and the fan motor speed.

> **Note:** The device has an internal schedule that can autonomously change
> the mode without any phone command. When testing 0x18 behavior, disable
> the schedule first to avoid confounding results.

### 5.2 Boost (param 0x19)

| Command | Packet | Description |
|---------|--------|-------------|
| BOOST ON | `a5b610060519000000010b` | Enable 30-min BOOST |
| BOOST OFF | `a5b610060519000000000a` | Disable BOOST |

### 5.3 Preheat (param 0x2F)

Toggles winter preheat on or off. This is a separate command from the Settings packet.

| Command | Packet | Description |
|---------|--------|-------------|
| Preheat ON | `a5b61006052f000000013d` | Enable preheat |
| Preheat OFF | `a5b61006052f000000003c` | Disable preheat |

The preheat state is reflected in DEVICE_STATE byte 53 (`0x01`=ON, `0x00`=OFF).

### 5.4 Holiday (param 0x1a)

| Command | Packet | Description |
|---------|--------|-------------|
| Holiday 3 days | `a5b61006051a000000030a` | Set 3-day holiday |
| Holiday 7 days | `a5b61006051a000000070e` | Set 7-day holiday |
| Holiday OFF | `a5b61006051a0000000009` | Disable holiday |

Byte 9 carries the number of holiday days (0=OFF, 1-255=active). The device
responds with a DEVICE_STATE packet (~130ms) reflecting the new value in
byte 43 (`holiday_days`).

**Reading holiday status:** Use DEVICE_STATE byte 43, not the 0x50 response.
The 0x50 response (from `REQUEST` param `0x2c`) is constant and does not
reflect holiday state.

**Response type:** The device responds with DEVICE_STATE (0x01), not
SETTINGS_ACK (0x23). This differs from SETTINGS commands.

> Verified via controlled capture sessions on 2026-02-05 and 2026-02-06.
> Byte 43 changes instantly to match the value sent and returns to 0 when cleared.
> Values 0, 3, 5, 7 all confirmed across multiple captures and e2e tests.

## 6. Schedule System

### 6.1 Reading the Schedule (param 0x27)

Requests the current schedule configuration. The device responds with a
Schedule Config Response (type 0x46).

```
a5b6 10 06 05 27 00 00 00 00 30
```

> **Verified (2026-02-06):** Confirmed via controlled capture sessions.
> REQUEST param 0x27 reliably triggers a 0x46 response.

#### Schedule Config Response (type 0x46)

The device's response containing current schedule configuration. Same slot
format as the write command (0x40), padded to 182 bytes with zeros. Triggered by REQUEST param 0x27.

```
a5b6 46 06 31 00 <slot_data...> <checksum> <zero padding to 182 bytes>
```

> **Verified (2026-02-06):** Parse validated against real device responses.

#### Schedule Query (type 0x47)

Triggered by REQUEST param 0x26. Structure not fully understood.

```
a5b6 47 06 18 00 08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 51
```

### 6.2 Writing the Schedule (type 0x40)

Writes the full 24-hour schedule configuration to the device. The device
responds with SETTINGS_ACK (type 0x23) within ~200ms.

The app sends the full 24-hour schedule on every single-slot change.

```
a5b6 40 06 31 00 <24 x 2-byte slots> <checksum>
```

| Offset | Size | Description |
|--------|------|-------------|
| 0-1 | 2 | Magic `a5b6` |
| 2 | 1 | Type `0x40` |
| 3-5 | 3 | Header `06 31 00` |
| 6-53 | 48 | 24 time slots (2 bytes each) |
| 54 | 1 | XOR checksum |

Each slot is 2 bytes:

| Byte | Description |
|------|-------------|
| 1 | Preheat temperature (°C), raw value (e.g., 0x10 = 16°C, 0x12 = 18°C) |
| 2 | Mode byte |

**Mode byte values:**

| Mode | Byte | Decimal | Airflow |
|------|------|---------|---------|
| Mode 1 | 0x28 | 40 | LOW |
| Mode 2 | 0x32 | 50 | MEDIUM |
| Mode 3 | 0x3C | 60 | HIGH |

> **Note:** The decimal values follow a regular 40/50/60 pattern, unlike the
> settings airflow bytes which use unrelated two-byte pairs.

**Example** (hour 0 set to HIGH at 18°C, hours 1-8 LOW, 9-17 MEDIUM, 18-23 LOW):
```
a5b6 40 06 31 00 123c 1028 1028 1028 1028 1028 1028 1028
                  1028 1032 1032 1032 1032 1032 1032 1032
                  1032 1032 1028 1028 1028 1028 1028 7b
```

> **Verified (2026-02-06):** Confirmed via controlled capture sessions (Runs 4-6).
> All three mode bytes captured and verified. Device responds with SETTINGS_ACK.

### 6.3 Enabling/Disabling Time Slots (param 0x1d)

Enables or disables the "Activating time slots" feature (found under
Configuration → "Activating time slots" in the VMI+ app). Byte 9 carries
the value: 0=OFF, 1=ON. The device responds with an UNKNOWN_05 packet.

When disabled, the "Time slot configuration" button disappears from the
Configuration screen. The device stops enforcing the hourly schedule,
allowing manual mode changes via 0x18 to persist indefinitely.

| Command | Packet | Description |
|---------|--------|-------------|
| Schedule ON | `a5b61006051d000000010f` | Enable time slots |
| Schedule OFF | `a5b61006051d000000000e` | Disable time slots |

> **Verified (2026-02-06):** Observed in controlled captures (Runs 2-3).
> **Verified (2026-02-07):** Sent `build_schedule_toggle(False)` via BLE,
> confirmed VMI+ app Configuration screen shows "Activating time slots: OFF"
> and "Time slot configuration" button disappears. Packets match phone
> captures byte-for-byte.

## 7. Advanced Topics

### 7.1 Settings & Clock Sync (type 0x1a)

The SETTINGS command is used by the phone app primarily for clock synchronization.

Structure: `a5b6 1a 06 06 1a 02 <byte7> <byte8> <byte9> <byte10> <checksum>`

| Offset | Size | Description |
|--------|------|-------------|
| 0-1 | 2 | Magic `a5b6` |
| 2 | 1 | Type `0x1a` |
| 3-5 | 3 | Header `06 06 1a` |
| 6 | 1 | Always `0x02` in captures |
| 7 | 1 | Mode byte / day (see below) |
| 8 | 1 | Hour or preheat temperature (see below) |
| 9 | 1 | Minute (clock sync) or config byte |
| 10 | 1 | Second (clock sync) or config byte |
| 11 | 1 | XOR checksum |

**Mode byte (offset 7) values:**

| Value | Meaning |
|-------|---------|
| `0x00` | Normal settings (summer limit OFF) — from early captures |
| `0x02` | Normal settings (summer limit ON) — from early captures |
| `0x05` | Schedule command |
| `0x06`, `0x07` | Clock sync (day-of-month or day-of-week) |

**Clock sync (bytes 7-10):**

The phone sends SETTINGS every ~10s during its polling loop. In these packets,
bytes 7-10 carry the current time:

| Offset | Description | Range |
|--------|-------------|-------|
| 7 | Day (of month or week) | Observed 0x06, 0x07 |
| 8 | Hour | 0-23 |
| 9 | Minute | 0-59 |
| 10 | Second | 0-59 |

Evidence from capture `fan_speed_capture_20260207_171617`:

| Byte 7 | Byte 8 | Byte 9 | Byte 10 | Interpreted time |
|--------|--------|--------|---------|-----------------|
| 0x07 | 0x10 (16) | 0x04 (4) | 0x0f (15) | day 7, 16:04:15 |
| 0x07 | 0x10 (16) | 0x0b (11) | 0x0a (10) | day 7, 16:11:10 |
| 0x07 | 0x10 (16) | 0x24 (36) | 0x05 (5) | day 7, 16:36:05 |
| 0x07 | 0x11 (17) | 0x04 (4) | 0x23 (35) | day 7, 17:04:35 |
| 0x07 | 0x11 (17) | 0x11 (17) | 0x17 (17) | day 7, 17:17:17 |

The hour increases monotonically and minutes/seconds wrap at 60. Byte 7
changed from 0x06 to 0x07 across the capture (Feb 6 → Feb 7, or Saturday
encoded differently).

> **Not yet verified:** Whether the same bytes carry config data (preheat temp,
> airflow) when the user changes settings in the app. The config bytes (3-6)
> were constant across all 29 SETTINGS packets in this capture. Early captures
> contained mode values 0x00/0x02 for config writes, but these have not been
> reproduced in recent controlled captures. It is unclear whether bytes 8-10
> carry different data in those cases.

**SETTINGS bytes 9-10 are a clock sync, not airflow** — they carry the
current minute and second.

### 7.2 Special Modes

> **Experimental:** Night Ventilation and Fixed Air Flow have significant gaps
> in protocol understanding. See [Open Questions](#open-questions) for details.

#### Night Ventilation Boost

**What we know:**
- UI toggle exists and is controllable from VMI app

**What we DON'T know:**
- Packet mapping for this mode in current captures
- Whether this uses `REQUEST` (`0x10`) or `SETTINGS` (`0x1a`) path
- OFF behavior at protocol level

#### Fixed Air Flow Rate

**What we know:**
- UI toggle exists and is controllable from VMI app

**What we DON'T know:**
- Packet mapping for this mode in current captures
- Whether this uses `REQUEST` (`0x10`) or `SETTINGS` (`0x1a`) path
- OFF behavior and selected airflow behavior

### 7.3 Airflow Calculations

Actual airflow (m³/h) depends on the configured volume (bytes 22-23 in status response):

```
LOW    = volume × 0.36 ACH
MEDIUM = volume × 0.45 ACH
HIGH   = volume × 0.55 ACH
```

ACH = Air Changes per Hour. Multiply the factor by the configured volume
(bytes 22-23, in m³) to get actual airflow in m³/h.

**Example (volume = 363 m³):**
- LOW: 363 × 0.36 = 131 m³/h
- MEDIUM: 363 × 0.45 = 163 m³/h
- HIGH: 363 × 0.55 = 200 m³/h

The volume is configured during professional installation based on the ventilated space size.

**Model specifications:**

| Model | Hardware Max | Target Use |
|-------|-------------|------------|
| Urban Vision'R | 201 m³/h | Apartments, studios |
| Purevent Vision'R | 350 m³/h | Houses |
| Pro 1000 | 1000 m³/h | Commercial |

## 8. Reference Tables

### 8.1 Device State (type 0x01) Full Byte Map

| Offset | Size | Description | Example |
|--------|------|-------------|---------|
| 0-1 | 2 | Magic | `a5b6` |
| 2 | 1 | Type | `0x01` |
| 4 | 1 | Remote humidity (%) — stale, use SCHEDULE byte 13 | 55 |
| 5-7 | 3 | Unknown (constant per device) | `68 25 40` |
| 8 | 1 | Unknown (always 18 in captures) | 18 |
| 22-23 | 2 | Configured volume (m³) (LE u16) | 363 |
| 26-27 | 2 | Operating days (LE u16) | 634 |
| 28-29 | 2 | Filter life days (LE u16) | 330 |
| 32 | 1 | Unknown (changes with mode 0x18, purpose unknown) | 19 |
| 34 | 1 | Mode selector (0=LOW, 1=MEDIUM, 2=HIGH) | 0/1/2 |
| 35 | 1 | Probe 1 temperature (°C) — unreliable, use PROBE_SENSORS | 16 |
| 38 | 1 | Summer limit temp threshold (°C) | 26 |
| 42 | 1 | Probe 2 temperature (°C) — unreliable, use PROBE_SENSORS | 11 |
| 43 | 1 | Holiday days remaining | 0=OFF, N=days |
| 44 | 1 | BOOST active | 0=OFF, 1=ON |
| 47 | 1 | Airflow indicator (0x68=LOW, 0xC2=MED, 0x26=HIGH) | 38/104/194 |
| 48 | 1 | Unknown (1 or 2, correlates with byte 34) | 1/2 |
| 49 | 1 | Unknown | — |
| 50 | 1 | Summer limit enabled | `0x02`=ON |
| 53 | 1 | Preheat enabled | `0x01`=ON, `0x00`=OFF |
| 54 | 1 | Diagnostic status bitfield | `0x0F`=all OK |
| 56 | 1 | Preheat temperature (°C) | 16 |

#### Mode Selector (byte 34)

Tracks the current fan speed mode. Matches the value sent via REQUEST param 0x18.

| Value | Fan Speed |
|-------|-----------|
| 0 | LOW |
| 1 | MEDIUM |
| 2 | HIGH |

#### Airflow Indicator (byte 47)

Each mode value produces a distinct indicator value:

| Mode | Indicator | ACH Factor | Airflow |
|------|-----------|------------|---------|
| 0 (LOW) | 0x68 (104) | × 0.36 | Lowest |
| 1 (MEDIUM) | 0xC2 (194) | × 0.45 | Mid |
| 2 (HIGH) | 0x26 (38) | × 0.55 | Highest |

#### Diagnostic Status Bitfield (byte 54)

| Bit | Value | Component |
|-----|-------|-----------|
| 0 | 1 | IAQ Sensor |
| 1 | 2 | Motor |
| 2 | 4 | Pre-heating |
| 3 | 8 | Probes |

Value `0x0F` (all bits set) indicates all components healthy.

> **Note:** Bit meanings are inferred from the device's diagnostic UI component list, but only value 0x0F (all healthy) has been observed.

### 8.2 Probe Sensors (type 0x03) Full Byte Map

| Offset | Size | Description |
|--------|------|-------------|
| 4 | 1 | Unknown (observed: 25) |
| 6 | 1 | Probe 1 temperature (°C) |
| 8 | 1 | Probe 1 humidity (direct %) |
| 11 | 1 | Probe 2 temperature (°C) |
| 13 | 1 | Filter percentage (100 = new) |
| 15, 20, 25 | 1 each | Unknown (observed: 8, repeating) |
| 30 | 1 | Unknown (observed: 44) |
| 31-181 | 151 | All zeros |

### 8.3 Schedule (type 0x02) Full Byte Map

| Offset | Size | Description |
|--------|------|-------------|
| 0-1 | 2 | Magic `a5b6` |
| 2 | 1 | Type `0x02` |
| 4-7 | 4 | Device ID (LE) |
| 8-9 | 2 | Config flags? `0x04 0x01` |
| 10 | 1 | Unknown `0x03` |
| **11** | **1** | **Remote temperature (direct °C)** |
| 12 | 1 | Unknown `0x00` |
| **13** | **1** | **Remote humidity (direct %)** |
| 14 | 1 | Unknown `0x00` |
| 15 | 1 | Days bitmask? `0xff` = all days |
| 16+ | — | 11-byte repeating blocks with `0xff` markers |

### 8.4 All Packet Types

| Type | Length | Description |
|------|--------|-------------|
| `0x01` | 182 bytes | Device State (config + Remote sensor) |
| `0x02` | 182 bytes | Schedule (time slot configuration) |
| `0x03` | 182 bytes | Probe Sensors (current probe readings) |
| `0x23` | 182 bytes | Settings acknowledgment |
| `0x40` | 55 bytes | Schedule Config Write |
| `0x46` | 182 bytes | Schedule Config Response |
| `0x47` | 26 bytes | Schedule Query |
| `0x50` | varies | Holiday status (constant, not useful — use byte 43) |

### 8.5 Fan Speed Encoding

| 0x18 Value | Fan Speed | Indicator (byte 47) | ACH Factor |
|-----------|-----------|---------------------|------------|
| 0 | LOW | 104 (0x68) | × 0.36 |
| 1 | MEDIUM | 194 (0xC2) | × 0.45 |
| 2 | HIGH | 38 (0x26) | × 0.55 |

## 9. Open Questions & Unknown Fields

### Status Packet Unknowns

| Location | Observed Values | Hypothesis |
|----------|-----------------|------------|
| Bytes 5-7 | 0x68 0x25 0x40 | Constant per device, possibly device ID |
| Byte 57 | 11, 25, 28 | Varies with sensor |
| Byte 60 | 100-210 | Unknown |
| Bytes 60-180 | Mostly zeros | May contain version info |

### App Fields Not Located in BLE

| Field | App Value | Notes |
|-------|-----------|-------|
| Night ventilation boost/turbo heat | No | Separate from 30-min BOOST |
| Embedded software version | 6.1.001 | Likely in bytes 60-180 |
| Electronic/Software/Mechanical version | 1/1/2 | Likely in bytes 60-180 |
| Season | Cold | Probably derived from preheat_enabled |
| Type of preheating | Electric | Hardware info, may not be in BLE |
| Serial number | MPV2402568 | Stored locally in app, not transmitted |

### Open Questions

**SETTINGS packet (0x1a):**
- Bytes 7-10 carry a clock sync (day, hour, minute, second) during the phone's
  regular polling. Whether the same bytes serve a different purpose during
  config writes (summer limit changes, etc.) is not yet verified.
- Early captures contained SETTINGS byte pairs matching known airflow modes
  (0x19/0x0a=LOW, 0x28/0x15=MEDIUM, 0x07/0x30=HIGH). These do not appear
  in recent controlled captures where bytes 7-10 consistently carry clock
  sync data. They may be from a different SETTINGS sub-command (mode byte
  0x00/0x02 vs 0x06/0x07).

**Unknown REQUEST params:**
- Param 0x29: the phone sends this heavily after connecting (~65 times with
  value=1, preceded by one with value=0). Purpose unknown — device responds
  with TYPE_0x48 packets. May establish a "phone control" mode that enables
  0x18 to affect the fan motor.
- Param 0x05: seen occasionally (268 occurrences across all captures).

**DEVICE_STATE unknowns:**
- Byte 32: changes with mode (0x18), purpose unknown. Does not correlate
  with Remote temperature (byte stayed at 19 while app showed 17°C).
- Byte 48: shows value 2 when mode=2 (HIGH), value 1 when mode=0 or 1
  (LOW or MEDIUM). Purpose unknown.
- Byte 60: changes with every 0x18 transition, wide range of values.
  Purpose unknown.

**Special Modes:**
- Night Ventilation packet mapping and encoding
- Fixed Air Flow packet mapping and encoding

**Schedule:**
- Schedule Response (0x02) fields (bytes 8-10, 15) — marked with "?"
- Schedule Query (0x47) full structure — triggered by param 0x26 but purpose unclear

**Status/Sensors:**
- Bypass state encoding (weather dependent)
- PROBE_SENSORS bytes 4, 15, 20, 25, 30 — non-zero but purpose unknown
- Device State byte 57 — varies (11, 25, 28 observed)
- Device State byte 60 — values 100-210 observed, possibly humidity-related

**Responses:**
- Holiday Status (0x50) response structure — constant payload, not useful for state
- Settings Ack (0x23) — structure not documented

## 10. References

- [Implementation Status](implementation-status.md) — Feature implementation tracking for the library
- [Infineon AN91162 - Creating a BLE Custom Profile](https://www.infineon.com/dgdl/Infineon-AN91162_Creating_a_BLE_Custom_Profile-ApplicationNotes-v05_00-EN.pdf)
- [Implementation Speculation](implementation-speculation.md) — Analysis of likely firmware implementation based on Cypress PSoC-4-BLE demo code patterns
- [Infineon PSoC-4-BLE GitHub](https://github.com/Infineon/PSoC-4-BLE) — Demo projects that VisionAir firmware appears to be based on
