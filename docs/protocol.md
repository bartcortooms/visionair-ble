# VisionAir BLE Protocol Specification

This document describes the BLE GATT protocol used by Ventilairsec VisionAir (Vision'R range) ventilation devices, reverse-engineered for interoperability purposes.

> **Disclaimer:** This is unofficial documentation created through reverse engineering. This project is not affiliated with, endorsed by, or connected to Ventilairsec, Purevent, VisionAir, or any related companies. All product names and trademarks are the property of their respective owners.

## Supported Devices

All devices in the Vision'R range advertise as "VisionAir" over BLE:

| Model | Hardware Max | Status |
|-------|-------------|--------|
| **Purevent Vision'R** | 350 m³/h | ✅ Tested |
| **Urban Vision'R** | 201 m³/h | ⚠️ Untested |
| **Cube Vision'R** | ? | ⚠️ Untested |

## Device Information

| Property | Value |
|----------|-------|
| BLE Name | `VisionAir` |
| MAC Prefix | `00:A0:50` |
| Chip | Cypress Semiconductor (PSoC BLE) |

## BLE Services

The device uses Cypress PSoC demo profile UUIDs (vendor reused generic UUIDs):

| Service UUID | Purpose |
|-------------|---------|
| `0003cab5-0000-1000-8000-00805f9b0131` | Data Service |
| `0003cbbb-0000-1000-8000-00805f9b0131` | Control Service |

### Characteristics

| UUID | Handle | Properties | Purpose |
|------|--------|------------|---------|
| `0003caa2-...` | 0x000e | Notify | Status notifications (device → app) |
| `0003cbb1-...` | 0x0013 | Write | Commands (app → device) |

## Packet Format

All packets use:
- **Magic prefix:** `0xa5 0xb6`
- **Checksum:** XOR of all bytes after prefix (excluding checksum byte itself)

### Checksum Calculation

```python
def calc_checksum(payload: bytes) -> int:
    """XOR all bytes in payload."""
    result = 0
    for b in payload:
        result ^= b
    return result

def build_packet(payload: bytes) -> bytes:
    """Build packet with magic prefix and checksum."""
    checksum = calc_checksum(payload)
    return b'\xa5\xb6' + payload + bytes([checksum])
```

## Commands (Write to 0x0013)

### Status Request (type 0x10)

```
a5b6 10 00 05 03 00 00 00 00 16
     │     │              │  └─ checksum
     │     │              └──── zeros
     │     └───────────────── param 0x03
     └─────────────────────── type 0x10
```

### History Request (type 0x10)

```
a5b6 10 06 05 07 00 00 00 00 14
```

Returns history packet with Probe 1 humidity.

### BOOST Command (type 0x10, param 0x19)

| Command | Packet | Description |
|---------|--------|-------------|
| BOOST ON | `a5b610060519000000010b` | Enable 30-min BOOST |
| BOOST OFF | `a5b610060519000000000a` | Disable BOOST |

### Settings Command (type 0x1a)

Structure: `a5b6 1a 06 06 1a <preheat> <summer> <temp> <af1> <af2> <checksum>`

| Offset | Size | Description |
|--------|------|-------------|
| 0-1 | 2 | Magic `a5b6` |
| 2 | 1 | Type `0x1a` |
| 3-5 | 3 | Header `06 06 1a` |
| 6 | 1 | Preheat enabled: `0x02`=ON, `0x00`=OFF |
| 7 | 1 | Summer limit: `0x02`=ON, `0x00`=OFF |
| 8 | 1 | Preheat temperature (°C) |
| 9 | 1 | Airflow byte 1 |
| 10 | 1 | Airflow byte 2 |
| 11 | 1 | XOR checksum |

#### Airflow Mode Encoding

The protocol supports exactly **three discrete airflow modes** (LOW, MEDIUM, HIGH). Arbitrary m³/h values cannot be sent—the device only accepts these specific byte combinations:

| Mode | Byte 9 | Byte 10 | Complete Packet (16°C preheat) |
|------|--------|---------|-------------------------------|
| LOW | 0x19 | 0x0a | `a5b61a06061a020210190a03` |
| MEDIUM | 0x28 | 0x15 | `a5b61a06061a020210281527` |
| HIGH | 0x07 | 0x30 | `a5b61a06061a020210073027` |

> **Note:** These byte values are internal device references (likely fan PWM or calibration indices), not m³/h values. The actual airflow in m³/h is calculated from the configured volume (see [Volume-Dependent Airflow Configuration](#volume-dependent-airflow-configuration)).

## Notifications (From 0x000e)

Subscribe by writing `0x0100` to CCCD handle 0x000f.

### Packet Types

| Type | Length | Description |
|------|--------|-------------|
| `0x01` | 182 bytes | Status response |
| `0x02` | 182 bytes | Schedule data |
| `0x03` | 182 bytes | History data |
| `0x23` | 182 bytes | Settings acknowledgment |

### Status Response (type 0x01)

| Offset | Size | Description | Example | Verified |
|--------|------|-------------|---------|----------|
| 0-1 | 2 | Magic | `a5b6` | ✓ |
| 2 | 1 | Type | `0x01` | ✓ |
| 4-7 | 4 | Device ID (LE) | `37682540` | ✓ |
| 5 | 1 | Remote humidity raw (÷2 = %) | 104 → 52% | ✓ |
| 8 | 1 | Remote temperature (°C) | 18 | ✓ |
| **22-23** | 2 | **Configured volume (m³)** (LE u16) | 363 | ✓ App confirms |
| 26-27 | 2 | Operating days (LE u16) | 634 | ✓ App confirms |
| 28-29 | 2 | Filter life days (LE u16) | 330 | ✓ App confirms |
| 34 | 1 | Sensor selector | 0/1/2 | ✓ |
| 35 | 1 | Probe 1 temperature (°C) | 16 | ✓ |
| **38** | 1 | **Summer limit temp threshold (°C)** | 26 | ✓ NEW |
| 42 | 1 | Probe 2 temperature (°C) | 11 | ✓ |
| 44 | 1 | BOOST active | 0=OFF, 1=ON | ✓ |
| 47 | 1 | Airflow indicator | 38/104/194 | ✓ |
| 48 | 1 | Airflow mode | 1=MID/MAX, 2=MIN | ✓ |
| 49 | 1 | Preheat enabled | `0x02`=ON | ✓ |
| 50 | 1 | Summer limit enabled | `0x02`=ON | ✓ |
| 56 | 1 | Preheat temperature (°C) | 16 | ✓ |

> **App verification (2026-02):** Equipment Life screen confirmed volume=363m³, operating days=634, filter life=330 days. "Theoretical air flow" shown as 131 m³/h matches LOW mode calculation (363 × 0.36).

#### Airflow Indicator Mapping (byte 47)

| Value | Mode | Calculation |
|-------|------|-------------|
| 38 (0x26) | LOW | volume × 0.36 ACH |
| 104 (0x68) | MEDIUM | volume × 0.45 ACH |
| 194 (0xC2) | HIGH | volume × 0.55 ACH |

> **Note:** These indicator values are internal state identifiers. To get the actual m³/h, read the configured volume from bytes 22-23 and apply the ACH multiplier.

#### Sensor Selector (byte 34)

| Value | Sensor |
|-------|--------|
| 0 | Probe 2 (Air inlet) |
| 1 | Probe 1 (Resistor outlet) |
| 2 | Remote Control |

### History Response (type 0x03)

| Offset | Size | Description |
|--------|------|-------------|
| 8 | 1 | Probe 1 humidity (direct %) |
| 13 | 1 | Filter percentage (100 = new) |

## Connection Sequence

1. Scan for device (name "VisionAir" or MAC prefix `00:A0:50`)
2. Connect
3. Discover services
4. Enable notifications: write `0x0100` to handle 0x000f
5. Send status request: write `a5b6100005030000000016` to handle 0x0013
6. Receive status notification on handle 0x000e

## Notes

- Only one BLE connection at a time - disconnect other clients first
- The device uses Cypress PSoC BLE demo profile UUIDs (not custom)
- Serial number is NOT transmitted over BLE (stored locally in app)
- BOOST mode auto-deactivates after 30 minutes

## Volume-Dependent Airflow Configuration

> **Important:** The airflow values documented here (131, 164, 201 m³/h) are believed to be **installation-specific**, not universal device constants.

### Background

During professional installation, the installer uses a special "installer mode" in the mobile application to configure the ventilation system. This configuration includes the **volume of the ventilated space** (in m³). The device then calculates appropriate airflow rates based on standard ventilation requirements (air changes per hour).

### Evidence

1. **Non-round values**: The specific values 131, 164, 201 m³/h suggest calculation rather than arbitrary defaults.

2. **Hardware vs configured limits**: The test device (Purevent Vision'R) has a hardware maximum of 350 m³/h, but shows MAX=201 m³/h—confirming values are calculated based on home volume, not hardware limits.

3. **Opaque byte encoding**: The mapping from airflow to protocol bytes shows no obvious mathematical relationship:
   - 131 m³/h → `0x19, 0x0A` (25, 10 decimal)
   - 164 m³/h → `0x28, 0x15` (40, 21 decimal)
   - 201 m³/h → `0x07, 0x30` (7, 48 decimal)

   This suggests these bytes are device-internal references (fan PWM values, calibration indices, etc.) specific to the configured volume.

4. **Status indicator is also opaque**: Byte 47 values (38, 104, 194) don't linearly map to m³/h, suggesting they're internal state values meaningful only with calibration context.

### Model Specifications

| Model | Hardware Max | Target Use | Max Surface |
|-------|-------------|------------|-------------|
| **Urban Vision'R** | 201 m³/h | Apartments, studios | ~100 m² |
| **Purevent Vision'R** | 350 m³/h | Houses | 250-300 m² |
| **Pro 1000** | 1000 m³/h | Commercial | Large buildings |

### Sizing Calculation

VMI systems are typically sized for **~0.5 air changes per hour (ACH)** in renovation contexts.

**Formula:** `Configured airflow = Home volume × 0.5 ACH`

**Example (test device):**
- MAX airflow: 201 m³/h
- Estimated volume: 201 ÷ 0.5 = **~400 m³**
- Estimated surface: 400 ÷ 2.5m ceiling = **~160 m²**

The three airflow levels represent different ACH rates:

| Level | Airflow | ACH (for ~400 m³) |
|-------|---------|-------------------|
| LOW | 131 m³/h | ~0.33 |
| MEDIUM | 164 m³/h | ~0.41 |
| HIGH | 201 m³/h | ~0.50 |

### Volume Field Discovered

**Status packet bytes 22-23 contain the configured volume in m³** (little-endian uint16).

The app calculates the actual m³/h values by multiplying the volume by ACH factors:

```
LOW    = volume × 0.36 ACH
MEDIUM = volume × 0.45 ACH
HIGH   = volume × 0.55 ACH
```

Example (test device with volume = 363 m³):
- LOW: 363 × 0.36 = 131 m³/h ✓
- MEDIUM: 363 × 0.45 = 163 m³/h ≈ 164 ✓
- HIGH: 363 × 0.55 = 200 m³/h ≈ 201 ✓

> **App terminology:** The app's "Equipment Life" screen displays "Theoretical air flow" which is the **LOW mode** value (volume × 0.36 ACH). This represents the base ventilation rate, not the current operating mode.

### Implications for This Library

The library reads the configured volume from the device and calculates the actual m³/h values:

```python
status = await purevent.get_status()
print(f"Volume: {status.configured_volume} m³")
print(f"LOW: {status.airflow_low} m³/h")
print(f"MEDIUM: {status.airflow_medium} m³/h")
print(f"HIGH: {status.airflow_high} m³/h")
print(f"Current: {status.airflow} m³/h ({status.airflow_mode})")
```

The protocol constants `AIRFLOW_LOW`, `AIRFLOW_MEDIUM`, `AIRFLOW_HIGH` (131, 164, 201) are used as protocol identifiers for the settings packet byte mappings, not as actual m³/h values.

**Key insight:** The settings packet byte pairs (0x19/0x0A, 0x28/0x15, 0x07/0x30) appear to be universal mode identifiers—they select LOW/MEDIUM/HIGH mode regardless of the configured volume. The device firmware then applies the appropriate airflow based on its calibration.

## Undocumented Fields

The following fields are observed but not fully decoded:

| Location | Values | Hypothesis | Related Issue |
|----------|--------|------------|---------------|
| Status byte 57 | 11, 25, 28 | Unknown, varies with sensor | |
| Status byte 60 | 100-210 | Context-dependent humidity | |
| Status bytes 60-180 | Mostly zeros | May contain version info (see below) | #10 |
| Unknown | ? | Night ventilation boost/turbo heat setting | #7 |
| Schedule packets | Type 0x46, 0x47 | Time slot configuration | #3 |

### App-reported fields not yet located in BLE packets

From the app's "Equipment Life" screen:

| Field | Value | Notes |
|-------|-------|-------|
| Max. supply air temp. | 26°C | ✓ DECODED: byte 38 (summer_limit_temp) |
| Night ventilation boost/turbo heat | No | Separate from 30-min BOOST (#7) |
| Embedded software version | 6.1.001 | Somewhere in bytes 60-180 (#10) |
| Electronic/Software/Mechanical version | 1/1/2 | Somewhere in bytes 60-180 (#10) |
| Season | Cold | Likely derived from preheat_enabled |
| Type of preheating | Electric | Hardware info, may not be in BLE |
| Serial number | MPV2402568 | NOT in BLE (stored locally in app) |

> **Research opportunity:** Capturing packets while using time slot scheduling, holiday mode, or diagnostic features would help decode the remaining protocol.

### Holiday Mode (Issue #3)

Captured during Holiday mode toggle testing (2026-02-04).

**Command sequence for Holiday mode toggle:**
1. Query 0x2c is sent first (fetch Holiday status)
2. Settings packet with byte 7 = 0x04 (Holiday mode command)

**Query 0x2c - Holiday Status Request:**
```
a5b6 10 06 05 2c 00 00 00 00 3f
             ^^ param 0x2c (44)
```
Sent before each Holiday mode toggle. Returns type 0x50 response.

**Holiday Mode Settings Command (byte 7 = 0x04):**
```
Structure: a5b6 1a 06 06 1a <preheat> 04 <days?> <p1> <p2> <checksum>
                            ^^^^^^^^ ^^ ^^^^^^^ ^^^^^^^^
                            byte6    byte7=0x04  parameters
```

| Field | Holiday ON | Holiday OFF | Notes |
|-------|------------|-------------|-------|
| Byte 6 | 0x02 | 0x02 | Preheat enabled |
| Byte 7 | **0x04** | **0x04** | Holiday mode command type |
| Byte 8 | 0x0b (11) | 0x0c (12) | Duration in days? |
| Byte 9 | 0x1b (27) | 0x2a (42) | Unknown parameter |
| Byte 10 | 0x30 (48) | 0x1e (30) | Unknown parameter |

**Captured packets:**
- Holiday ON:  `a5b61a06061a02040b1b3026`
- Holiday OFF: `a5b61a06061a02040c2a1e3e`

**Key insight:** Byte 7 = 0x04 identifies Holiday mode commands (vs normal settings where byte 7 is 0x00 or 0x02 for summer limit). The actual ON/OFF state appears to be encoded in bytes 8-10.

**Needs further research:**
- Determine exact meaning of bytes 8-10 (days duration, mode flags?)
- Test with explicit days values to confirm byte 8 = days
- Find Holiday mode indicator in status packet

## References

- [Infineon AN91162 - Creating a BLE Custom Profile](https://www.infineon.com/dgdl/Infineon-AN91162_Creating_a_BLE_Custom_Profile-ApplicationNotes-v05_00-EN.pdf)
