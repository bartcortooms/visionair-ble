#!/bin/bash
# VMI App Control Script
# Controls the Ventilairsec VMI+ app via ADB and captures BLE traffic

set -e

# Find and source .env file from project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# ADB target (can be set via VMI_ADB_TARGET env var or .env file)
ADB_TARGET="${VMI_ADB_TARGET:-}"
adb_cmd() {
    if [[ -n "$ADB_TARGET" ]]; then
        adb -s "$ADB_TARGET" "$@"
    else
        adb "$@"
    fi
}

# Auto-detect screen resolution or use VMI_RESOLUTION env var
detect_resolution() {
    if [[ -n "$VMI_RESOLUTION" ]]; then
        echo "$VMI_RESOLUTION"
        return
    fi

    local size=$(adb_cmd shell wm size 2>/dev/null | grep -oE '[0-9]+x[0-9]+' | head -1)
    if [[ -n "$size" ]]; then
        echo "$size"
    else
        echo "1080x2340"  # default
    fi
}

RESOLUTION=$(detect_resolution)

# Coordinate mappings per resolution
# Format: function_x function_y
get_coords() {
    local func=$1
    case "$RESOLUTION" in
        1080x2340)
            case "$func" in
                vmci)       echo "280 1105" ;;
                pair)       echo "800 350" ;;
                menu)       echo "848 183" ;;
                config)     echo "540 1316" ;;
                simplified) echo "540 1071" ;;
                maintenance) echo "540 1564" ;;
                sensors)    echo "540 1813" ;;
                dismiss)    echo "418 1280" ;;
                slider_left)  echo "163 783" ;;
                slider_right) echo "917 783" ;;
                fan_min)    echo "212 468" ;;
                fan_mid)    echo "540 468" ;;
                fan_max)    echo "868 468" ;;
                boost)      echo "378 790" ;;
                available_info) echo "540 848" ;;
                equipment_life) echo "540 702" ;;
                measurements)   echo "540 889" ;;
                diagnostic)     echo "540 1199" ;;
                special_modes)  echo "540 1320" ;;
                time_slots)     echo "540 1568" ;;
                sensor_probe1)  echo "540 800" ;;
                sensor_probe2)  echo "540 990" ;;
                sensor_remote)  echo "540 1270" ;;
                # Holiday mode (Special modes screen)
                holiday_card)   echo "540 738" ;;
                holiday_toggle) echo "868 738" ;;
                holiday_days)   echo "540 1038" ;;
            esac
            ;;
        1116x2484|*)
            case "$func" in
                vmci)       echo "291 1214" ;;
                pair)       echo "900 440" ;;
                menu)       echo "876 194" ;;
                config)     echo "558 1397" ;;
                simplified) echo "558 1137" ;;
                maintenance) echo "558 1661" ;;
                sensors)    echo "558 1925" ;;
                dismiss)    echo "432 1359" ;;
                slider_left)  echo "150 460" ;;
                slider_right) echo "950 460" ;;
                fan_min)    echo "219 497" ;;
                fan_mid)    echo "558 497" ;;
                fan_max)    echo "897 497" ;;
                boost)      echo "390 839" ;;
                available_info) echo "558 900" ;;
                equipment_life) echo "558 745" ;;
                measurements)   echo "558 1009" ;;
                diagnostic)     echo "558 1273" ;;
                special_modes)  echo "558 1401" ;;
                time_slots)     echo "558 1665" ;;
                sensor_probe1)  echo "558 850" ;;
                sensor_probe2)  echo "558 1050" ;;
                sensor_remote)  echo "558 1350" ;;
                # Holiday mode (Special modes screen) - TODO: verify coords
                holiday_card)   echo "558 784" ;;
                holiday_toggle) echo "896 784" ;;
                holiday_days)   echo "558 1100" ;;
            esac
            ;;
    esac
}

wake() {
    adb_cmd shell input keyevent KEYCODE_WAKEUP
    sleep 0.3
}

tap() {
    wake
    adb_cmd shell input tap $1 $2
    sleep 2
}

tap_func() {
    local coords=$(get_coords "$1")
    echo "Tapping $1 at $coords (resolution: $RESOLUTION)"
    tap $coords
}

screenshot() {
    wake
    sleep 0.3
    adb_cmd exec-out screencap -p > "${1:-/tmp/vmi_screen.png}"
    echo "Screenshot saved to ${1:-/tmp/vmi_screen.png}"
}

