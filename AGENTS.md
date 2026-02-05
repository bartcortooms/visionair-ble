# Guidelines for AI Agents

## Project Overview

VisionAir BLE is a Python library for communicating with Ventilairsec VisionAir ventilation devices over Bluetooth Low Energy. The protocol was reverse-engineered from BLE traffic captures.

## Key Files

- `src/visionair_ble/protocol.py` - Protocol definitions and packet parsing
- `docs/protocol.md` - Protocol specification
- `scripts/capture/` - Tools for capturing and analyzing BLE traffic

## Running Tests

Use `uv` for running tests, scripts, and Python commands:

```bash
# Unit tests
uv run pytest

# E2E tests (requires device to be powered on and in range)
uv run pytest -m e2e -v
```

### E2E Tests

E2E tests require a real VisionAir device. Configuration is in `.env`:
- `PROXY_HOST` - ESPHome BLE proxy IP address
- `PROXY_KEY` - ESPHome API encryption key
- `DEVICE_ADDRESS` - VisionAir device MAC address

**Important:** The VisionAir device only supports one BLE connection at a time. Before running E2E tests:
1. **Disable Home Assistant's BLE proxy integration** - HA must not be using the ESPHome proxy
2. **Disconnect the phone** - Either disable Bluetooth on the phone (`adb shell svc bluetooth disable`) or force-stop the VMI app (`adb shell am force-stop com.ventilairsec.ventilairsecinstallateur`)

The tests are read-only and do not modify device settings.

## Code Style

### Keep code clean and evergreen
- Do not add backward compatibility aliases or shims - this library has no real users
- Do not reference what things were "formerly" called or historical naming
- Comments should describe what code does now, not its history

### Comments
- Keep comments concise and relevant
- Do not add unnecessary historical context
- Avoid phrases like "formerly known as", "was previously", "vendor calls it"

### Naming
- Use names that accurately reflect the actual purpose/content
- Rename things when we discover the current name is misleading
- Do not keep old names around "for compatibility"

## Protocol Reverse Engineering

This is a reverse-engineered protocol. We have no vendor documentation.
All names and interpretations are our own based on observed behavior.
The VMI mobile app is the only authoritative source for protocol behavior.
Always verify assumptions by capturing and analyzing VMI app traffic before
changing protocol interpretations or implementation details.

When naming protocol elements:
- Use names that describe actual content/behavior
- Update names when we learn more about what something actually does
- Do not attribute names to "the vendor" - we created all the names
