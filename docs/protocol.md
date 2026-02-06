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

### 4.1 Device State & Sensor Queries

#### Device State Request (type 0x10, param 0x03)

Requests the Device State packet (0x01) containing device config and Remote sensor data.

```
a5b6 10 00 05 03 00 00 00 00 16
     │     │              │  └─ checksum
     │     │              └──── zeros
     │     └───────────────── param 0x03 (DEVICE_STATE)
     └─────────────────────── type 0x10 (REQUEST)
```

#### Probe Sensors Request (type 0x10, param 0x07)

Requests the Probe Sensors packet (0x03) containing current probe readings.

```
a5b6 10 06 05 07 00 00 00 00 14
```

Returns current probe temperatures and humidity (not historical data despite vendor naming).

#### Sensor Select Request (type 0x10, param 0x18)

Requests fresh data for a specific sensor. Byte 7 selects which sensor:

| Byte 7 | Sensor | Packet |
|--------|--------|--------|
| 0x00 | Probe 2 (Air inlet) | `a5b610060518000000000b` |
| 0x01 | Probe 1 (Resistor outlet) | `a5b610060518000000010a` |
| 0x02 | Remote Control | `a5b6100605180000000209` |

The device responds with a DEVICE_STATE packet, but the response contains
**stale data from the previously-selected sensor**. The device switches
internally AFTER sending its response.

To get a fresh reading for the requested sensor, send a follow-up
Device State Request (param 0x03) and check that byte 34 (selector)
matches the requested sensor. Timing varies by sensor type:

| Sensor | Switch Speed | Notes |
|--------|-------------|-------|
| Probe 1, Probe 2 (wired) | Fast | Usually matches on 1st follow-up |
| Remote (RF) | Slow | Often needs 2-3 follow-up requests |

> **Important:** The PROBE_SENSORS packet (type 0x03) provides live
> Probe 1 and Probe 2 temperatures without sensor cycling. Only Remote
> temperature requires the sensor_select mechanism.

> **Verified (2026-02-05):** Re-analyzed captures confirming byte7 selects
> the sensor explicitly. The app sends requests in order 0→2→1 to refresh all sensors.

#### Full Data Request (type 0x10, param 0x06)

```
a5b6 10 06 05 06 00 00 00 00 15
```

This "get all data" request triggers the device to send a sequence of responses:
1. SETTINGS_ACK (type 0x23)
2. DEVICE_STATE (type 0x01) - device config + Remote sensor
3. SCHEDULE (type 0x02)
4. PROBE_SENSORS (type 0x03) - current probe readings

> **Discovered (2026-02-05):** Btsnoop analysis shows the VMI app uses this
> request heavily for polling. It's more efficient than separate DEVICE_STATE and
> PROBE_SENSORS requests since it gets all data in one request sequence.

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
| `0x04` | Special mode settings variant (legacy captures only; not observed in current Holiday workflow) |
| `0x05` | Schedule command |

**Airflow mode encoding (bytes 9-10):**

| Mode | Byte 9 | Byte 10 | Example Packet |
|------|--------|---------|----------------|
| LOW | 0x19 | 0x0a | `a5b61a06061a020210190a03` |
| MEDIUM | 0x28 | 0x15 | `a5b61a06061a020210281527` |
| HIGH | 0x07 | 0x30 | `a5b61a06061a020210073027` |

