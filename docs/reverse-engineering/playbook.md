# VisionAir BLE Reverse Engineering Playbook

This playbook describes the methodology for capturing and analyzing BLE traffic from the VisionAir ventilation device to decode protocol fields.

## Prerequisites

- An Android phone with the official VMI+ installer app: `com.ventilairsec.ventilairsecinstallateur`
- ADB access to the phone (USB or WiFi)
- Ability to enable Bluetooth HCI snoop logging on the phone
- Optional: nRF Connect app for controlled GATT operations

## Environment Setup

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your device MAC, phone IP, etc.
```

## Enabling Bluetooth HCI Snoop Logging

**IMPORTANT:** For full packet captures, you must enable BT snoop logging in Developer Options with the correct mode. The `settings` command alone is not sufficient.

### Automated Setup

Run the following command to enable full BT snoop logging:

```bash
./scripts/capture/app_control.sh btsnoop-enable
```

This will:
1. Open Developer Options
2. Enable "Bluetooth HCI snoop log" with **"Enabled"** mode (not filtered)
3. Toggle Bluetooth off/on to apply the setting

### Manual Verification

If the automated command fails, verify manually:

1. Open **Settings → Developer Options**
2. Find **"Enable Bluetooth HCI snoop log"**
3. Select **"Enabled"** (NOT "Disabled", "Enabled Filtered", or other filtered modes)
4. Toggle Bluetooth off and on

**Note:** Without the correct mode, you'll get `btsnooz` format (truncated/filtered) instead of full `btsnoop` captures.

## Capture Discipline (Critical)

**Key principle:** Always record app-displayed values WITH timestamps so they can be correlated with specific packets.

### Interactive Capture Session (Recommended)

Use the interactive capture command for exploring protocol fields:

```bash
./scripts/capture/app_control.sh capture humidity_test
```

This starts an interactive session where you can:
- Type `c` (checkpoint) at any moment to record:
  - Precise ISO timestamp
  - Screenshot of current app screen
  - Manual entry of displayed values (temp, humidity, etc.)
- Type `s` (screenshot) to just take a screenshot
- Type `q` (quit) to end session and pull btsnoop logs

**Workflow example:**
```
capture> c
=== Checkpoint 1 at 2026-02-05T15:30:45+01:00 ===
Screenshot: checkpoint_1_153045.png
Enter values shown in app:
  Remote temp (°C): 19
  Remote humidity (%): 55
  Probe1 temp (°C): 16
  Probe1 humidity (%): 71
  ...
Checkpoint 1 saved.

capture> q
[pulls btsnoop logs]
```

**Analysis with checkpoints:**
```bash
python scripts/capture/extract_packets.py session/btsnoop.log \
    --checkpoints session/checkpoints.txt --window 10
