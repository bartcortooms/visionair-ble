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

## 2. BLE Interface

The device uses Cypress PSoC demo profile UUIDs (vendor reused generic UUIDs).

### Services

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

## 3. Packet Format

All packets use:
- **Magic prefix:** `0xa5 0xb6`
- **Checksum:** XOR of all bytes after prefix (excluding checksum byte itself)

### Checksum Calculation

XOR all payload bytes (everything between magic prefix and checksum).

**Example:** `a5b6 10 00 05 03 00 00 00 00 16`
- Payload: `10 00 05 03 00 00 00 00`
- Checksum: `0x10 ^ 0x00 ^ 0x05 ^ 0x03 ^ 0x00 ^ 0x00 ^ 0x00 ^ 0x00` = `0x16`

## 4. Commands Reference

Commands are written to characteristic handle 0x0013.

### 4.1 Status & Sensor Queries

#### Status Request (type 0x10, param 0x03)

```
a5b6 10 00 05 03 00 00 00 00 16
     │     │              │  └─ checksum
     │     │              └──── zeros
     │     └───────────────── param 0x03
     └─────────────────────── type 0x10
```

#### History Request (type 0x10, param 0x07)

```
a5b6 10 06 05 07 00 00 00 00 14
```

Returns history packet with Probe 1 humidity.

#### Sensor Select Request (type 0x10, param 0x18)

Requests fresh data for a specific sensor. Byte 7 selects which sensor:

| Byte 7 | Sensor | Packet |
|--------|--------|--------|
| 0x00 | Probe 2 (Air inlet) | `a5b610060518000000000b` |
| 0x01 | Probe 1 (Resistor outlet) | `a5b610060518000000010a` |
| 0x02 | Remote Control | `a5b6100605180000000209` |

The response's sensor selector (byte 34) matches the requested sensor, and
byte 32 contains the fresh temperature for that sensor.

To get fresh readings for all sensors, send all three requests in sequence.

> **Verified (2026-02-05):** Re-analyzed captures confirming byte7 selects
> the sensor explicitly. The app sends requests in order 0→2→1 to refresh all sensors.

#### Full Data Request (type 0x10, param 0x06)

```
a5b6 10 06 05 06 00 00 00 00 15
```

This "get all data" request triggers the device to send a sequence of responses:
1. SETTINGS_ACK (type 0x23)
2. STATUS (type 0x01)
3. SCHEDULE (type 0x02)
4. SENSOR/HISTORY (type 0x03)

> **Discovered (2026-02-05):** Btsnoop analysis shows the VMI app uses this
> request heavily for polling. It's more efficient than separate STATUS and
> HISTORY requests since it gets all data in one request sequence.

### 4.2 Device Control

#### BOOST Command (type 0x10, param 0x19)

| Command | Packet | Description |
|---------|--------|-------------|
| BOOST ON | `a5b610060519000000010b` | Enable 30-min BOOST |
| BOOST OFF | `a5b610060519000000000a` | Disable BOOST |

#### Settings Command (type 0x1a)

Structure: `a5b6 1a 06 06 1a <preheat> <mode> <temp> <af1> <af2> <checksum>`

| Offset | Size | Description |
|--------|------|-------------|
| 0-1 | 2 | Magic `a5b6` |
| 2 | 1 | Type `0x1a` |
| 3-5 | 3 | Header `06 06 1a` |
| 6 | 1 | Preheat enabled: `0x02`=ON, `0x00`=OFF |
| 7 | 1 | Mode byte (see below) |
| 8 | 1 | Preheat temperature (°C) |
| 9 | 1 | Airflow byte 1 |
| 10 | 1 | Airflow byte 2 |
| 11 | 1 | XOR checksum |

**Mode byte (offset 7) values:**

| Value | Meaning |
|-------|---------|
| `0x00` | Normal settings (summer limit OFF) |
| `0x02` | Normal settings (summer limit ON) |
| `0x04` | Special Mode command (Holiday/Night Vent/Fixed Air) |
| `0x05` | Schedule command |

