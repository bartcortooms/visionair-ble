#!/usr/bin/env python3
"""Listen test: Toggle LOW/HIGH via 0x18 and listen for fan speed change.

A human stands near the VMI and listens while this script toggles modes.
No phone needed. Clear announcements of each transition.

Sequence:
  1. Disable schedule
  2. Set HIGH — hold 90s (baseline)
  3. Switch to LOW — hold 90s (listen for change)
  4. Switch to HIGH — hold 90s (listen for change back)
  5. Switch to LOW — hold 90s (confirm)
  6. Re-enable schedule

Run:
  cd visionair-ble
  uv run python scripts/experiments/test_0x18_listen.py
"""

import asyncio
import functools
import os
import subprocess
import sys
import time
from pathlib import Path

print = functools.partial(print, flush=True)

from visionair_ble.protocol import (
    MAGIC,
    AirflowLevel,
    PacketType,
    build_schedule_toggle,
    build_sensor_select_request,
    build_status_request,
    parse_status,
)
from visionair_ble.connect import connect_via_proxy

REPO_DIR = Path(__file__).resolve().parent.parent.parent


def announce(text: str):
    """Speak text aloud and print it."""
    print(f"\n  🔊 {text}")
    subprocess.Popen(["spd-say", "-w", text], stderr=subprocess.DEVNULL)


def load_dotenv():
    env_path = REPO_DIR / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def ts():
    return time.strftime("%H:%M:%S")


async def send_and_read(client, cc, sc, packet):
    result = None
    event = asyncio.Event()

    def handler(*args):
        nonlocal result
        data = bytes(args[-1])
        if len(data) >= 3 and bytes(data[:2]) == b"\xa5\xb6" and data[2] == PacketType.DEVICE_STATE:
            result = data
            event.set()

    await client.start_notify(sc, handler)
    try:
        await client.write_gatt_char(cc, packet, response=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=10.0)
        except TimeoutError:
            pass
    finally:
        try:
            await client.stop_notify(sc)
        except Exception:
            pass
    return result


async def main():
    load_dotenv()
    mac = os.environ.get("VISIONAIR_MAC")
    host = os.environ.get("ESPHOME_PROXY_HOST")
    key = os.environ.get("ESPHOME_API_KEY")

    if not all([mac, host, key]):
        print("ERROR: Set VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY in .env")
        sys.exit(1)

    SC_UUID = "0003caa2-0000-1000-8000-00805f9b0131"
    CC_UUID = "0003cbb1-0000-1000-8000-00805f9b0131"
    HOLD_SECONDS = 90

    def connect():
        return connect_via_proxy(host, key, device_address=mac)

    def find_chars(client):
        sc = cc = None
        for svc in client.services:
            for c in svc.characteristics:
                if c.uuid == SC_UUID:
                    sc = c
                elif c.uuid == CC_UUID:
                    cc = c
        return sc, cc

    async def set_mode(mode, name):
        async with connect() as client:
            sc, cc = find_chars(client)
            ds = await send_and_read(client, cc, sc, build_sensor_select_request(mode))
            if ds:
                s = parse_status(ds)
                print(f"  [{ts()}] BLE confirms: mode={s.airflow_mode}, indicator=0x{s.airflow_indicator:02x}")

    async def schedule(enable):
        async with connect() as client:
            _, cc = find_chars(client)
            await client.write_gatt_char(cc, build_schedule_toggle(enable), response=True)
            await asyncio.sleep(0.5)

    async def hold(seconds, label):
        for remaining in range(seconds, 0, -10):
            print(f"  [{ts()}] {label} — {remaining}s remaining")
            await asyncio.sleep(10)

    print()
    print("=" * 50)
    print("  LISTEN TEST: 0x18 fan speed")
    print("  Stand near the VMI and listen.")
    print(f"  Each mode held for {HOLD_SECONDS}s.")
    print("=" * 50)

    schedule_disabled = False
    try:
        announce("Starting listen test. Disabling schedule.")
        print(f"\n[{ts()}] Disabling schedule...")
        await schedule(False)
        schedule_disabled = True
        await asyncio.sleep(2)

        # Phase 1: HIGH baseline
        print(f"\n{'='*50}")
        print(f"  >>> SETTING HIGH (baseline)")
        print(f"{'='*50}")
        announce("Setting HIGH. This is the baseline.")
        await set_mode(AirflowLevel.HIGH, "HIGH")
        await asyncio.sleep(2)
        await hold(HOLD_SECONDS, "HIGH")

        # Phase 2: Switch to LOW
        print(f"\n{'='*50}")
        print(f"  >>> SWITCHING TO LOW")
        print(f"{'='*50}")
        announce("Switching to LOW now.")
        await set_mode(AirflowLevel.LOW, "LOW")
        await asyncio.sleep(2)
        await hold(HOLD_SECONDS, "LOW")

        # Phase 3: Switch back to HIGH
        print(f"\n{'='*50}")
        print(f"  >>> SWITCHING TO HIGH")
        print(f"{'='*50}")
        announce("Switching to HIGH now.")
        await set_mode(AirflowLevel.HIGH, "HIGH")
        await asyncio.sleep(2)
        await hold(HOLD_SECONDS, "HIGH")

        # Phase 4: Switch to LOW again
        print(f"\n{'='*50}")
        print(f"  >>> SWITCHING TO LOW (confirm)")
        print(f"{'='*50}")
        announce("Switching to LOW again to confirm.")
        await set_mode(AirflowLevel.LOW, "LOW")
        await asyncio.sleep(2)
        await hold(HOLD_SECONDS, "LOW")

        # Cleanup
        print(f"\n[{ts()}] Re-enabling schedule...")
        await schedule(True)
        schedule_disabled = False

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        if schedule_disabled:
            try:
                await schedule(True)
            except Exception:
                print("  WARNING: Failed to re-enable schedule!")
        raise

    announce("Test complete.")
    print(f"\n{'='*50}")
    print("  DONE. What did you hear?")
    print("  - Fan speed changed → 0x18 controls fan speed")
    print("  - No change → 0x18 only changes sensor routing")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
