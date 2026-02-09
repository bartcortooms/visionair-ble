# Guidelines for AI Agents

## Project Overview

VisionAir BLE is a Python library for communicating with Ventilairsec VisionAir ventilation devices over Bluetooth Low Energy. The protocol was reverse-engineered from BLE traffic captures.

## Privacy & Public Communication (critical)

- Treat GitHub issues, PRs, and commit messages in public repos as **public**.
- Never post private/internal identifiers in public text (LAN IPs, private hostnames, ADB targets, tokens, keys, MAC addresses, email/phone, exact home network details).
- If technical context is needed, redact values (for example: `<private-ip>:<port>`).
- If private details were posted accidentally, **delete and repost redacted** (editing may preserve history).
- For GitHub issue/PR comments and PR bodies, use `gh ... --body-file` with a heredoc (`<<'EOF'`) instead of inline `--body "..."` strings, so markdown/newlines render correctly and content is not mangled by shell interpolation.

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

E2E tests require a real VisionAir device. Configuration via `.env` or CLI flags:
- `VISIONAIR_MAC` - VisionAir device MAC address (or `--device-address`)
- `ESPHOME_PROXY_HOST` - ESPHome BLE proxy IP address (or `--proxy-host`)
- `ESPHOME_API_KEY` - ESPHome API encryption key (or `--proxy-key`)

**Runtime:** E2E tests take approximately **4 minutes** due to BLE connection setup, proxy recovery delays between tests, and the reliability test running multiple iterations.

**Important:** The VisionAir device only supports one BLE connection at a time. Before running E2E tests:
1. **Disable Home Assistant's BLE proxy integration** - HA must not be using the ESPHome proxy
2. **Disconnect the phone** - Either disable Bluetooth on the phone (`adb shell svc bluetooth disable`) or force-stop the VMI app (`adb shell am force-stop com.ventilairsec.ventilairsecinstallateur`)

Most tests are read-only. The holiday mode test (`TestHolidayMode`) briefly activates and then clears holiday mode, always cleaning up in a `finally` block.

## Code Style

### Write for newcomers, not for historians
- Code comments and docs describe **what things are now**, never what they used to be or how they changed
- A reader unfamiliar with the project's history should be able to understand everything without context about past mistakes or refactors
- Do not add backward compatibility aliases or shims — this library has no real users
- Never use phrases like "formerly known as", "was previously", "NOT X (see Y)", "changed from", "used to be", "was wrong"
- If you need to record *why* something changed, put that in `docs/logbook/` — not in code comments or docs
- Code history is in git; discoveries and investigations go in the logbook; code and docs only describe the present

### Naming
- Use names that accurately reflect the actual purpose/content
- Rename things when we discover the current name is misleading
- Do not keep old names around "for compatibility"

## Logbook

Maintain a logbook under `docs/logbook/` to record discoveries, work done, and notes for later. Use `date +%Y-%m-%d` to get today's date and create entries as `docs/logbook/YYYY-MM-DD.md`. Include:
- What was investigated or implemented
- Key discoveries and findings
- Open questions and things to revisit
- Raw observations that might be useful later

## VMI Control Script (`scripts/capture/vmictl.py`)

Continuously improve `vmictl.py` as issues are encountered during capture sessions. When a command fails, produces wrong coordinates, or a needed command is missing, fix the script before retrying manually. The skill documentation (`.claude/skills/vmi-reverse-engineering/`) should stay in sync with the actual script capabilities.

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

### Schedule interference

The device has an internal 24-hour schedule (written via 0x40 packets) that it
enforces autonomously. If a manual mode change conflicts with the active
schedule slot, the device may revert to the scheduled mode within seconds —
without any phone command. This can silently confuse test results: you send a
mode change, the device confirms it, and then 30 seconds later the device
reports a different mode.

**Always account for the schedule when testing mode changes.** Either disable
the schedule first (`build_schedule_toggle(False)`), or ensure your test mode
matches the current schedule slot. Otherwise you may attribute device-initiated
mode changes to phone commands or "sensor polling."