scroll_down() {
    wake
    adb_cmd shell input swipe 500 1800 500 800 300
    sleep 1
}

back() {
    adb_cmd shell input keyevent KEYCODE_BACK
    sleep 1
}

ui_dump() {
    adb_cmd shell uiautomator dump 2>/dev/null
    adb_cmd shell cat /sdcard/window_dump.xml 2>/dev/null
}

# App control functions
launch_app() {
    echo "Launching VMI+ app..."
    adb_cmd shell am force-stop com.ventilairsec.ventilairsecinstallateur
    sleep 1
    adb_cmd shell monkey -p com.ventilairsec.ventilairsecinstallateur -c android.intent.category.LAUNCHER 1
    sleep 3
    screenshot /tmp/vmi_01_home.png
}

select_vmci() {
    echo "Selecting VMCI..."
    tap_func vmci
    sleep 5
    screenshot /tmp/vmi_02_scanning.png
}

tap_pair() {
    echo "Tapping PAIR..."
    tap_func pair
    sleep 5
    screenshot /tmp/vmi_03_paired.png
}

dismiss_update_dialog() {
    echo "Dismissing update dialog..."
    tap_func dismiss
    sleep 2
    screenshot /tmp/vmi_04_main_menu.png
}

tap_menu() {
    echo "Opening menu..."
    tap_func menu
    sleep 2
    screenshot /tmp/vmi_menu.png
}

goto_configuration() {
    echo "Going to Configuration..."
    tap_func config
    sleep 2
    screenshot /tmp/vmi_05_configuration.png
}

goto_simplified_config() {
    echo "Going to Simplified configuration..."
    tap_func simplified
    sleep 2
    screenshot /tmp/vmi_06_simplified_config.png
}

goto_maintenance() {
    echo "Going to Maintenance..."
    tap_func maintenance
    sleep 2
    screenshot /tmp/vmi_07_maintenance.png
}

goto_sensor_management() {
    echo "Going to Sensor management..."
    tap_func sensors
    sleep 2
    screenshot /tmp/vmi_08_sensor_management.png
}

goto_available_info() {
    echo "Going to Available info..."
    tap_func available_info
    sleep 2
    screenshot /tmp/vmi_available_info.png
}

goto_equipment_life() {
    echo "Going to Equipment life..."
    tap_func equipment_life
    sleep 2
    screenshot /tmp/vmi_equipment_life.png
}

goto_measurements() {
    echo "Going to Instantaneous measurements..."
    tap_func measurements
    sleep 2
    screenshot /tmp/vmi_measurements.png
}

goto_measurements_full() {
    echo "Navigating: Home → Menu → Maintenance → Available info → Measurements"
    echo "Step 1/4: Opening menu..."
    tap_func menu
    sleep 2
    echo "Step 2/4: Going to Maintenance..."
    tap_func maintenance
    sleep 2
    echo "Step 3/4: Going to Available info..."
    tap_func available_info
    sleep 2
    echo "Step 4/4: Going to Measurements..."
    tap_func measurements
    sleep 2
    screenshot /tmp/vmi_measurements_full.png
    echo "Done! Screenshot saved to /tmp/vmi_measurements_full.png"
}

goto_diagnostic() {
    echo "Going to Diagnostic..."
    tap_func diagnostic
    sleep 2
    screenshot /tmp/vmi_diagnostic.png
}

goto_special_modes() {
    echo "Going to Special modes..."
    tap_func special_modes
    sleep 2
    screenshot /tmp/vmi_special_modes.png
}

goto_time_slots() {
    echo "Going to Time slot configuration..."
    tap_func time_slots
    sleep 2
    screenshot /tmp/vmi_time_slots.png
}

tap_sensor_probe1() {
    echo "Tapping Probe N°1 row..."
    tap_func sensor_probe1
    sleep 2
    screenshot /tmp/vmi_sensor_probe1.png
}

tap_sensor_probe2() {
    echo "Tapping Probe N°2 row..."
    tap_func sensor_probe2
    sleep 2
    screenshot /tmp/vmi_sensor_probe2.png
}

tap_sensor_remote() {
    echo "Tapping Remote control row..."
    tap_func sensor_remote
    sleep 2
    screenshot /tmp/vmi_sensor_remote.png
}

