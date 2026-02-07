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

For phone setup, ADB connection, BT snoop logging details, and troubleshooting, see [playbook.md](docs/reverse-engineering/playbook.md) section 1.

## App Control Commands

### Connection
| Command | Description |
|---------|-------------|
| `connect` | Full sequence: launch → scan → pair → dismiss update dialog |
| `launch` | Just launch the app |
| `stop` | Force-stop the VMI+ app |
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

### Schedule Controls (from Time Slot Configuration)
| Command | Description |
|---------|-------------|
| `schedule-edition` | Select EDITION tab |
| `schedule-planning` | Select PLANNING tab |
| `schedule-hour <0-23>` | Tap hour row in schedule table |

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
| `preheat-toggle` | Toggle preheat ON/OFF |

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
| `battery` | Show phone battery level and charging status |

### Bluetooth Capture
| Command | Description |
|---------|-------------|
| `btsnoop-enable` | Enable FULL BT snoop logging |
| `btstart` | Enable logging (basic, may be filtered) |
| `btpull` | Pull btsnoop logs via bugreport |
| `session-start <name>` | Start capture session, outputs directory path |
| `session-checkpoint <dir> [note]` | Take timestamped screenshot with optional note |
| `session-end <dir>` | End session, pull btsnoop logs |
| `collect-sensors [--force]` | Build timestamped UI+packet evidence session for sensor analysis |
| `should-collect` | Check if sensor collection is due |

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

## Capture Session Workflow

```bash
# 1. Start session (outputs directory path)
SESSION=$(./scripts/capture/vmictl.py session-start humidity_test)

# 2. Navigate to screen, take checkpoint (outputs screenshot path)
SCREENSHOT=$(./scripts/capture/vmictl.py session-checkpoint "$SESSION")

# 3. Read the screenshot to see values, then append to checkpoints.txt

# 4. End session and pull btsnoop logs
./scripts/capture/vmictl.py session-end "$SESSION"
```

After each checkpoint, append observed values to `$SESSION/checkpoints.txt`:

```
remote_temp=19
remote_humidity=55
probe1_temp=16
probe1_humidity=71
notes=after switching to Probe1 sensor
```

## Packet Analysis

```bash
# Basic extraction
python scripts/capture/extract_packets.py session/btsnoop.log

# With checkpoint correlation
python scripts/capture/extract_packets.py session/btsnoop.log \
    --checkpoints session/checkpoints.txt --window 10

# Export status packets as hex
python scripts/capture/extract_packets.py session/btsnoop.log --status-hex
```

For packet type reference, field offsets, and encoding details, see [protocol.md](docs/protocol.md).

## Instructions for Claude

When helping with reverse engineering:

1. **Before capturing:** Ensure BT snoop is enabled with `btsnoop-enable`
2. **For new protocol fields:** Use capture session with checkpoints
3. **Record values:** Read each checkpoint screenshot, append values to checkpoints.txt
4. **Compare packets:** Use `--checkpoints` flag to correlate bytes with app values
5. **Navigation:** Follow screen hierarchy - can't jump directly to submenus
6. **Verify results:** Check screenshots in session directory

### Phone Battery Monitoring

The Fairphone used for reverse engineering is **not plugged in** and will eventually run out of battery. The `vmictl` script automatically checks battery level every 5 minutes and prints a warning to stderr when it's low.

**You MUST relay battery warnings to the user.** When you see output containing `BATTERY WARNING` or `BATTERY CRITICAL` from any vmictl command:

- **WARNING (<= 20%):** Immediately tell the user: *"The phone battery is at X% — it should be charged soon to avoid losing the session."*
- **CRITICAL (<= 10%):** **Stop what you are doing** and alert the user: *"The phone battery is critically low (X%). It needs to be charged NOW or it will shut off and we'll lose BLE connectivity."*

You can also check manually at any time with `./scripts/capture/vmictl.py battery`.

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
