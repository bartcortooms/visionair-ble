#!/usr/bin/env python3
"""Experiment: Does REQUEST param 0x18 change the physical fan speed?

See https://github.com/bartcortooms/visionair-ble/issues/22 for context.

Fully automated — uses the VMI+ phone app as ground truth.
No human observation needed.

Protocol (A/B/A/B with post-screenshot readbacks):
  1. Disable schedule, verify OFF via BLE readback
  2. Force-stop phone app
  -- Phase A1 (LOW) --
  3. Send 0x18=LOW, BLE readback (immediate)
  4. Wait 3 min with 30s BLE readbacks (persistence, no phone)
  5. Phone screenshot (home screen), then force-stop
  6. BLE readback (detect phone side effects)
  -- Phase B1 (HIGH) --
  7. Send 0x18=HIGH, BLE readback (immediate)
  8. Wait 3 min with 30s BLE readbacks (persistence, no phone)
  9. Phone screenshot (home screen), then force-stop
  10. BLE readback (detect phone side effects)
  -- Phase A2 (LOW) --
  11-14. Repeat A1
  -- Phase B2 (HIGH) --
  15-18. Repeat B1
  -- Cleanup --
  19. Re-enable schedule

IMPORTANT: The phone app must NOT connect during persistence checks.
The phone may send initialization commands that override the mode.

Prerequisites:
  - HA VisionAir integration DISABLED
  - HA ESPHome proxy integration DISABLED
  - Phone reachable via ADB (check with: adb -s $ADB_TARGET shell echo ok)
  - .env with VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY, ADB_TARGET
"""

import asyncio
import functools
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Force unbuffered output so progress is visible when piped/redirected.
print = functools.partial(print, flush=True)

from visionair_ble.protocol import (
    MAGIC,
    AirflowLevel,
    PacketType,
    build_schedule_toggle,
    build_mode_select_request,
    build_status_request,
    build_sensor_request,
    parse_status,
    parse_sensors,
)
from visionair_ble.connect import connect_via_proxy

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent.parent
VMICTL = REPO_DIR / "scripts" / "capture" / "vmictl.py"

MAC = PROXY_HOST = API_KEY = None