# Holiday mode functions
goto_special_modes_full() {
    echo "Navigating: Home → Menu → Configuration → Special modes"
    echo "Step 1/3: Opening menu..."
    tap_func menu
    sleep 2
    echo "Step 2/3: Going to Configuration..."
    tap_func config
    sleep 2
    echo "Step 3/3: Scrolling and tapping Special modes..."
    scroll_down
    tap_func special_modes
    sleep 2
    screenshot /tmp/vmi_special_modes.png
    echo "Done! At Special Modes screen."
}

holiday_toggle() {
    echo "Toggling Holiday mode..."
    tap_func holiday_toggle
    sleep 3
    screenshot /tmp/vmi_holiday_toggled.png
}

holiday_set_days() {
    local days="${1:-5}"
    echo "Setting Holiday mode days to $days..."
    # Tap on the days field
    tap_func holiday_days
    sleep 1
    # Clear existing text and enter new value
    adb_cmd shell "input keyevent KEYCODE_MOVE_END"
    adb_cmd shell "input keyevent --longpress KEYCODE_DEL"
    sleep 0.5
    adb_cmd shell "input text '$days'"
    adb_cmd shell "input keyevent KEYCODE_ENTER"
    sleep 2
    screenshot /tmp/vmi_holiday_days_${days}.png
    echo "Days set to $days"
}

holiday_capture_test() {
    local days="${1:-5}"
    echo "=== Holiday Mode Capture Test (days=$days) ==="
    echo ""
    echo "Step 1: Reset BT snoop log..."
    adb_cmd shell svc bluetooth disable
    sleep 2
    adb_cmd shell svc bluetooth enable
    sleep 5
    echo "BT reset complete."
    echo ""
    echo "Step 2: Connect to device..."
    full_connect_sequence
    sleep 3
    echo ""
    echo "Step 3: Navigate to Special Modes..."
    goto_special_modes_full
    echo ""
    echo "Step 4: Turn Holiday OFF (ensure clean state)..."
    # Check current state via UI dump
    adb_cmd shell uiautomator dump 2>/dev/null
    local xml=$(adb_cmd shell cat /sdcard/window_dump.xml 2>/dev/null)
    if echo "$xml" | grep -q 'content-desc="ON".*Holiday' || echo "$xml" | grep -q 'Holiday.*content-desc="ON"'; then
        echo "Holiday is ON, turning OFF first..."
        holiday_toggle
        sleep 3
    fi
    echo ""
    echo "Step 5: Turn Holiday ON with $days days..."
    holiday_toggle
    sleep 2
    # Set days value
    holiday_set_days "$days"
    echo ""
    echo "Step 6: Wait for BLE packet to be sent..."
    sleep 5
    echo ""
    echo "Step 7: Pull btsnoop log..."
    pull_btsnoop
    echo ""
    echo "=== Capture complete! ==="
    echo "Analyze packets with: python scripts/capture/extract_packets.py /tmp/vmi_btlogs/btsnoop_*.log"
}

tap_fan_min() {
    echo "Setting fan to MIN..."
    tap_func fan_min
    screenshot /tmp/vmi_fan_min.png
}

tap_fan_mid() {
    echo "Setting fan to MID..."
    tap_func fan_mid
    screenshot /tmp/vmi_fan_mid.png
}

tap_fan_max() {
    echo "Setting fan to MAX..."
    tap_func fan_max
    screenshot /tmp/vmi_fan_max.png
}

tap_boost() {
    echo "Activating BOOST..."
    tap_func boost
    screenshot /tmp/vmi_boost.png
}

set_airflow_min() {
    echo "Setting airflow to minimum..."
    local coords=$(get_coords slider_left)
    wake
    adb_cmd shell input tap $coords
    sleep 2
    screenshot /tmp/vmi_airflow_min.png
}

set_airflow_max() {
    echo "Setting airflow to maximum..."
    local coords=$(get_coords slider_right)
    wake
    adb_cmd shell input tap $coords
    sleep 2
    screenshot /tmp/vmi_airflow_max.png
}

