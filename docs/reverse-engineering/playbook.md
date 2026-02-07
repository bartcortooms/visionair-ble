# VisionAir BLE Reverse Engineering Playbook

This playbook describes how to set up BLE traffic capture from the VisionAir device and the methodology for decoding protocol fields.

## 1. Phone Setup

### Requirements

- Android phone with:
  - Developer options enabled
  - ADB debugging enabled (USB or WiFi)
  - VMI+ app installed: `com.ventilairsec.ventilairsecinstallateur`
- ADB installed on your computer
- Optional: nRF Connect app for controlled GATT operations

### Environment

Copy `.env.example` to `.env` and configure your values:

```bash
cp .env.example .env
```

| Variable | Description | Example |
|----------|-------------|---------|
| `VISIONAIR_MAC` | Device MAC address | `00:A0:50:XX:XX:XX` |
| `ADB_TARGET` | ADB device (optional, auto-detects) | `192.168.1.100:5555` |
| `PHONE_RESOLUTION` | Force screen resolution (optional) | `1080x2340` |
| `ESPHOME_PROXY_HOST` | ESPHome BLE proxy IP (optional) | `192.168.1.50` |
| `ESPHOME_API_KEY` | ESPHome API key (optional) | — |

### ADB Connection

```bash
# USB
adb devices

# WiFi (connect USB first, then)
adb tcpip 5555
adb connect <phone-ip>:5555

# Multiple devices — set ADB_TARGET or use:
ADB_TARGET=<ip>:5555 ./scripts/capture/vmictl.py <command>
```

### Bluetooth HCI Snoop Logging

**IMPORTANT:** For full packet captures, you must enable BT snoop logging in Developer Options with the correct mode. The `settings` command alone is not sufficient.

**Automated setup:**
```bash
./scripts/capture/vmictl.py btsnoop-enable
```

This opens Developer Options, selects "Enabled" mode (not filtered), and toggles Bluetooth to apply.

**Manual verification** (if automated setup fails):
1. Open **Settings → Developer Options**
2. Find **"Enable Bluetooth HCI snoop log"**
3. Select **"Enabled"** (NOT "Disabled", "Enabled Filtered", or other filtered modes)
4. Toggle Bluetooth off and on

Without the correct mode, you'll get `btsnooz` format (truncated/filtered) instead of full `btsnoop`.

### Pulling BLE Logs

```bash
./scripts/capture/vmictl.py btpull
```

Creates a bugreport and extracts the btsnoop log to `data/captures/`.

**Manual extraction** (if the script fails):
```bash
adb bugreport /tmp/bugreport.zip
unzip -jo /tmp/bugreport.zip "*/btsnoop_hci.log" -d /tmp/
# or for btsnooz format:
unzip -jo /tmp/bugreport.zip "*/btsnooz_hci.log" -d /tmp/
```

**Converting btsnooz to btsnoop:**
```bash
python scripts/capture/btsnooz.py /tmp/btsnooz_hci.log /tmp/btsnoop.log
```

### Adapting to App UI Updates

`vmictl.py` uses selector-based UI targeting via `scripts/capture/vmictl_lib/ui_selectors.toml`, not hardcoded coordinates. When the app UI changes:

1. Dump current UI tree: `./scripts/capture/vmictl.py ui > /tmp/vmi_ui.xml`
2. Find updated labels/content descriptions in the XML
3. Update entries in `scripts/capture/vmictl_lib/ui_selectors.toml`
4. Re-run smoke commands: `menu`, `measurements-full`, `sensors`

### Common `vmictl` Navigation Commands

```bash
# App lifecycle
./scripts/capture/vmictl.py launch
./scripts/capture/vmictl.py stop
./scripts/capture/vmictl.py connect

# Scheduling screen
./scripts/capture/vmictl.py time-slots
./scripts/capture/vmictl.py schedule-edition
./scripts/capture/vmictl.py schedule-planning
./scripts/capture/vmictl.py schedule-hour 12
```

### Troubleshooting

**"more than one device/emulator"** — Set `ADB_TARGET` to specify which device.

**No btsnoop log in bugreport** — Ensure BT HCI snoop is set to "Enabled" (not filtered) in Developer Options, toggle Bluetooth off/on, and perform some BLE activity before pulling.

