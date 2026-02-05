# Guidelines for AI Agents

## Project Overview

VisionAir BLE is a Python library for communicating with Ventilairsec VisionAir ventilation devices over Bluetooth Low Energy. The protocol was reverse-engineered from BLE traffic captures.

## Key Files

- `src/visionair_ble/protocol.py` - Protocol definitions and packet parsing
- `docs/protocol.md` - Protocol specification
- `scripts/capture/` - Tools for capturing and analyzing BLE traffic

## Running Tests

```bash
pytest
```

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

When naming protocol elements:
- Use names that describe actual content/behavior
- Update names when we learn more about what something actually does
- Do not attribute names to "the vendor" - we created all the names