drag_slider() {
    echo "Dragging slider from $1% to $2%..."
    local left=$(get_coords slider_left)
    local right=$(get_coords slider_right)
    local lx=$(echo $left | cut -d' ' -f1)
    local rx=$(echo $right | cut -d' ' -f1)
    local y=$(echo $left | cut -d' ' -f2)
    local range=$((rx - lx))
    local from_x=$((lx + range * $1 / 100))
    local to_x=$((lx + range * $2 / 100))
    wake
    adb_cmd shell input swipe $from_x $y $to_x $y 500
    sleep 2
    screenshot /tmp/vmi_airflow_changed.png
}

# BLE logging
start_btsnoop() {
    echo "Enabling Bluetooth HCI snoop log..."
    adb_cmd shell settings put secure bluetooth_hci_log 1
    adb_cmd shell svc bluetooth disable
    sleep 2
    adb_cmd shell svc bluetooth enable
    sleep 3
    echo "BT snoop enabled. Logs will be at /data/misc/bluetooth/logs/"
    echo ""
    echo "IMPORTANT: For FULL packet capture (not filtered), you must ALSO:"
    echo "  1. Open Settings -> Developer Options"
    echo "  2. Tap 'Enable Bluetooth HCI snoop log'"
    echo "  3. Select 'Enabled' (NOT 'Enabled Filtered' or other filtered modes)"
    echo "  4. Toggle Bluetooth off/on again"
    echo ""
    echo "Without this, you'll get btsnooz (truncated) instead of btsnoop (full)."
}

enable_btsnoop_full() {
    echo "Enabling FULL Bluetooth HCI snoop logging via Developer Options..."
    echo "Opening Developer Options..."
    adb_cmd shell am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS
    sleep 2

    # Find and tap "Enable Bluetooth HCI snoop log"
    echo "Looking for BT snoop log setting..."
    local max_scrolls=5
    local found=0

    for i in $(seq 1 $max_scrolls); do
        # Dump UI and check for the setting
        adb_cmd shell uiautomator dump 2>/dev/null
        local xml=$(adb_cmd shell cat /sdcard/window_dump.xml 2>/dev/null)

        if echo "$xml" | grep -q "Enable Bluetooth HCI snoop log"; then
            found=1
            break
        fi
        # Scroll down
        adb_cmd shell input swipe 500 1500 500 800 300
        sleep 1
    done

    if [[ $found -eq 0 ]]; then
        echo "ERROR: Could not find 'Enable Bluetooth HCI snoop log' setting"
        return 1
    fi

    # Get the bounds of the setting
    local bounds=$(echo "$xml" | grep -o 'text="Enable Bluetooth HCI snoop log"[^>]*bounds="\[[0-9,]*\]\[[0-9,]*\]"' | grep -o 'bounds="\[[0-9,]*\]\[[0-9,]*\]"' | head -1)

    if [[ -z "$bounds" ]]; then
        echo "ERROR: Could not find bounds for BT snoop setting"
        return 1
    fi

    # Parse bounds and calculate center
    local coords=$(echo "$bounds" | sed 's/bounds="\[\([0-9]*\),\([0-9]*\)\]\[\([0-9]*\),\([0-9]*\)\]"/\1 \2 \3 \4/')
    local x1=$(echo $coords | cut -d' ' -f1)
    local y1=$(echo $coords | cut -d' ' -f2)
    local x2=$(echo $coords | cut -d' ' -f3)
    local y2=$(echo $coords | cut -d' ' -f4)
    local cx=$(( (x1 + x2) / 2 ))
    local cy=$(( (y1 + y2) / 2 ))

    echo "Tapping BT snoop setting at ($cx, $cy)..."
    adb_cmd shell input tap $cx $cy
    sleep 1

    # Now find and tap "Enabled" (not filtered) in the dialog
    adb_cmd shell uiautomator dump 2>/dev/null
    xml=$(adb_cmd shell cat /sdcard/window_dump.xml 2>/dev/null)

    # Find the "Enabled" option (exact match, not "Enabled Filtered")
    bounds=$(echo "$xml" | grep -o 'text="Enabled"[^>]*bounds="\[[0-9,]*\]\[[0-9,]*\]"' | grep -o 'bounds="\[[0-9,]*\]\[[0-9,]*\]"' | head -1)

    if [[ -z "$bounds" ]]; then
        echo "ERROR: Could not find 'Enabled' option in dialog"
        return 1
    fi

    coords=$(echo "$bounds" | sed 's/bounds="\[\([0-9]*\),\([0-9]*\)\]\[\([0-9]*\),\([0-9]*\)\]"/\1 \2 \3 \4/')
    x1=$(echo $coords | cut -d' ' -f1)
    y1=$(echo $coords | cut -d' ' -f2)
    x2=$(echo $coords | cut -d' ' -f3)
    y2=$(echo $coords | cut -d' ' -f4)
    cx=$(( (x1 + x2) / 2 ))
    cy=$(( (y1 + y2) / 2 ))

    echo "Selecting 'Enabled' at ($cx, $cy)..."
    adb_cmd shell input tap $cx $cy
    sleep 1

    # Toggle Bluetooth to apply setting
    echo "Toggling Bluetooth to apply setting..."
    adb_cmd shell svc bluetooth disable
    sleep 2
    adb_cmd shell svc bluetooth enable
    sleep 3

    echo "BT snoop logging enabled (full mode). Ready for capture."
    adb_cmd shell input keyevent KEYCODE_HOME
}

