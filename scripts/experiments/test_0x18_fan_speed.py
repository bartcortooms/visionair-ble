#!/usr/bin/env python3
"""Experiment: Does REQUEST param 0x18 change the physical fan speed?

See https://github.com/bartcortooms/visionair-ble/issues/22 for context.

Fully automated — uses the VMI+ phone app as ground truth.
No human observation needed.

Protocol:
  1. Disable the device schedule (prevents autonomous mode changes)
  2. Send 0x18 value=0 (LOW) via ESPHome proxy
  3. Launch VMI+ app on phone, screenshot home screen (shows current mode)
  4. Wait 3 minutes, verify LOW persists in DEVICE_STATE
  5. Send 0x18 value=2 (HIGH) via proxy
  6. Launch VMI+ app, screenshot home screen
  7. Wait 3 minutes, verify HIGH persists
  8. Re-enable the schedule

Prerequisites:
  - HA VisionAir integration DISABLED (device only accepts one BLE connection)
  - HA ESPHome proxy integration DISABLED (proxy only accepts one client)
  - Phone reachable via ADB (check with: adb -s $ADB_TARGET shell echo ok)
  - .env with VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY, ADB_TARGET

Run:
  cd visionair-ble
  uv run python scripts/experiments/test_0x18_fan_speed.py

What to look for in the screenshots:
  - The VMI+ app home screen shows three fan speed buttons (LOW/MEDIUM/HIGH)
  - The currently active mode is highlighted
  - If LOW screenshot shows LOW highlighted and HIGH screenshot shows HIGH
    highlighted, then 0x18 controls the fan speed
  - If both show the same mode, 0x18 only changes sensor routing

What to look for in the byte analysis:
  - Known sensor-routing bytes {32, 34, 47, 48, 60} are expected to change
  - Any OTHER DEVICE_STATE bytes changing would be new evidence
  - PROBE_SENSORS changes may indicate airflow differences (or just sensor drift)
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from visionair_ble.protocol import (
    MAGIC,
    AirflowLevel,
    PacketType,
    build_schedule_toggle,
    build_sensor_select_request,
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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=str(REPO_DIR))
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


async def ble_set_mode(mode: AirflowLevel, mode_name: str) -> bytes | None:
    """Connect via proxy, send 0x18, capture response, disconnect."""
    print(f"\n  BLE: Setting {mode_name}...")
    async with quick_connect() as client:
        sc, cc = find_chars(client)
        packet = build_sensor_select_request(mode)
        ds = await send_and_capture(client, cc, sc, packet, PacketType.DEVICE_STATE)
        if ds:
            status = parse_status(ds)
            print(f"  BLE: mode={status.airflow_mode}, indicator=0x{status.airflow_indicator:02x}, "
                  f"selector={status.sensor_selector}")
        else:
            print("  BLE: No response (command was sent)")
        return ds


async def ble_capture_state(label: str) -> dict:
    """Connect, read DEVICE_STATE + PROBE_SENSORS, disconnect."""
    async with quick_connect() as client:
        sc, cc = find_chars(client)
        ds = await send_and_capture(client, cc, sc, build_status_request(), PacketType.DEVICE_STATE)
        if ds:
            status = parse_status(ds)
            print(f"  [{label}] mode={status.airflow_mode}, indicator=0x{status.airflow_indicator:02x}")
        await asyncio.sleep(0.5)
        ps = await send_and_capture(client, cc, sc, build_sensor_request(), PacketType.PROBE_SENSORS)
        if ps:
            sensors = parse_sensors(ps)
            print(f"  [{label}] p1={sensors.temp_probe1}C, p2={sensors.temp_probe2}C")
    return {"device_state": ds, "probe_sensors": ps}


async def ble_schedule_toggle(enable: bool):
    """Connect, toggle schedule, disconnect."""
    async with quick_connect() as client:
        sc, cc = find_chars(client)
        await client.write_gatt_char(cc, build_schedule_toggle(enable), response=True)
        await asyncio.sleep(0.5)
    print(f"  BLE: Schedule {'enabled' if enable else 'disabled'}")


def phone_screenshot(output_dir: Path, filename: str) -> str:
    path = str(output_dir / filename)
    vmictl("screenshot", path)
    return path


def phone_stop():
    vmictl("stop")
    print("  Phone: App stopped")


def phone_connect():
    vmictl("connect")
    print("  Phone: Connected to device")


def hex_dump(data: bytes, label: str) -> str:
    lines = [f"--- {label} ({len(data)} bytes) ---"]
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        lines.append(f"  [{i:3d}] {hex_str}")
    return "\n".join(lines)


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
    print("EXPERIMENT: Does 0x18 change fan speed?")
    print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Output: {output_dir}")
    print(f"Wait per mode: {WAIT_MINUTES} min")
    print("=" * 60)

    schedule_disabled = False
    screenshots = {}
    snapshots = {}

    try:
        # === Step 1: Baseline + disable schedule ===
        print(f"\n{'='*60}")
        print("Step 1: Baseline + disable schedule")
        print(f"{'='*60}")
        phone_stop()
        await asyncio.sleep(2)
        snapshots["baseline"] = await ble_capture_state("baseline")
        await asyncio.sleep(2)
        await ble_schedule_toggle(False)
        schedule_disabled = True
        await asyncio.sleep(3)

        # === Step 2: Set LOW ===
        print(f"\n{'='*60}")
        print("Step 2: Set LOW via 0x18")
        print(f"{'='*60}")
        snapshots["low_immediate"] = {"device_state": await ble_set_mode(AirflowLevel.LOW, "LOW")}
        await asyncio.sleep(2)
        snapshots["low_verify"] = await ble_capture_state("low-verify")
        await asyncio.sleep(2)

        # === Step 3: Phone screenshot at LOW ===
        print(f"\n{'='*60}")
        print("Step 3: Phone app screenshot (expect LOW)")
        print(f"{'='*60}")
        phone_connect()
        await asyncio.sleep(3)
        screenshots["low"] = phone_screenshot(output_dir, "low_mode.png")
        print(f"  Screenshot: {screenshots['low']}")
        phone_stop()
        await asyncio.sleep(3)

        # === Step 4: Wait, verify LOW persists ===
        print(f"\n{'='*60}")
        print(f"Step 4: Wait {WAIT_MINUTES} min, verify LOW persists")
        print(f"{'='*60}")
        for remaining in range(WAIT_MINUTES * 60, 0, -30):
            await asyncio.sleep(30)
            if remaining > 30:
                print(f"  {remaining // 60}m {remaining % 60}s remaining...")
        snapshots["low_after_wait"] = await ble_capture_state(f"low-{WAIT_MINUTES}min")
        await asyncio.sleep(2)

        # === Step 5: Set HIGH ===
        print(f"\n{'='*60}")
        print("Step 5: Set HIGH via 0x18")
        print(f"{'='*60}")
        snapshots["high_immediate"] = {"device_state": await ble_set_mode(AirflowLevel.HIGH, "HIGH")}
        await asyncio.sleep(2)
        snapshots["high_verify"] = await ble_capture_state("high-verify")
        await asyncio.sleep(2)

        # === Step 6: Phone screenshot at HIGH ===
        print(f"\n{'='*60}")
        print("Step 6: Phone app screenshot (expect HIGH)")
        print(f"{'='*60}")
        phone_connect()
        await asyncio.sleep(3)
        screenshots["high"] = phone_screenshot(output_dir, "high_mode.png")
        print(f"  Screenshot: {screenshots['high']}")
        phone_stop()
        await asyncio.sleep(3)

        # === Step 7: Wait, verify HIGH persists ===
        print(f"\n{'='*60}")
        print(f"Step 7: Wait {WAIT_MINUTES} min, verify HIGH persists")
        print(f"{'='*60}")
        for remaining in range(WAIT_MINUTES * 60, 0, -30):
            await asyncio.sleep(30)
            if remaining > 30:
                print(f"  {remaining // 60}m {remaining % 60}s remaining...")
        snapshots["high_after_wait"] = await ble_capture_state(f"high-{WAIT_MINUTES}min")
        await asyncio.sleep(2)

        # === Step 8: Re-enable schedule ===
        print(f"\n{'='*60}")
        print("Step 8: Re-enable schedule")
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

    # === ANALYSIS ===
    print(f"\n{'='*60}")
    print("ANALYSIS")
    print(f"{'='*60}")

    low_ds = snapshots.get("low_after_wait", {}).get("device_state")
    high_ds = snapshots.get("high_after_wait", {}).get("device_state")

    if low_ds and high_ds:
        print(hex_dump(low_ds, "LOW DEVICE_STATE"))
        print()
        print(hex_dump(high_ds, "HIGH DEVICE_STATE"))
        print()

        known_sensor_bytes = {32, 34, 47, 48, 60}
        diffs_known = []
        diffs_unknown = []
        for i in range(min(len(low_ds), len(high_ds))):
            if low_ds[i] != high_ds[i]:
                (diffs_known if i in known_sensor_bytes else diffs_unknown).append(i)
                print(f"  byte[{i:3d}]: LOW=0x{low_ds[i]:02x} HIGH=0x{high_ds[i]:02x}"
                      f"  {'(known)' if i in known_sensor_bytes else '*** NEW ***'}")

        print(f"\n  Known sensor-routing bytes changed: {diffs_known}")
        print(f"  Unknown bytes changed: {diffs_unknown}")

    low_ps = snapshots.get("low_after_wait", {}).get("probe_sensors")
    high_ps = snapshots.get("high_after_wait", {}).get("probe_sensors")
    if low_ps and high_ps:
        ps_diffs = [(i, low_ps[i], high_ps[i]) for i in range(min(len(low_ps), len(high_ps))) if low_ps[i] != high_ps[i]]
        if ps_diffs:
            print(f"\n  PROBE_SENSORS diffs:")
            for i, lv, hv in ps_diffs:
                print(f"    byte[{i}]: LOW=0x{lv:02x} HIGH=0x{hv:02x}")

    if low_ds:
        s = parse_status(low_ds)
        print(f"\n  LOW persisted {WAIT_MINUTES} min? {'YES' if s.airflow_mode == 'low' else 'NO: ' + s.airflow_mode}")
    if high_ds:
        s = parse_status(high_ds)
        print(f"  HIGH persisted {WAIT_MINUTES} min? {'YES' if s.airflow_mode == 'high' else 'NO: ' + s.airflow_mode}")

    print(f"\n  Screenshots:")
    for label, path in screenshots.items():
        print(f"    {label}: {path}")

    print(f"\n  Output directory: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