**Truncated/filtered packets** — If the bugreport contains `btsnooz_hci.log` instead of `btsnoop_hci.log`, or the log has only advertising data without GATT Write/Notify payloads, BT HCI snoop logging is not set to the correct mode. Make sure it is set to **"Enabled"** (not "Enabled Filtered" or any other filtered mode) in Developer Options, then toggle Bluetooth off and on. See the [Bluetooth HCI Snoop Logging](#bluetooth-hci-snoop-logging) section above.

**Wrong UI target selection** — Dump UI tree and update selectors in `ui_selectors.toml`.

---

## 2. Capture Methodology

**Key principle:** Always record app-displayed values WITH timestamps so they can be correlated with specific packets.

### Checkpoint-Based Sessions (Recommended)

Non-interactive session commands for CLI tools and coding agents:

```bash
# 1. Start session (outputs directory path)
SESSION=$(./scripts/capture/vmictl.py session-start humidity_test)

# 2. Navigate to screen, take checkpoint (outputs screenshot path)
./scripts/capture/vmictl.py measurements-full
SCREENSHOT=$(./scripts/capture/vmictl.py session-checkpoint "$SESSION")

# 3. Read the screenshot to see values, then append to checkpoints.txt
cat >> "$SESSION/checkpoints.txt" << EOF
remote_temp=19
remote_humidity=55
probe1_temp=16
probe1_humidity=71
EOF

# 4. Repeat steps 2-3 for more checkpoints as needed

# 5. End session and pull btsnoop logs
./scripts/capture/vmictl.py session-end "$SESSION"
```

Each checkpoint automatically records a timestamp and screenshot filename.

**Auto-checkpointing for state-modifying commands:** Commands that modify the VMI (`fan-min`, `fan-mid`, `fan-max`, `boost`, `preheat-toggle`, `airflow`, `airflow-min`, `airflow-max`, `holiday-toggle`, `holiday-days`, `firmware-update`) automatically take a checkpoint when a session is active. They also always append to `data/captures/vmi_actions.log` regardless of session state. This means you only need manual `session-checkpoint` calls for read-only observations.

**Analysis with checkpoints:**
```bash
python scripts/capture/extract_packets.py $SESSION/btsnoop.log \
    --checkpoints $SESSION/checkpoints.txt --window 10
```

Shows packets within ±10 seconds of each checkpoint, with byte values alongside recorded app values.

### Single-Action Runs

For targeted tests, each run should have **one UI change only**:

1. Enable snoop logging ("Enabled", not filtered), restart BT
2. Start from app Home screen
3. Do exactly one action
4. Wait 10-20s (collect notifications)
5. Pull log + save screenshot + UI dump (optional)
6. Extract relevant writes/notifies into a structured record

**Naming convention:**
```
RUN_010_probe_switch_remote_to_probe1
RUN_020_open_equipment_life
RUN_030_press_boost
```

**Record per run:**
- Screenshot path + what value is visible
- **Exact timestamp of action** (use `date -Iseconds` before/after)
- Writes to handle `0x0013` (hex payloads)
- Notifications from handle `0x000e` (type 0x01/0x02/0x03/0x23 payloads)

---

## 3. Packet Extraction

From each btsnoop:
- Writes to command char: `btatt.opcode == 0x12 && btatt.handle == 0x0013`
- Notifications from status char: `btatt.opcode == 0x1b && btatt.handle == 0x000e`
- Classify by type byte: `payload[2]`

```bash
# Basic extraction
python scripts/capture/extract_packets.py session/btsnoop.log

# With checkpoint correlation
python scripts/capture/extract_packets.py session/btsnoop.log \
    --checkpoints session/checkpoints.txt --window 10

# Export status packets as hex
python scripts/capture/extract_packets.py session/btsnoop.log --status-hex
```

See [protocol.md](../protocol.md) for packet type reference and field offsets.

---

## 4. Open Investigations

### Humidity Field (byte 4 vs byte 60)

Byte 4 in DEVICE_STATE is documented as remote humidity but was always 55 across 1721 packets. Open questions:
- Does byte 4 change when app-displayed humidity changes?
- Does byte 60 ÷ 2 match the displayed humidity for each sensor?
- Is humidity reporting sensor-dependent?

**Method:** Use checkpoint captures on the Instantaneous Measurements screen, switching between Remote/Probe1/Probe2 sensors, recording displayed values at each checkpoint.

### Night Ventilation & Fixed Air Flow

Packet mapping unknown. These modes have UI toggles in Configuration → Special Modes but we haven't captured their protocol encoding. May use `REQUEST` (0x10) or `SETTINGS` (0x1a) path.

### Bypass State

Encoding unknown (weather dependent). Look for status byte changes correlated with bypass icon state.

### Diagnostic Bitfield (byte 54)

Only value 0x0F (all healthy) observed. Bit-to-component mapping assumed from UI order. Need a device with a faulty component to verify.

---

## 5. Completed Investigations

For reference — these are fully decoded and implemented.

| Feature | Protocol | Status |
|---------|----------|--------|
| BOOST ON/OFF | REQUEST param 0x19, byte 9 = 0/1 | Implemented |
| Holiday mode | REQUEST param 0x1a, byte 9 = days | Implemented |
| Equipment life | DEVICE_STATE bytes 26-29 | Implemented |
| Summer limit threshold | DEVICE_STATE byte 38 | Implemented |
| Airflow settings | SETTINGS 0x1a, bytes 9-10 | Implemented |
| Preheat control | SETTINGS 0x1a, bytes 6+8 | Implemented |
| Schedule config | 0x40 write / 0x46 response | Experimental |

See [implementation-status.md](../implementation-status.md) for details.
