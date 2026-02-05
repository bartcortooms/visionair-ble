# VMI App Reverse Engineering

Control the Ventilairsec VMI+ app via ADB to capture and analyze BLE protocol traffic.

## Quick Start

```bash
# 1. Enable BT snoop logging (one-time setup)
./scripts/capture/app_control.sh btsnoop-enable

# 2. Connect to device
./scripts/capture/app_control.sh connect

# 3. Start capture session
./scripts/capture/app_control.sh capture my_session
```

## Environment Setup

Copy `.env.example` to `.env` and configure:

| Variable | Description | Example |
|----------|-------------|---------|
| `VMI_MAC` | Device MAC address | `00:A0:50:XX:XX:XX` |
| `VMI_ADB_TARGET` | ADB device (for WiFi) | `192.168.1.100:5555` |
| `VMI_RESOLUTION` | Force screen resolution | `1080x2340` |

## ADB Connection

```bash
# USB connection
adb devices

# WiFi connection (connect USB first, then)
adb tcpip 5555
adb connect <phone-ip>:5555

# Specify target for multiple devices
VMI_ADB_TARGET=192.168.1.100:5555 ./scripts/capture/app_control.sh connect
```

## Bluetooth Snoop Logging

**CRITICAL:** Must use "Enabled" mode (not filtered) for full packet captures.

```bash
# Automated setup (opens Developer Options, selects correct mode)
./scripts/capture/app_control.sh btsnoop-enable

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
| `holiday-test [n]` | Full capture test: reset BT, connect, toggle holiday |

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
| `capture [name]` | Start interactive capture session |

## Interactive Capture Session

The `capture` command starts an interactive session for correlating app values with packet data:

```bash
./scripts/capture/app_control.sh capture humidity_test
```

### Session Commands
| Command | Description |
|---------|-------------|
| `c` / `checkpoint` | Record: timestamp + screenshot + app values |
| `s` / `screenshot` | Just take a screenshot |
| `q` / `quit` | End session, pull btsnoop logs |
| `help` | Show commands |

### Checkpoint Workflow

```
capture> c
=== Checkpoint 1 at 2026-02-05T15:30:45+01:00 ===
Screenshot: checkpoint_1_153045.png
Enter values shown in app:
  Remote temp (°C): 19
  Remote humidity (%): 55
  Probe1 temp (°C): 16
  Probe1 humidity (%): 71
  Probe2 temp (°C): 13
  Airflow (low/med/high): medium
  Notes: after switching to Probe1 sensor
Checkpoint 1 saved.

capture> q
Ending session...
Pulling btsnoop logs...
=== Session Complete ===
Directory: /tmp/vmi_btlogs/humidity_test_20260205_153000
```

### Session Output

Each session creates a directory with:
- `btsnoop.log` - Raw BLE packet capture
- `checkpoints.txt` - Timestamped app values
- `checkpoint_N_HHMMSS.png` - Screenshots for each checkpoint

## Packet Analysis

### Basic Extraction
```bash
python scripts/capture/extract_packets.py /tmp/vmi_btlogs/session/btsnoop.log
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
1. Start capture session: `./scripts/capture/app_control.sh capture test_name`
2. Navigate to relevant screen
3. Record checkpoint (`c`) with visible values
4. Perform action (e.g., change sensor)
5. Record another checkpoint
6. Compare packet bytes between checkpoints

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
2. **For new protocol fields:** Use interactive capture session with checkpoints
3. **Record values:** Always note what the app displays at each checkpoint
4. **Compare packets:** Use `--checkpoints` flag to correlate bytes with app values
5. **Navigation:** Follow screen hierarchy - can't jump directly to submenus
6. **Verify results:** Check screenshots in `/tmp/vmi_btlogs/` or session directory

### Common Investigation Patterns

**To verify a byte offset:**
```bash
./scripts/capture/app_control.sh capture byte_verify
# Navigate to screen showing the value
# c (checkpoint, record displayed value)
# Change something that should affect the value
# c (checkpoint, record new value)
# q (quit, pull logs)
python scripts/capture/extract_packets.py session/btsnoop.log --checkpoints session/checkpoints.txt
```

**To find which byte encodes a value:**
1. Capture with known app values at specific timestamps
2. Find packets near those timestamps
3. Search for the value (or value×2, or little-endian encoding)
4. Verify by capturing again with a different value