def load_dotenv():
    env_path = REPO_DIR / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def vmictl(*args) -> str:
    """Run a vmictl command and return stdout."""
    cmd = [str(VMICTL)] + list(args)
    print(f"  $ vmictl {' '.join(args)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(REPO_DIR))
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            if "BATTERY" in line:
                print(f"  WARNING: {line}")
            elif line.strip():
                print(f"  stderr: {line}")
    return result.stdout.strip()


def quick_connect():
    return connect_via_proxy(PROXY_HOST, API_KEY, device_address=MAC)


def find_chars(client):
    sc = cc = None
    for svc in client.services:
        for c in svc.characteristics:
            if c.uuid == "0003caa2-0000-1000-8000-00805f9b0131":
                sc = c
            elif c.uuid == "0003cbb1-0000-1000-8000-00805f9b0131":
                cc = c
    return sc, cc


async def send_and_capture(client, cc, sc, packet, ptype, timeout=10.0):
    """Send a BLE packet and wait for a specific response type."""
    result = None
    event = asyncio.Event()

    def handler(*args):
        nonlocal result
        data = bytes(args[-1])
        if len(data) >= 3 and bytes(data[:2]) == MAGIC and data[2] == ptype:
            result = data
            event.set()

    await client.start_notify(sc, handler)
    try:
        await client.write_gatt_char(cc, packet, response=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            print("    (timeout waiting for response)")
    finally:
        try:
            await client.stop_notify(sc)
        except Exception:
            pass
    return result


def ts():
    """Current timestamp string."""
    return time.strftime("%H:%M:%S")


async def ble_set_mode(mode: AirflowLevel, mode_name: str) -> dict:
    """Connect via proxy, send 0x18, capture response, disconnect."""
    print(f"\n  [{ts()}] BLE: Setting {mode_name}...")
    async with quick_connect() as client:
        sc, cc = find_chars(client)
        packet = build_mode_select_request(mode)
        ds = await send_and_capture(client, cc, sc, packet, PacketType.DEVICE_STATE)
        entry = {"timestamp": ts(), "action": f"set_{mode_name}"}
        if ds:
            status = parse_status(ds)
            entry["mode"] = status.airflow_mode
            entry["indicator"] = f"0x{status.airflow_indicator:02x}"
            entry["selector"] = status.mode_selector
            entry["raw_hex"] = ds.hex()
            print(f"  [{ts()}] BLE: mode={status.airflow_mode}, indicator={entry['indicator']}, "
                  f"selector={status.mode_selector}")
        else:
            entry["mode"] = None
            print(f"  [{ts()}] BLE: No response (command was sent)")
        return entry


async def ble_readback(label: str) -> dict:
    """Connect, read DEVICE_STATE + PROBE_SENSORS, disconnect."""
    async with quick_connect() as client:
        sc, cc = find_chars(client)
        ds = await send_and_capture(client, cc, sc, build_status_request(), PacketType.DEVICE_STATE)
        entry = {"timestamp": ts(), "label": label}
        if ds:
            status = parse_status(ds)
            entry["mode"] = status.airflow_mode
            entry["indicator"] = f"0x{status.airflow_indicator:02x}"
            entry["selector"] = status.mode_selector
            entry["ds_hex"] = ds.hex()
            print(f"  [{ts()}] [{label}] mode={status.airflow_mode}, indicator={entry['indicator']}")
        await asyncio.sleep(0.5)
        ps = await send_and_capture(client, cc, sc, build_sensor_request(), PacketType.PROBE_SENSORS)
        if ps:
            sensors = parse_sensors(ps)
            entry["p1_temp"] = sensors.temp_probe1
            entry["p2_temp"] = sensors.temp_probe2
            entry["ps_hex"] = ps.hex()
            print(f"  [{ts()}] [{label}] p1={sensors.temp_probe1}C, p2={sensors.temp_probe2}C")
    return entry


async def ble_schedule_toggle(enable: bool):
    """Connect, toggle schedule, disconnect."""
    async with quick_connect() as client:
        sc, cc = find_chars(client)
        await client.write_gatt_char(cc, build_schedule_toggle(enable), response=True)
        await asyncio.sleep(0.5)
    print(f"  [{ts()}] BLE: Schedule {'enabled' if enable else 'disabled'}")


def phone_screenshot(output_dir: Path, filename: str) -> str:
    path = str(output_dir / filename)
    vmictl("screenshot", path)
    return path


def phone_stop():
    vmictl("stop")
    print(f"  [{ts()}] Phone: App stopped")


def phone_connect():
    vmictl("connect")
    print(f"  [{ts()}] Phone: Connected to device")


def hex_dump(data: bytes, label: str) -> str:
    lines = [f"--- {label} ({len(data)} bytes) ---"]
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        lines.append(f"  [{i:3d}] {hex_str}")
    return "\n".join(lines)


async def run_phase(
    phase_name: str,
    mode: AirflowLevel,
    mode_name: str,
    wait_minutes: int,
    output_dir: Path,
    log: list,
):
    """Run one phase of the A/B/A/B experiment.

    Returns dict with all collected data for this phase.
    """
    phase = {"name": phase_name, "mode": mode_name, "readbacks": []}

    print(f"\n{'='*60}")
    print(f"Phase {phase_name}: Set {mode_name}")
    print(f"{'='*60}")

    # 1. Set mode
    phase["set_result"] = await ble_set_mode(mode, mode_name)
    await asyncio.sleep(2)

    # 2. Immediate verify
    rb = await ble_readback(f"{phase_name}-immediate")
    phase["readbacks"].append(rb)
    await asyncio.sleep(2)

    # 3. Periodic readbacks during wait (no phone!)
    print(f"\n  Waiting {wait_minutes} min with 30s readbacks...")
    for i in range(wait_minutes * 2):
        await asyncio.sleep(30)
        elapsed = (i + 1) * 30
        rb = await ble_readback(f"{phase_name}-{elapsed}s")
        phase["readbacks"].append(rb)
        await asyncio.sleep(2)

    # 4. Phone screenshot
    print(f"\n  [{ts()}] Connecting phone for screenshot...")
    phone_connect()
    await asyncio.sleep(3)
    screenshot_file = f"{phase_name}_{mode_name}.png"
    phase["screenshot"] = phone_screenshot(output_dir, screenshot_file)
    print(f"  Screenshot: {phase['screenshot']}")
    phone_stop()
    await asyncio.sleep(3)

    # 5. Post-screenshot BLE readback (detect phone side effects)
    phase["post_screenshot"] = await ble_readback(f"{phase_name}-post-screenshot")
    await asyncio.sleep(2)

    # Check: did the phone change the mode?
    pre_mode = phase["readbacks"][-1].get("mode")
    post_mode = phase["post_screenshot"].get("mode")
    if pre_mode and post_mode and pre_mode != post_mode:
        print(f"  *** PHONE SIDE EFFECT: mode changed from {pre_mode} to {post_mode} ***")
        phase["phone_side_effect"] = True
    else:
        phase["phone_side_effect"] = False

    log.append(phase)
    return phase


async def main():
    global MAC, PROXY_HOST, API_KEY
    load_dotenv()

    MAC = os.environ.get("VISIONAIR_MAC")
    PROXY_HOST = os.environ.get("ESPHOME_PROXY_HOST")
    API_KEY = os.environ.get("ESPHOME_API_KEY")

    if not all([MAC, PROXY_HOST, API_KEY]):
        print("ERROR: Set VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY in .env")
        sys.exit(1)

    WAIT_MINUTES = 3
    output_dir = REPO_DIR / "data" / "captures" / f"0x18_fan_speed_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("EXPERIMENT: Does 0x18 change fan speed? (A/B/A/B)")
    print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Output: {output_dir}")
    print(f"Wait per phase: {WAIT_MINUTES} min")
    print(f"Phases: A1(LOW) → B1(HIGH) → A2(LOW) → B2(HIGH)")
    print("=" * 60)

    schedule_disabled = False
    log = []

    try:
        # === Setup ===
        print(f"\n{'='*60}")
        print("Setup: Disable schedule, force-stop phone")
        print(f"{'='*60}")
        phone_stop()
        await asyncio.sleep(2)

        baseline = await ble_readback("baseline")
        log.append({"name": "baseline", "readback": baseline})
        await asyncio.sleep(2)

        await ble_schedule_toggle(False)
        schedule_disabled = True
        await asyncio.sleep(3)

        # Verify schedule is off via readback
        post_toggle = await ble_readback("post-schedule-off")
        log.append({"name": "schedule_off", "readback": post_toggle})
        await asyncio.sleep(2)

        # === A/B/A/B phases ===
        phases = [
            ("A1", AirflowLevel.LOW, "LOW"),
            ("B1", AirflowLevel.HIGH, "HIGH"),
            ("A2", AirflowLevel.LOW, "LOW"),
            ("B2", AirflowLevel.HIGH, "HIGH"),
        ]

        for phase_name, mode, mode_name in phases:
            await run_phase(phase_name, mode, mode_name, WAIT_MINUTES, output_dir, log)

        # === Cleanup ===
        print(f"\n{'='*60}")
        print("Cleanup: Re-enable schedule")
        print(f"{'='*60}")
        await ble_schedule_toggle(True)
        schedule_disabled = False

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        if schedule_disabled:
            print("Re-enabling schedule...")
            try:
                await ble_schedule_toggle(True)
                schedule_disabled = False
            except Exception:
                print("  WARNING: Failed to re-enable schedule!")
        try:
            phone_stop()
        except Exception:
            pass
        raise

    # === Save raw log ===
    log_path = output_dir / "experiment_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"\n  Raw log saved to: {log_path}")

    # === ANALYSIS ===
    print(f"\n{'='*60}")
    print("ANALYSIS")
    print(f"{'='*60}")

    # Summarize each phase
    for entry in log:
        if "readbacks" not in entry:
            continue
        phase = entry
        name = phase["name"]
        target = phase["mode"]
        readbacks = phase["readbacks"]

        # Did target mode persist through all readbacks?
        modes = [rb.get("mode") for rb in readbacks if rb.get("mode")]
        persisted = all(m == target.lower() for m in modes)
        print(f"\n  Phase {name} ({target}):")
        print(f"    Set result: {phase['set_result'].get('mode')}")
        print(f"    Readbacks ({len(modes)}): {', '.join(modes)}")
        print(f"    Persisted: {'YES' if persisted else 'NO'}")
        print(f"    Phone side effect: {phase['phone_side_effect']}")
        post = phase["post_screenshot"].get("mode")
        print(f"    Post-screenshot mode: {post}")

    # Byte diffs between final LOW and HIGH states
    a1 = next((e for e in log if e.get("name") == "A1"), None)
    b1 = next((e for e in log if e.get("name") == "B1"), None)
    if a1 and b1:
        low_hex = a1["readbacks"][-1].get("ds_hex")
        high_hex = b1["readbacks"][-1].get("ds_hex")
        if low_hex and high_hex:
            low_ds = bytes.fromhex(low_hex)
            high_ds = bytes.fromhex(high_hex)
            print(f"\n  DEVICE_STATE byte diffs (A1 LOW vs B1 HIGH):")
            known_sensor_bytes = {32, 34, 47, 48, 60}
            for i in range(min(len(low_ds), len(high_ds))):
                if low_ds[i] != high_ds[i]:
                    tag = "(known)" if i in known_sensor_bytes else "*** NEW ***"
                    print(f"    byte[{i:3d}]: LOW=0x{low_ds[i]:02x} HIGH=0x{high_ds[i]:02x}  {tag}")

    print(f"\n  Output directory: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
