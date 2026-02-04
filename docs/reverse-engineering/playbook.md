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

## Capture Discipline (Critical)

Each test run must have **one UI change only**.

For every run:

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
- Exact timestamp of action
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

See [PROTOCOL_SPEC.md](PROTOCOL_SPEC.md) for full protocol documentation.

---

## Phase 1: Probe 1 Humidity

Force **UI-driven sensor selection** differences to identify humidity bytes.

### Hypothesis

When the selected sensor changes in the app, some byte(s) in the status packet should change from Remote humidity to Probe1 humidity values.

### Runs

1. **RUN_010** - Open Instantaneous Measurements, select Remote
2. **RUN_011** - Select Probe 1 (same screen)
3. **RUN_012** - Select Probe 2 (same screen)

### Analysis

1. Extract all `a5b6 01 06 ...` packets (type 0x01)
2. Compute byte-diff between "Remote selected" vs "Probe1 selected"
3. Find bytes that match humidity values (raw or scaled)

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

Use the extraction script:
```bash
python scripts/ble-capture/extract_packets.py captures/btsnoop_001.log
```

---

## Deliverables

1. **Run table** (one row per run):
   - Run ID, UI action, screenshot path, writes (hex), notifies (hex)

2. **Field map** with evidence:
   - Offset + scaling + supporting packet examples

3. **New command list** (if any beyond known 0x1a)