```

This shows packets within ±10 seconds of each checkpoint, with their byte values alongside the recorded app values for easy correlation.

### Single-Action Runs (Original Method)

For targeted tests, each run should have **one UI change only**:

1. Enable snoop logging ("Enabled", not filtered), restart BT
2. Start from app Home screen
3. Do exactly one action
4. Wait 10-20s (collect notifications)
5. Pull log + save screenshot + UI dump (optional)
6. Extract relevant writes/notifies into a structured record

### Run Naming Convention

```
RUN_010_probe_switch_remote_to_probe1
RUN_020_open_equipment_life
RUN_030_press_boost
```

### Record Per Run

- Screenshot path + what value is visible
- **Exact timestamp of action** (use `date -Iseconds` before/after)
- Writes to handle `0x0013` (hex payloads)
- Notifications from handle `0x000e` (type 0x01/0x02/0x03/0x23 payloads)

---

## Protocol Overview (Already Decoded)

- Prefix `a5b6`, XOR checksum (last byte)
- Status notify handle `0x000e` (UUID `0003caa2...`)
- Command write handle `0x0013` (UUID `0003cbb1...`)
- Packet types:
  - `0x01`: Status (182 bytes)
  - `0x02`: Schedule
  - `0x03`: History/Sensors
  - `0x10`: Query/Request
  - `0x1a`: Settings (12 bytes)
  - `0x23`: Acknowledgment

See [protocol.md](../protocol.md) for full protocol documentation.

---

## Phase 1: Humidity Field Verification

**Status:** Byte 4 was identified as remote humidity, but needs verification with correlated captures.

### The Problem

Analysis of 1721 STATUS packets showed byte 4 is always 55, never varying. This could mean:
- The room humidity was actually stable at 55%
- Byte 4 is a cached/baseline value, not live humidity
- We're reading the wrong byte

Byte 60 shows variation and sensor-dependence:
- Remote sensor: ~55-65% when divided by 2
- Probe1 sensor: ~50-79% when divided by 2

### Verification Method

Use checkpoint captures to correlate displayed values with packet bytes:

```bash
./scripts/capture/app_control.sh capture humidity_verify
```

1. Navigate to Instantaneous Measurements screen
2. Record checkpoint with displayed humidity values
3. Wait for humidity to change (or create conditions that change it)
4. Record another checkpoint
5. Compare byte 4 and byte 60 values at each checkpoint

### Key Questions

- Does byte 4 change when app-displayed humidity changes?
- Does byte 60 ÷ 2 match the displayed humidity for each sensor?
- Is humidity reporting sensor-dependent (different bytes for different sensors)?

### Runs

1. **RUN_010** - Open Instantaneous Measurements, select Remote
2. **RUN_011** - Select Probe 1 (same screen)
3. **RUN_012** - Select Probe 2 (same screen)

### Analysis

1. Extract all `a5b6 01 06 ...` packets (type 0x01)
2. Use `--checkpoints` to correlate with recorded values
3. Compare byte 4 and byte 60 against displayed humidity

---

## Phase 2: Equipment Life Fields

Opening Equipment Life screen triggers specific packets.

### Runs

1. **RUN_020** - Open Equipment Life screen, screenshot showing:
   - Filter life days
   - Operating days
   - Serial number
   - Versions list (if visible)

2. **RUN_021** - Scroll to reveal more info if hidden

### Analysis

Search payloads for:
- Filter days as little-endian uint16
- Operating days as little-endian uint16
- Serial number as ASCII fragments

---

## Phase 3: BOOST Button and Bypass Status

### BOOST Button

1. **RUN_030** - Press BOOST once
2. **RUN_031** - Press BOOST again (to cancel)

Identify the command packet type and enable/disable bytes.

### Bypass Status

1. **RUN_040** - Toggle Night Ventilation Boost Mode
2. **RUN_041** - Toggle Summer limit enable

Look for status byte changes correlated with bypass icon state.

---

## Phase 4: Summer Limit Threshold

The enable flag is decoded; need the threshold VALUE.

### Runs

1. **RUN_050** - Try changing summer threshold via UI
2. If read-only, capture while screen is open

Search status/history for the threshold value (e.g., `0x1A` = 26°C).

---

## Phase 5: Special Modes

Configuration → Special modes toggles.

### Runs (one toggle per run)

- RUN_060: Toggle Holiday Mode
- RUN_061: Toggle Fixed Air Flow Rate Mode
- RUN_062: Toggle Boost Mode - 30 MIN
- RUN_063: Toggle Night Ventilation Boost Mode

For each, identify which byte/bit changed in the settings packet.

---

## Phase 6: Time Slot Scheduling

### Runs

1. **RUN_070** - Open Time slot screen (no changes)
2. **RUN_071** - Toggle "Activating time slots" ON/OFF
3. **RUN_072** - Change one hour's Mode
4. **RUN_073** - Change one hour's temperature

Extract type `0x02` packets and diff to find encoding.

---

## Phase 7: Diagnostic Health Statuses

### Runs

1. **RUN_080** - Open Diagnostic screen, screenshot showing component statuses

Look for bitfield pattern (4 statuses = 4 bits/bytes).

---

## Extraction Checklist

From each btsnoop:

- Writes to command char: `btatt.opcode == 0x12 && btatt.handle == 0x0013`
- Notifications from status char: `btatt.opcode == 0x1b && btatt.handle == 0x000e`
- Classify by type byte: `payload[2]`

### Extraction Scripts

**Basic extraction:**
```bash
python scripts/capture/extract_packets.py session/btsnoop.log
```

**With checkpoint correlation** (for matching packet bytes to app values):
```bash
python scripts/capture/extract_packets.py session/btsnoop.log \
    --checkpoints session/checkpoints.txt \
    --window 10
```

**Output status packets as hex** (for batch analysis):
```bash
python scripts/capture/extract_packets.py session/btsnoop.log --status-hex
```

---

## Deliverables

1. **Run table** (one row per run):
   - Run ID, UI action, screenshot path, writes (hex), notifies (hex)

2. **Field map** with evidence:
   - Offset + scaling + supporting packet examples

3. **New command list** (if any beyond known 0x1a)