**Airflow mode encoding (bytes 9-10):**

| Mode | Byte 9 | Byte 10 | Example Packet |
|------|--------|---------|----------------|
| LOW | 0x19 | 0x0a | `a5b61a06061a020210190a03` |
| MEDIUM | 0x28 | 0x15 | `a5b61a06061a020210281527` |
| HIGH | 0x07 | 0x30 | `a5b61a06061a020210073027` |

> **Note:** These byte values are internal device references, not m³/h values.
> See [Volume-Based Calculations](#62-volume-based-calculations) for actual airflow.
>
> **Hypothesis (medium confidence):** Based on Cypress PSoC patterns, these may be
> **PWM duty cycle pairs** for the fan motor. PSoC demo code uses similar two-value
> patterns for pulse-width modulation (e.g., `PRS_WritePulse0/1`). The lack of
> obvious mathematical relationship between values supports this — they're likely
> calibrated motor control values rather than computed from airflow.

### 4.3 Special Modes

> **⚠️ EXPERIMENTAL:** These features have significant gaps in protocol understanding.
> See [Open Questions](#open-questions) for details. Use with caution.

All special modes use the Settings Command with byte 7 = `0x04`. Bytes 8-9-10 encode an HH:MM:SS timestamp.

**Why timestamps? (high confidence):** The PSoC BLE chip lacks a battery-backed RTC — it uses a
Watchdog Timer for timekeeping which resets on power loss. The timestamp likely serves to:
1. Sync the device's internal clock with the app
2. Provide a reference point for calculating mode expiration

**Mode differentiation hypothesis (medium confidence):** Holiday, Night Ventilation, and Fixed Air
Flow all send identical `0x04` packets. Based on PSoC's event-driven state machine pattern, the
device likely uses **preceding query packets** to select which mode to activate:
- Query `0x1a` (days) → selects Holiday mode
- Query `0x1b` → may select Fixed Air Flow mode (one capture observed)
- Unknown query → may select Night Ventilation mode

The `0x04` command then activates whatever mode was most recently selected.

#### Holiday Mode

**What we know:**
- Activation sequence involves days query followed by Settings 0x04 command
- Days query sets the duration
- Activation command includes current time as HH:MM:SS

**What we DON'T know:**
- How to deactivate/cancel Holiday mode (no OFF packets captured)
- Whether the days value persists or needs to be sent every time
- How the device reports remaining Holiday time

**Activation sequence (observed):**

1. **Set days** — Query 0x1a with days value:
   ```
   a5b6 10 06 05 1a 00 00 00 <days> <checksum>
   ```

2. **Activate** — Settings command with current time:
   ```
   a5b6 1a 06 06 1a <preheat> 04 <hour> <min> <sec> <checksum>
   ```

**Days query examples:**

| Days | Packet |
|------|--------|
| 3 | `a5b61006051a000000030a` |
| 7 | `a5b61006051a000000070e` |
| 14 | `a5b61006051a0000000e07` |

**Holiday status query (param 0x2c):**
```
a5b6 10 06 05 2c 00 00 00 00 3f
```

Returns type 0x50 response (structure not yet decoded).

#### Night Ventilation Boost

**What we know:**
- Uses the same packet structure as Holiday mode (byte 7 = `0x04`, bytes 8-9-10 = HH:MM:SS)

**What we DON'T know:**
- How the device distinguishes this from Holiday mode — packets appear identical
- Whether a preceding query is required to select this mode
- How to deactivate it

#### Fixed Air Flow Rate

**What we know:**
- Uses the same packet structure as Holiday mode (byte 7 = `0x04`, bytes 8-9-10 = HH:MM:SS)

**What we DON'T know:**
- How the device distinguishes this from Holiday mode — packets appear identical
- Whether a preceding query is required to select this mode
- How to deactivate it
- What airflow rate it uses (the current mode? a specific rate?)

### 4.4 Schedule Commands

#### Schedule Config (type 0x46)

```
a5b6 46 06 31 00 <slot_data...>
```

Contains 24 time slots (2 bytes each):

| Byte | Description |
|------|-------------|
| 1 | Preheat temperature (°C), e.g., 0x10 = 16°C |
| 2 | Mode byte |

**Mode byte values:**

| Mode | Byte | Airflow |
|------|------|---------|
| Mode 1 | 0x28 (40) | LOW |
| Mode 2 | 0x32 (50) | MEDIUM |
| Mode 3 | ? | HIGH (not captured) |

#### Schedule Query (type 0x47)

```
a5b6 47 06 18 00 08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 51
```

Query or acknowledgment packet for schedule operations.

## 5. Response Reference

Responses arrive as notifications on characteristic handle 0x000e. Subscribe by writing `0x0100` to CCCD handle 0x000f.

### Packet Types

| Type | Length | Description |
|------|--------|-------------|
| `0x01` | 182 bytes | Status response |
| `0x02` | 182 bytes | Schedule data |
| `0x03` | 182 bytes | History data |
| `0x23` | 182 bytes | Settings acknowledgment |
| `0x46` | varies | Schedule config data |
| `0x50` | varies | Holiday status |

### 5.1 Status Response (type 0x01)

| Offset | Size | Description | Example |
|--------|------|-------------|---------|
| 0-1 | 2 | Magic | `a5b6` |
| 2 | 1 | Type | `0x01` |
| 4 | 1 | Remote humidity (%) | 55 |
| 5-7 | 3 | Unknown (constant per device) | `68 25 40` |
| 8 | 1 | **Unknown** - always 18, not live temp | 18 |
| 22-23 | 2 | Configured volume (m³) (LE u16) | 363 |
| 26-27 | 2 | Operating days (LE u16) | 634 |
| 28-29 | 2 | Filter life days (LE u16) | 330 |
| 32 | 1 | **Live temperature** for selected sensor (see byte 34) | 19 |
| 34 | 1 | Sensor selector | 0/1/2 |
| 35 | 1 | Probe 1 temperature (°C) | 16 |
| 38 | 1 | Summer limit temp threshold (°C) | 26 |
| 42 | 1 | Probe 2 temperature (°C) | 11 |
| 44 | 1 | BOOST active | 0=OFF, 1=ON |
| 47 | 1 | Airflow indicator | 38/104/194 |
| 48 | 1 | Airflow mode | 1=MID/MAX, 2=MIN |
| 49 | 1 | Preheat enabled | `0x02`=ON |
| 50 | 1 | Summer limit enabled | `0x02`=ON |
| 54 | 1 | Diagnostic status bitfield | `0x0F`=all OK |
| 56 | 1 | Preheat temperature (°C) | 16 |

#### Sensor Selector (byte 34)

| Value | Sensor |
|-------|--------|
| 0 | Probe 2 (Air inlet) |
| 1 | Probe 1 (Resistor outlet) |
| 2 | Remote Control |

#### Airflow Indicator (byte 47)

| Value | Mode | ACH Factor |
|-------|------|------------|
| 38 (0x26) | LOW | × 0.36 |
| 104 (0x68) | MEDIUM | × 0.45 |
| 194 (0xC2) | HIGH | × 0.55 |

> **Note:** Like the settings bytes, these values have no obvious mathematical relationship.
> They may be internal state identifiers or PWM-related values. Use the ACH factors with the
> configured volume to calculate actual m³/h.

#### Diagnostic Status Bitfield (byte 54)

| Bit | Value | Component |
|-----|-------|-----------|
| 0 | 1 | IAQ Sensor |
| 1 | 2 | Motor |
| 2 | 4 | Pre-heating |
| 3 | 8 | Probes |

Value `0x0F` (all bits set) indicates all components healthy.

> **Note:** Bit-to-component mapping is assumed based on UI display order. Only value 0x0F (all healthy) has been observed.

### 5.2 Schedule Response (type 0x02)

Reports current time and schedule state.

| Offset | Size | Description |
|--------|------|-------------|
| 0-1 | 2 | Magic `a5b6` |
| 2 | 1 | Type `0x02` |
| 4-7 | 4 | Device ID (LE) |
| 8-9 | 2 | Config flags? `0x04 0x01` |
| 10 | 1 | Mode? `0x03` |
| 11 | 1 | Current hour (0-23) |
| 13 | 1 | Current minute (0-59) |
| 15 | 1 | Days bitmask? `0xff` = all days |
| 16+ | — | 11-byte repeating blocks with `0xff` markers |

The app's "Time slot configuration" UI shows:
- 24 hourly slots (0h-23h)
- Each slot: preheat temp (°C) and mode (1/2/3 = airflow level)
- Per-day or default configuration
- "Activating time slots" toggle

### 5.3 History Response (type 0x03)

| Offset | Size | Description |
|--------|------|-------------|
| 8 | 1 | Probe 1 humidity (direct %) |
| 13 | 1 | Filter percentage (100 = new) |

## 6. Data Encoding Reference

### 6.1 Airflow Modes

The protocol supports three discrete airflow modes. The byte pairs in settings commands are internal device references:

| Mode | Settings Bytes | Status Indicator |
|------|---------------|------------------|
| LOW | 0x19, 0x0A | 38 (0x26) |
| MEDIUM | 0x28, 0x15 | 104 (0x68) |
| HIGH | 0x07, 0x30 | 194 (0xC2) |

### 6.2 Volume-Based Calculations

Actual airflow (m³/h) depends on the configured volume (bytes 22-23 in status response):

```
LOW    = volume × 0.36 ACH
MEDIUM = volume × 0.45 ACH
HIGH   = volume × 0.55 ACH
```

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

### 6.3 Special Mode Timestamp Encoding

Special mode commands (byte 7 = 0x04) encode the current time in bytes 8-9-10:

| Byte | Value |
|------|-------|
| 8 | Hour (0-23) |
| 9 | Minute (0-59) |
| 10 | Second (0-59) |

## 7. Library

See [implementation-status.md](implementation-status.md) for feature implementation tracking.

## Appendix A: Unknown Fields

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

**Special Modes:**
- How does the device distinguish Holiday vs Night Vent vs Fixed Air Flow modes?
  - *Partial answer:* Likely via preceding query packets (state machine). See [Special Modes](#43-special-modes).
- How to explicitly deactivate special modes (toggle OFF behavior)?
- Does Holiday mode require the days query every time, or is it stored?
  - *Hypothesis:* Probably needs to be sent each time — PSoC examples don't show persistent state storage for such values.

**Schedule:**
- Schedule Mode 3 (HIGH) byte value — not captured
- Schedule Response fields (bytes 8-10, 15) — marked with "?"
- How to enable/disable "Activating time slots" toggle

**Status/Sensors:**
- Sensor Cycle Request behavior — needs re-verification against captures
- Bypass state encoding (weather dependent)
- What do airflow setting bytes actually represent (PWM? calibration index?)

**Responses:**
- Holiday Status (0x50) response structure — not decoded
- Settings Ack (0x23) — structure not documented

## Appendix B: References

- [Infineon AN91162 - Creating a BLE Custom Profile](https://www.infineon.com/dgdl/Infineon-AN91162_Creating_a_BLE_Custom_Profile-ApplicationNotes-v05_00-EN.pdf)
- [Implementation Speculation](implementation-speculation.md) — Analysis of likely firmware implementation based on Cypress PSoC-4-BLE demo code patterns
- [Infineon PSoC-4-BLE GitHub](https://github.com/Infineon/PSoC-4-BLE) — Demo projects that VisionAir firmware appears to be based on