pull_btsnoop() {
    echo "Pulling Bluetooth snoop logs via bugreport..."
    mkdir -p /tmp/vmi_btlogs
    local timestamp=$(date +%Y%m%d_%H%M%S)
    adb_cmd bugreport /tmp/vmi_btlogs/bugreport_${timestamp}.zip
    unzip -jo /tmp/vmi_btlogs/bugreport_${timestamp}.zip "*/btsnooz_hci.log" -d /tmp/vmi_btlogs/ 2>/dev/null || \
    unzip -jo /tmp/vmi_btlogs/bugreport_${timestamp}.zip "*/btsnoop_hci.log" -d /tmp/vmi_btlogs/ 2>/dev/null || \
    unzip -jo /tmp/vmi_btlogs/bugreport_${timestamp}.zip "FS/data/misc/bluetooth/logs/btsnooz_hci.log" -d /tmp/vmi_btlogs/ 2>/dev/null || \
    unzip -jo /tmp/vmi_btlogs/bugreport_${timestamp}.zip "FS/data/misc/bluetooth/logs/btsnoop_hci.log" -d /tmp/vmi_btlogs/ 2>/dev/null || true
    mv /tmp/vmi_btlogs/btsnooz_hci.log /tmp/vmi_btlogs/btsnoop_${timestamp}.log 2>/dev/null || \
    mv /tmp/vmi_btlogs/btsnoop_hci.log /tmp/vmi_btlogs/btsnoop_${timestamp}.log 2>/dev/null || true
    if [[ -f /tmp/vmi_btlogs/btsnoop_${timestamp}.log ]]; then
        echo "Logs saved to /tmp/vmi_btlogs/btsnoop_${timestamp}.log"
        echo "Parse with: python scripts/capture/extract_packets.py /tmp/vmi_btlogs/btsnoop_${timestamp}.log"
    else
        echo "Warning: No btsnoop log found in bugreport. Make sure BT snoop logging is enabled."
        echo "Run: $0 btstart"
    fi
}

# Sensor data collection for protocol verification
# Tracks last checkpoint time and collects all sensor readings

LAST_CHECKPOINT_FILE="/tmp/vmi_btlogs/last_sensor_checkpoint.txt"
CHECKPOINT_INTERVAL_MINUTES=15

# Check if it's time to collect sensor data (15+ minutes since last)
should_collect_sensors() {
    if [[ ! -f "$LAST_CHECKPOINT_FILE" ]]; then
        return 0  # No previous checkpoint, should collect
    fi

    local last_ts=$(cat "$LAST_CHECKPOINT_FILE" 2>/dev/null)
    local now_ts=$(date +%s)
    local diff_minutes=$(( (now_ts - last_ts) / 60 ))

    if [[ $diff_minutes -ge $CHECKPOINT_INTERVAL_MINUTES ]]; then
        return 0  # Should collect
    else
        echo "Last sensor checkpoint was $diff_minutes minutes ago (threshold: $CHECKPOINT_INTERVAL_MINUTES min)" >&2
        return 1  # Too recent
    fi
}

