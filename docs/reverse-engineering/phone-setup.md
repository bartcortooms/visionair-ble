# Phone Setup for BLE Capture

This guide explains how to set up an Android phone for capturing BLE traffic from the VisionAir device.

## Requirements

- Android phone with:
  - Developer options enabled
  - ADB debugging enabled (USB or WiFi)
  - VMI+ app: `com.ventilairsec.ventilairsecinstallateur`
- ADB installed on your computer

## Environment Setup

Copy `.env.example` to `.env` and configure your values:

```bash
cp .env.example .env
```

Required variables:
- `VMI_MAC` - Your device's MAC address (format: `00:A0:50:XX:XX:XX`)

Optional variables:
- `VMI_ADB_TARGET` - ADB device serial (e.g., `192.168.1.100:5555` for WiFi ADB)
- `VMI_RESOLUTION` - Force screen resolution (auto-detected if not set)
- `ESPHOME_PROXY_HOST` - ESPHome BLE proxy IP (for remote BLE access)
- `ESPHOME_API_KEY` - ESPHome API key

## Connecting via ADB

### USB Connection

```bash
adb devices
```

### WiFi Connection

1. Connect phone via USB first
2. Enable TCP/IP mode:
   ```bash
   adb tcpip 5555
   ```
3. Disconnect USB and connect over WiFi:
   ```bash
   adb connect <phone-ip>:5555
   ```

### Multiple Devices

If multiple ADB devices are connected, specify the target:

```bash
VMI_ADB_TARGET=<ip>:5555 ./scripts/capture/app_control.sh <command>
```

## Enabling Bluetooth HCI Snoop Logging

### Via App Control Script

```bash
./scripts/capture/app_control.sh btstart
```

### Manual Steps (Required for Full Captures)

The script enables logging via `settings`, but for **full packet captures** (not filtered/truncated), you must also:

1. Open **Settings → Developer Options**
2. Find **Enable Bluetooth HCI snoop log**
3. Select **"Enabled"** (NOT "Enabled Filtered" or other filtered modes)
4. Toggle Bluetooth off and on

Without this, you'll get `btsnooz` format (compressed/truncated) instead of full `btsnoop`.

## Pulling BLE Logs

```bash
./scripts/capture/app_control.sh btpull
```

This creates a bugreport and extracts the btsnoop log to `/tmp/vmi_btlogs/`.

### Manual Extraction

If the script fails, manually pull the bugreport:

```bash
adb bugreport /tmp/bugreport.zip
unzip -jo /tmp/bugreport.zip "*/btsnoop_hci.log" -d /tmp/
# or for btsnooz format:
unzip -jo /tmp/bugreport.zip "*/btsnooz_hci.log" -d /tmp/
```

## Converting btsnooz to btsnoop

If you get a `btsnooz_hci.log` file (compressed format), convert it:

```bash
python scripts/capture/btsnooz.py /tmp/btsnooz_hci.log /tmp/btsnoop.log
```

## App Control Commands

The app control script automates UI interactions:

```bash
./scripts/capture/app_control.sh help
```

Key commands:
- `connect` - Full connection sequence (launch → scan → pair → dismiss)
- `screenshot [file]` - Take screenshot
- `menu` - Open hamburger menu
- `measurements-full` - Navigate to temperature/humidity readings
- `boost` - Activate BOOST mode
- `btstart` - Enable BT snoop logging
- `btpull` - Pull BT snoop logs
- `resolution` - Show detected screen resolution

## Adding Support for New Screen Resolutions

The script uses coordinate mappings per screen resolution. The resolution is auto-detected via `adb shell wm size`.

To add support for a new resolution:

1. Get the screen resolution:
   ```bash
   adb shell wm size
   ```

2. Use uiautomator to find element coordinates:
   ```bash
   adb shell uiautomator dump
   adb shell cat /sdcard/window_dump.xml
   ```

3. Add a new case in the `get_coords()` function in `scripts/capture/app_control.sh`:
   ```bash
   1234x5678)
       case "$func" in
           vmci)       echo "XXX YYY" ;;
           pair)       echo "XXX YYY" ;;
           # ... add all coordinates
       esac
       ;;
   ```

Currently supported resolutions:
- `1080x2340`
- `1116x2484`

## Troubleshooting

### "more than one device/emulator"

Set `VMI_ADB_TARGET` to specify which device:
```bash
VMI_ADB_TARGET=<serial> ./scripts/capture/app_control.sh <command>
```

### No btsnoop log in bugreport

1. Ensure BT HCI snoop is enabled in Developer Options (not just via `settings`)
2. Select "Enabled" mode, not a filtered mode
3. Toggle Bluetooth off/on after enabling
4. Perform some BLE activity before pulling the log

### Truncated/filtered packets

Some phones only support filtered captures by default. Check:
- Developer Options for unfiltered mode
- Different phones may have different capabilities

### Wrong tap coordinates

If taps are hitting the wrong elements:
1. Check your resolution: `./scripts/capture/app_control.sh resolution`
2. If not supported, add coordinates for your resolution (see above)
3. Or set `VMI_RESOLUTION` to force a similar resolution
