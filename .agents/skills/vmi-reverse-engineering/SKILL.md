---
name: vmi-reverse-engineering
description: This skill should be used when the user asks to "reverse engineer VMI", "capture BLE traffic", "analyze VMI protocol", "control VMI app via ADB", "pull btsnoop logs", or discusses Ventilairsec device protocol analysis.
---

# VMI App Reverse Engineering

Control the Ventilairsec VMI+ app via ADB to capture and analyze BLE protocol traffic.

## Quick Start

```bash
# 1. Enable BT snoop logging (one-time setup)
./scripts/capture/vmictl.py btsnoop-enable

# 2. Connect to device
./scripts/capture/vmictl.py connect

# 3. Start capture session
SESSION=$(./scripts/capture/vmictl.py session-start my_session)
# Navigate, take checkpoints, record values, then end session
./scripts/capture/vmictl.py session-end "$SESSION"
```

## Environment Setup

Copy `.env.example` to `.env` and configure:

| Variable | Description | Example |
|----------|-------------|---------|
| `VMI_MAC` | Device MAC address | `00:A0:50:XX:XX:XX` |
| `VMI_ADB_TARGET` | ADB device (for WiFi) | `192.168.1.100:5555` |

## ADB Connection

```bash
# USB connection
adb devices

# WiFi connection (connect USB first, then)
adb tcpip 5555
adb connect <phone-ip>:5555

# Specify target for multiple devices
VMI_ADB_TARGET=192.168.1.100:5555 ./scripts/capture/vmictl.py connect
```

## Bluetooth Snoop Logging

**CRITICAL:** Must use "Enabled" mode (not filtered) for full packet captures.

```bash
# Automated setup (opens Developer Options, selects correct mode)
./scripts/capture/vmictl.py btsnoop-enable

# Or manually:
# 1. Settings → Developer Options
# 2. "Enable Bluetooth HCI snoop log" → "Enabled" (NOT filtered)
# 3. Toggle Bluetooth off/on
```

## App Control Commands

### Connection
| Command | Description |
|---------|-------------|
| `connect` | Full sequence: launch → scan → pair → dismiss update dialog |
| `launch` | Just launch the app |
| `vmci` | Tap VMCI device type |
| `pair` | Tap PAIR on scan results |
| `dismiss` | Dismiss update dialog |

### Navigation (from home screen)
| Command | Description |
|---------|-------------|
| `menu` | Open hamburger menu |
| `config` | Menu → Configuration |
| `simplified` | Configuration → Simplified |
| `maintenance` | Menu → Maintenance |
| `sensors` | Menu → Sensor management |

### Maintenance Screens
| Command | Description |
|---------|-------------|
| `available-info` | Maintenance → Available info |
| `equipment-life` | Available info → Equipment life |
| `measurements` | Available info → Measurements (temp/humidity) |
| `measurements-full` | Full nav: home → menu → maintenance → available info → measurements |
| `diagnostic` | Available info → Diagnostic |

### Configuration Screens
| Command | Description |
|---------|-------------|
| `special-modes` | Configuration → Special modes (holiday, etc.) |
| `special-modes-full` | Full nav from home to Special modes |
| `time-slots` | Configuration → Time slot configuration |

### Sensor Selection (from Sensor management)
| Command | Description |
|---------|-------------|
| `sensor-probe1` | Select Probe 1 (outlet) |
| `sensor-probe2` | Select Probe 2 (inlet) |
| `sensor-remote` | Select Remote Control |

### Fan Control (from home screen)
| Command | Description |
|---------|-------------|
| `fan-min` | Set to LOW (131 m³/h) |
| `fan-mid` | Set to MEDIUM (164 m³/h) |
| `fan-max` | Set to HIGH (201 m³/h) |
| `boost` | Activate BOOST mode |

### Holiday Mode (from Special modes screen)
| Command | Description |
|---------|-------------|
| `holiday-toggle` | Toggle Holiday mode ON/OFF |
| `holiday-days <n>` | Set Holiday duration to n days |

### Utility
| Command | Description |
|---------|-------------|
| `screenshot [file]` | Take screenshot |
| `scroll` | Scroll down |
| `back` | Press back button |
| `ui` | Dump UI hierarchy (XML) |
| `resolution` | Show detected resolution |

### Bluetooth Capture
| Command | Description |
|---------|-------------|
| `btsnoop-enable` | Enable FULL BT snoop logging |
| `btstart` | Enable logging (basic, may be filtered) |
| `btpull` | Pull btsnoop logs via bugreport |
| `session-start <name>` | Start capture session, outputs directory path |
| `session-checkpoint <dir>` | Take timestamped screenshot, outputs image path |
| `session-end <dir>` | End session, pull btsnoop logs |
| `collect-sensors [--force]` | Build timestamped UI+packet evidence session for sensor analysis |
| `should-collect` | Check if sensor collection is due |

## Capture Session Workflow

Non-interactive commands for CLI tools and coding agents:

```bash
# 1. Start session (outputs directory path)
SESSION=$(./scripts/capture/vmictl.py session-start humidity_test)
# Example output: data/captures/humidity_test_20260205_153000

# 2. Navigate to screen, take checkpoint (outputs screenshot path)
SCREENSHOT=$(./scripts/capture/vmictl.py session-checkpoint "$SESSION")
# Example output: data/captures/.../checkpoint_1_153045.png

# 3. Read the screenshot to see values, then append to checkpoints.txt
# (Agent reads image, then writes observed values)

# 4. End session and pull btsnoop logs
./scripts/capture/vmictl.py session-end "$SESSION"
```

### Recording Values

After each checkpoint, append observed values to `$SESSION/checkpoints.txt`:

```
remote_temp=19
remote_humidity=55
probe1_temp=16
probe1_humidity=71
notes=after switching to Probe1 sensor
```

The checkpoint timestamp and screenshot filename are automatically recorded.

### Session Output

Each session creates a directory with:
- `btsnoop.log` - Raw BLE packet capture
- `checkpoints.txt` - Timestamps + values (values added by agent)
- `checkpoint_N_HHMMSS.png` - Screenshots for each checkpoint

## Packet Analysis

### Basic Extraction
```bash
python scripts/capture/extract_packets.py data/captures/session/btsnoop.log
```

### With Checkpoint Correlation
```bash
python scripts/capture/extract_packets.py session/btsnoop.log \
    --checkpoints session/checkpoints.txt \
    --window 10
```

Shows packets within ±10 seconds of each checkpoint, comparing byte values to recorded app values.

### Export Status Packets
```bash
python scripts/capture/extract_packets.py session/btsnoop.log --status-hex
```

## Screen Hierarchy

```
HOME (fan control buttons)
├── menu
│   ├── Configuration
│   │   ├── Simplified (airflow slider)
│   │   ├── Special modes (holiday, night vent, fixed airflow)
│   │   └── Time slot configuration
│   ├── Maintenance
│   │   └── Available info
│   │       ├── Equipment life (filter days, serial)
│   │       ├── Instantaneous measurements (temp/humidity)
│   │       └── Diagnostic (component health)
│   └── Sensor management (probe selection)
```

## Capture Discipline

### Key Principle
**Always record app-displayed values WITH timestamps** for packet correlation.

### For Protocol Discovery
1. Start session: `SESSION=$(./scripts/capture/vmictl.py session-start test_name)`
2. Navigate to relevant screen
3. Take checkpoint: `IMG=$(./scripts/capture/vmictl.py session-checkpoint "$SESSION")`
4. Read screenshot, append values to `$SESSION/checkpoints.txt`
5. Perform action (e.g., change sensor)
6. Take another checkpoint, record values
7. End session: `./scripts/capture/vmictl.py session-end "$SESSION"`
8. Compare packet bytes between checkpoints

### For Targeted Tests
One action per capture:
1. Reset BT: `adb shell svc bluetooth disable && sleep 2 && adb shell svc bluetooth enable`
2. Connect to device
3. Perform exactly ONE action
4. Wait 10-20 seconds
5. Pull logs: `btpull`

## Protocol Quick Reference

| Type | Byte 2 | Size | Description |
|------|--------|------|-------------|
| STATUS | `0x01` | 182 | Device state, sensors, settings |
| SCHEDULE | `0x02` | 182 | Time slot configuration |
| HISTORY | `0x03` | 182 | Sensor readings history |
| QUERY | `0x10` | 11 | Request to device |
| SETTINGS | `0x1a` | 12 | Configuration change |
| ACK | `0x23` | 182 | Acknowledgment |

All packets: `0xa5 0xb6` magic prefix, XOR checksum (last byte).

## Instructions for Claude

When helping with reverse engineering:

1. **Before capturing:** Ensure BT snoop is enabled with `btsnoop-enable`
2. **For new protocol fields:** Use capture session with checkpoints
3. **Record values:** Read each checkpoint screenshot, append values to checkpoints.txt
4. **Compare packets:** Use `--checkpoints` flag to correlate bytes with app values
5. **Navigation:** Follow screen hierarchy - can't jump directly to submenus
6. **Verify results:** Check screenshots in session directory

### Opportunistic Data Collection

**At the start of any VMI debugging session**, run the sensor collection command:

```bash
./scripts/capture/vmictl.py collect-sensors
```

This command:
1. Checks if 15+ minutes have passed since last collection (skip if too recent)
2. Navigates to Instantaneous Measurements screen
3. Takes a screenshot and pulls btsnoop logs
4. Extracts packet byte values and displays them for comparison

Use `--force` to collect even if less than 15 minutes have passed.

After running, read the screenshot and compare app values to packet bytes. If they differ, add a data point to GitHub issue #9.

| Field | App Screen | Packet Location |
|-------|------------|-----------------|
| Remote temp | Remote Control → Temperature | STATUS byte 8 |
| Remote humidity | Remote Control → Humidity | STATUS byte 4 |
| Probe 1 temp | Probe N°1 → Temperature | HISTORY byte 6 |
| Probe 1 humidity | Probe N°1 → Humidity | HISTORY byte 8 |
| Probe 2 temp | Probe N°2 → Temperature | HISTORY byte 11 |

Data is stored persistently in `data/captures/` (gitignored, survives reboots).

### Common Investigation Patterns

**To verify a byte offset:**
```bash
# Start session
SESSION=$(./scripts/capture/vmictl.py session-start byte_verify)

# Navigate to screen showing the value
./scripts/capture/vmictl.py measurements-full

# Take checkpoint, read screenshot, record values
IMG=$(./scripts/capture/vmictl.py session-checkpoint "$SESSION")
# Read $IMG to see displayed values, append to $SESSION/checkpoints.txt

# Change something that should affect the value
./scripts/capture/vmictl.py sensor-probe1

# Take another checkpoint
IMG=$(./scripts/capture/vmictl.py session-checkpoint "$SESSION")
# Read $IMG, append new values to checkpoints.txt

# End session and analyze
./scripts/capture/vmictl.py session-end "$SESSION"
python scripts/capture/extract_packets.py "$SESSION/btsnoop.log" --checkpoints "$SESSION/checkpoints.txt"
```

**To find which byte encodes a value:**
1. Capture with known app values at specific timestamps
2. Find packets near those timestamps
3. Search for the value (or value×2, or little-endian encoding)
4. Verify by capturing again with a different value