# Collect all sensor readings and compare to packet bytes
# Usage: collect-sensors [--force]
collect_sensors() {
    local force=0
    if [[ "$1" == "--force" ]]; then
        force=1
    fi

    if [[ $force -eq 0 ]] && ! should_collect_sensors; then
        echo "Skipping sensor collection (use --force to override)"
        return 0
    fi

    echo "=== Collecting Sensor Data for Protocol Verification ===" >&2
    mkdir -p /tmp/vmi_btlogs

    local ts=$(date +%Y%m%d_%H%M%S)
    local screenshot_file="/tmp/vmi_btlogs/sensors_${ts}.png"

    # Navigate to measurements screen and capture
    echo "Navigating to Instantaneous Measurements..." >&2
    goto_measurements_full >/dev/null 2>&1
    goto_measurements >/dev/null 2>&1

    # Take screenshot
    adb_cmd exec-out screencap -p > "$screenshot_file"
    echo "Screenshot: $screenshot_file" >&2

    # Pull btsnoop logs
    echo "Pulling btsnoop logs..." >&2
    adb_cmd bugreport "/tmp/vmi_btlogs/bugreport_sensors_${ts}.zip" 2>/dev/null
    unzip -jo "/tmp/vmi_btlogs/bugreport_sensors_${ts}.zip" "*/btsnoop_hci.log" -d /tmp/vmi_btlogs/ 2>/dev/null || true
    local btsnoop_file="/tmp/vmi_btlogs/btsnoop_sensors_${ts}.log"
    mv /tmp/vmi_btlogs/btsnoop_hci.log "$btsnoop_file" 2>/dev/null || true

    # Extract packet byte values
    if [[ -f "$btsnoop_file" ]]; then
        echo "" >&2
        echo "=== Packet Byte Values ===" >&2
        python3 - "$btsnoop_file" << 'PYTHON' 2>/dev/null
import sys
import subprocess
import json

btsnoop = sys.argv[1]
result = subprocess.run(['python3', 'scripts/capture/extract_packets.py', btsnoop, '--json'],
    capture_output=True, text=True, cwd='/home/bart/repos/visionair-ble')
packets = json.loads(result.stdout)

# Get latest STATUS packet
status_pkts = [p for p in packets['raw_packets'] if p['type'] == 0x01]
if status_pkts:
    data = bytes.fromhex(status_pkts[-1]['hex'])
    print(f"STATUS packet:")
    print(f"  Byte 4 (Remote humidity): {data[4]}%")
    print(f"  Byte 8 (Remote temp): {data[8]}°C")

# Get latest HISTORY packet
history_pkts = [p for p in packets['raw_packets'] if p['type'] == 0x03]
if history_pkts:
    data = bytes.fromhex(history_pkts[-1]['hex'])
    print(f"HISTORY packet:")
    print(f"  Byte 6 (Probe 1 temp): {data[6]}°C")
    print(f"  Byte 8 (Probe 1 humidity): {data[8]}%")
    print(f"  Byte 11 (Probe 2 temp): {data[11]}°C")
PYTHON
    fi

    # Update last checkpoint timestamp
    date +%s > "$LAST_CHECKPOINT_FILE"

    echo "" >&2
    echo "=== Action Required ===" >&2
    echo "1. Read screenshot: $screenshot_file" >&2
    echo "2. Compare app values to packet bytes above" >&2
    echo "3. Add data point to GitHub issue #9 if values differ" >&2

    # Output the screenshot path for the agent
    echo "$screenshot_file"
}

# Non-interactive capture session commands
# For use by CLI tools and coding agents

# Start a new capture session - creates directory, returns path
session_start() {
    local session_name="${1:-session}"
    local session_start=$(date +%Y%m%d_%H%M%S)
    local capture_dir="/tmp/vmi_btlogs/${session_name}_${session_start}"
    mkdir -p "$capture_dir"
    echo "$(date -Iseconds)" > "$capture_dir/session_start.txt"
    echo "0" > "$capture_dir/checkpoint_count.txt"
    # Output just the path for easy parsing
    echo "$capture_dir"
}