> **Note:** These byte values are internal device references, not m³/h values.
> See [Volume-Based Calculations](#72-volume-based-calculations) for actual airflow.
>
> **Hypothesis (medium confidence):** Based on Cypress PSoC patterns, these may be
> **PWM duty cycle pairs** for the fan motor. PSoC demo code uses similar two-value
> patterns for pulse-width modulation (e.g., `PRS_WritePulse0/1`). The lack of
> obvious mathematical relationship between values supports this — they're likely
> calibrated motor control values rather than computed from airflow.

#### Holiday Command (type 0x10, param 0x1a)

| Command | Packet | Description |
|---------|--------|-------------|
| Holiday 3 days | `a5b61006051a000000030a` | Set 3-day holiday |
| Holiday 7 days | `a5b61006051a000000070e` | Set 7-day holiday |
| Holiday OFF | `a5b61006051a0000000009` | Disable holiday |

Byte 9 carries the number of holiday days (0=OFF, 1-255=active). The device
reflects this value immediately in DEVICE_STATE byte 43 (`holiday_days`).

**Reading holiday status:** Use DEVICE_STATE byte 43, not the 0x50 response.
The 0x50 response (from `REQUEST` param `0x2c`) is constant and does not
reflect holiday state.

> Verified via controlled capture session `data/captures/issue12_final2_20260205_225506`.
> Byte 43 changes instantly to match the value sent and returns to 0 when cleared.

### 4.3 Special Modes

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

### 4.4 Schedule Commands

#### Schedule Config Write (type 0x40)

> **Experimental:** Observed in captures but not yet verified via e2e tests
> or controlled VMI app reverse engineering. Structure is high-confidence
> (ATT framing confirmed, XOR checksum valid), but behavioral details
> (e.g. device response, required preconditions) are unverified.

Writes schedule configuration to the device. Same slot encoding as the
Schedule Config response (type 0x46), but sent as a 55-byte command.

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
| 1 | Preheat temperature (°C), e.g., 0x10 = 16°C |
| 2 | Mode byte |

**Mode byte values:**

| Mode | Byte | Airflow |
|------|------|---------|
| Mode 1 | 0x28 (40) | LOW |
| Mode 2 | 0x32 (50) | MEDIUM |
| Mode 3 | ? | HIGH (not captured) |

**Example** (hour 1 set to MEDIUM, rest LOW):
```
a5b6 40 06 31 00 1028 1032 1028 1028 1028 1028 1028 1028
                  1032 1032 1032 1032 1032 1032 1032 1032
                  1032 1028 1028 1028 1028 1028 1028 77
```

> **Discovered (2026-02-06):** First observed in Feb 5 captures during
> schedule editing. Verified via ATT framing as a real command (written to
> handle 0x0013). XOR checksum confirmed valid.

#### Schedule Config Response (type 0x46)

> **Experimental:** Observed in captures but not yet verified via e2e tests.

The device's response containing current schedule configuration. Same slot
format as 0x40, padded to 182 bytes with zeros.

```
a5b6 46 06 31 00 <slot_data...> <checksum> <zero padding to 182 bytes>
```

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
| `0x01` | 182 bytes | Device State (config + Remote sensor) |
| `0x02` | 182 bytes | Schedule (time slot configuration) |
| `0x03` | 182 bytes | Probe Sensors (current probe readings) |
| `0x23` | 182 bytes | Settings acknowledgment |
| `0x40` | 55 bytes | Schedule Config Write (experimental) |
| `0x46` | 182 bytes | Schedule Config Response (experimental) |
| `0x47` | 26 bytes | Schedule Query (experimental) |
| `0x50` | varies | Holiday status (constant, not useful — use byte 43) |

### 5.1 Device State Packet (type 0x01)

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
| 35 | 1 | Probe 1 temperature (°C) — **often stale** | 16 |
| 38 | 1 | Summer limit temp threshold (°C) | 26 |
| 42 | 1 | Probe 2 temperature (°C) — **often stale** | 11 |
| 43 | 1 | Holiday days remaining | 0=OFF, N=days |
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

### 5.3 Probe Sensors Packet (type 0x03)

Contains current/live probe readings. Despite vendor documentation calling this "HISTORY",
it contains current measurements, not historical data.

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

> **Note:** This packet does NOT contain Remote sensor data. Remote temperature
> is only available in the Device State packet (byte 32 when selector=2).
> Remote humidity is always in Device State byte 4. Full hex dump confirmed
> no Remote temperature or humidity values present in bytes 14-181.

## 6. Sensor Data Architecture

There is no single packet that contains all sensor temperatures. Data is split
across two packet types by sensor connectivity:

| Reading | Source | Packet | Notes |
|---------|--------|--------|-------|
| Probe 1 temperature | Wired | PROBE_SENSORS byte 6 | Always live |
| Probe 1 humidity | Wired | PROBE_SENSORS byte 8 | Always live |
| Probe 2 temperature | Wired | PROBE_SENSORS byte 11 | Always live |
| Remote humidity | RF | DEVICE_STATE byte 4 | Always present |
| Remote temperature | RF | DEVICE_STATE byte 32 | **Only when selector (byte 34) = 2** |

The wired probes (Probe 1 = outlet, Probe 2 = inlet) are always available
in the PROBE_SENSORS packet. The Remote sensor communicates via RF and its
temperature is only available in the DEVICE_STATE packet when the device's
internal sensor selector is pointing at it.

### Getting All Readings

To collect all sensor readings, the recommended approach is:

1. Send **Probe Sensors Request** (param 0x07) → Probe 1/2 temps + Probe 1 humidity
2. Send **Sensor Select** (param 0x18, sensor 2) → Switch to Remote
3. Send **Device State Request** (param 0x03) → Remote temp (byte 32 when selector=2) + Remote humidity (byte 4)

The handler should collect all notifications without filtering by type, since
the device has limited notification throughput through BLE proxies. See
`VisionAirClient.get_fresh_status()` for the implementation.

> **Note:** The Device State packet also contains Probe 1/2 temperatures at
> bytes 35 and 42, but these are often stale. Use PROBE_SENSORS for reliable
> probe readings.

## 7. Data Encoding Reference

### 7.1 Airflow Modes

The protocol supports three discrete airflow modes. The byte pairs in settings commands are internal device references:

| Mode | Settings Bytes | Status Indicator |
|------|---------------|------------------|
| LOW | 0x19, 0x0A | 38 (0x26) |
| MEDIUM | 0x28, 0x15 | 104 (0x68) |
| HIGH | 0x07, 0x30 | 194 (0xC2) |

### 7.2 Volume-Based Calculations

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

### 7.3 Holiday Mode Encoding

Holiday control uses `REQUEST` (type `0x10`) with param `0x1a`:

| Packet | Meaning |
|--------|---------|
| `a5b61006051a000000NNCC` | Holiday command (`NN` = days, `CC` = checksum) |

Where:
- `0x10` packet type (`REQUEST`), `0x06` extended format
- Request param `0x1a` in byte 5
- Byte 9 = holiday days (0=OFF, 1-255=active)

Read back: DEVICE_STATE byte 43 contains the current holiday days value.
The `0x50` response from holiday status query (param `0x2c`) is constant
and should not be used for state monitoring.

## 8. Library

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
- Night Ventilation packet mapping and encoding
- Fixed Air Flow packet mapping and encoding

**Schedule:**
- Schedule Mode 3 (HIGH) byte value — not captured
- Schedule Response fields (bytes 8-10, 15) — marked with "?"
- How to enable/disable "Activating time slots" toggle

**Status/Sensors:**
- Bypass state encoding (weather dependent)
- What do airflow setting bytes actually represent (PWM? calibration index?)
- PROBE_SENSORS bytes 4, 15, 20, 25, 30 — non-zero but purpose unknown
- Device State byte 57 — varies with sensor (11, 25, 28 observed)
- Device State byte 60 — values 100-210 observed, possibly humidity-related

**Responses:**
- Holiday Status (0x50) response structure — constant payload, not useful for state
- Settings Ack (0x23) — structure not documented

## Appendix B: References

- [Infineon AN91162 - Creating a BLE Custom Profile](https://www.infineon.com/dgdl/Infineon-AN91162_Creating_a_BLE_Custom_Profile-ApplicationNotes-v05_00-EN.pdf)
- [Implementation Speculation](implementation-speculation.md) — Analysis of likely firmware implementation based on Cypress PSoC-4-BLE demo code patterns
- [Infineon PSoC-4-BLE GitHub](https://github.com/Infineon/PSoC-4-BLE) — Demo projects that VisionAir firmware appears to be based on