# Take a checkpoint screenshot, returns the screenshot path
# Usage: session-checkpoint <session_dir>
session_checkpoint() {
    local capture_dir="$1"
    if [[ -z "$capture_dir" || ! -d "$capture_dir" ]]; then
        echo "ERROR: Invalid session directory: $capture_dir" >&2
        return 1
    fi

    # Increment checkpoint counter
    local checkpoint_num=$(cat "$capture_dir/checkpoint_count.txt" 2>/dev/null || echo "0")
    checkpoint_num=$((checkpoint_num + 1))
    echo "$checkpoint_num" > "$capture_dir/checkpoint_count.txt"

    local ts=$(date -Iseconds)
    local ts_file=$(date +%H%M%S)
    local screenshot_file="$capture_dir/checkpoint_${checkpoint_num}_${ts_file}.png"

    # Take screenshot
    adb_cmd exec-out screencap -p > "$screenshot_file"

    # Record timestamp in checkpoints file (values added separately by agent)
    cat >> "$capture_dir/checkpoints.txt" << CHECKPOINT

[checkpoint_$checkpoint_num]
timestamp=$ts
screenshot=checkpoint_${checkpoint_num}_${ts_file}.png
CHECKPOINT

    # Output screenshot path for agent to read
    echo "$screenshot_file"
}

# End session and pull btsnoop logs
# Usage: session-end <session_dir>
session_end() {
    local capture_dir="$1"
    if [[ -z "$capture_dir" || ! -d "$capture_dir" ]]; then
        echo "ERROR: Invalid session directory: $capture_dir" >&2
        return 1
    fi

    echo "$(date -Iseconds)" > "$capture_dir/session_end.txt"

    echo "Pulling btsnoop logs..." >&2
    adb_cmd bugreport "$capture_dir/bugreport.zip"
    unzip -jo "$capture_dir/bugreport.zip" "*/btsnooz_hci.log" -d "$capture_dir/" 2>/dev/null || \
    unzip -jo "$capture_dir/bugreport.zip" "*/btsnoop_hci.log" -d "$capture_dir/" 2>/dev/null || true
    mv "$capture_dir/btsnooz_hci.log" "$capture_dir/btsnoop.log" 2>/dev/null || \
    mv "$capture_dir/btsnoop_hci.log" "$capture_dir/btsnoop.log" 2>/dev/null || true

    local checkpoint_num=$(cat "$capture_dir/checkpoint_count.txt" 2>/dev/null || echo "0")
    echo "Session complete. Checkpoints: $checkpoint_num" >&2
    echo "Analyze with: python scripts/capture/extract_packets.py $capture_dir/btsnoop.log --checkpoints $capture_dir/checkpoints.txt" >&2

    # Output the btsnoop log path
    echo "$capture_dir/btsnoop.log"
}

full_connect_sequence() {
    echo "=== Full VMI Connect Sequence ==="
    launch_app
    select_vmci

    echo "Waiting for device to appear..."
    sleep 10
    screenshot /tmp/vmi_scan_result.png

    tap_pair
    sleep 3
    dismiss_update_dialog

    echo "=== Connected to VMI ==="
    screenshot /tmp/vmi_connected.png
}

# Usage
case "${1:-help}" in
    launch)     launch_app ;;
    vmci)       select_vmci ;;
    pair)       tap_pair ;;
    dismiss)    dismiss_update_dialog ;;
    menu)       tap_menu ;;
    config)     goto_configuration ;;
    simplified) goto_simplified_config ;;
    maintenance) goto_maintenance ;;
    sensors)    goto_sensor_management ;;
    available-info) goto_available_info ;;
    equipment-life) goto_equipment_life ;;
    measurements)   goto_measurements ;;
    measurements-full) goto_measurements_full ;;
    diagnostic) goto_diagnostic ;;
    special-modes) goto_special_modes ;;
    special-modes-full) goto_special_modes_full ;;
    holiday-toggle) holiday_toggle ;;
    holiday-days) holiday_set_days "$2" ;;
    holiday-test) holiday_capture_test "$2" ;;
    time-slots) goto_time_slots ;;
    sensor-probe1) tap_sensor_probe1 ;;
    sensor-probe2) tap_sensor_probe2 ;;
    sensor-remote) tap_sensor_remote ;;
    back)       back ;;
    screenshot) screenshot "$2" ;;
    scroll)     scroll_down ;;
    ui)         ui_dump ;;
    btstart)    start_btsnoop ;;
    btsnoop-enable) enable_btsnoop_full ;;
    btpull)     pull_btsnoop ;;
    session-start) session_start "$2" ;;
    session-checkpoint) session_checkpoint "$2" ;;
    session-end) session_end "$2" ;;
    collect-sensors) collect_sensors "$2" ;;
    should-collect) should_collect_sensors && echo "Yes, should collect" || echo "No, too recent" ;;
    connect)    full_connect_sequence ;;
    fan-min)    tap_fan_min ;;
    fan-mid)    tap_fan_mid ;;
    fan-max)    tap_fan_max ;;
    boost)      tap_boost ;;
    airflow-min) set_airflow_min ;;
    airflow-max) set_airflow_max ;;
    airflow)    drag_slider "${2:-0}" "${3:-100}" ;;
    resolution) echo "Detected resolution: $RESOLUTION" ;;
    *)
        echo "VMI App Control Script"
        echo "Detected resolution: $RESOLUTION"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Environment variables:"
        echo "  VMI_RESOLUTION  - Force screen resolution (e.g., 1080x2340)"
        echo "  VMI_ADB_TARGET  - ADB device serial (e.g., 192.168.1.100:5555)"
        echo ""
        echo "Connection:"
        echo "  launch      - Launch VMI+ app"
        echo "  vmci        - Tap VMCI button (select device type)"
        echo "  pair        - Tap PAIR button on scan results"
        echo "  dismiss     - Dismiss update dialog"
        echo "  connect     - Full connection sequence"
        echo ""
        echo "Navigation (from home -> menu):"
        echo "  menu        - Open hamburger menu"
        echo "  config      - Menu -> Configuration"
        echo "  simplified  - Configuration -> Simplified"
        echo "  maintenance - Menu -> Maintenance"
        echo "  sensors     - Menu -> Sensor management"
        echo ""
        echo "Navigation (Maintenance -> Available info):"
        echo "  available-info  - Maintenance -> Available info"
        echo "  equipment-life  - Available info -> Equipment life"
        echo "  measurements    - Available info -> Instantaneous measurements"
        echo "  measurements-full - Full navigation from home to measurements"
        echo "  diagnostic  - Available info -> Diagnostic"
        echo ""
        echo "Navigation (Configuration -> Special modes):"
        echo "  special-modes      - Tap Special modes (assumes already in Configuration)"
        echo "  special-modes-full - Full navigation from home to Special modes"
        echo ""
        echo "Holiday mode (from Special modes screen):"
        echo "  holiday-toggle     - Toggle Holiday mode ON/OFF"
        echo "  holiday-days <n>   - Set Holiday mode days (e.g., holiday-days 5)"
        echo "  holiday-test [n]   - Full capture test: reset BT, set n days, toggle, pull logs"
        echo ""
        echo "Fan speed (from home screen):"
        echo "  fan-min     - Set fan to MIN"
        echo "  fan-mid     - Set fan to MID"
        echo "  fan-max     - Set fan to MAX"
        echo "  boost       - Activate BOOST mode"
        echo ""
        echo "Slider (from simplified config screen):"
        echo "  airflow-min - Tap slider left"
        echo "  airflow-max - Tap slider right"
        echo "  airflow <from%> <to%> - Drag slider"
        echo ""
        echo "Utility:"
        echo "  back        - Press back button"
        echo "  scroll      - Scroll down"
        echo "  screenshot [file] - Take screenshot"
        echo "  ui          - Dump UI hierarchy"
        echo "  resolution  - Show detected resolution"
        echo ""
        echo "Bluetooth:"
        echo "  btsnoop-enable - Enable FULL BT snoop logging (via Developer Options)"
        echo "  btstart     - Enable BT snoop logging (via settings command only)"
        echo "  btpull      - Pull BT snoop logs"
        echo ""
        echo "Capture session (non-interactive, for CLI/agents):"
        echo "  session-start <name>  - Start session, outputs directory path"
        echo "  session-checkpoint <dir> - Take timestamped screenshot, outputs image path"
        echo "  session-end <dir>     - Pull btsnoop logs, outputs btsnoop.log path"
        echo ""
        echo "  Workflow: start -> navigate/checkpoint -> read screenshot -> write values -> end"
        echo "  Values should be appended to <dir>/checkpoints.txt after each checkpoint"
        echo ""
        echo "Sensor data collection (for protocol verification):"
        echo "  collect-sensors [--force] - Collect all sensor readings if 15+ min since last"
        echo "  should-collect  - Check if it's time to collect (15+ min since last)"
        echo ""
        echo "  NOTE: Run 'collect-sensors' at the start of debugging sessions to build"
        echo "  historical data for verifying protocol byte offsets (see GitHub issue #9)"
        ;;
esac
