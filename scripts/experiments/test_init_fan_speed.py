#!/usr/bin/env python3
"""Test whether the phone's initialization sequence enables 0x18 fan control.

Monitors HA power sensors to detect physical fan speed changes without
needing a human listener.

Experiment design:
  1. Baseline: monitor power for 2 minutes (fan at LOW, set by remote)
  2. Phase A: send ONLY 0x18=HIGH (no init) — this should NOT change power
     (confirmed by listen test). Monitor for 2 minutes.
  3. Reset: send 0x18=LOW. Wait 1 minute.
  4. Phase B: send SETTINGS time sync + 0x18=HIGH. Monitor for 2 minutes.
  5. Phase C: send 0x29 burst + 0x18=HIGH. Monitor for 2 minutes.

If power changes in Phase B or C but not A, that identifies the enabling factor.
"""

import asyncio
import functools
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# Fix output buffering
print = functools.partial(print, flush=True)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from visionair_ble.connect import connect_via_proxy
from visionair_ble.protocol import (
    MAGIC,
    PacketType,
    build_airflow_request,
    build_schedule_toggle,
    calc_checksum,
    parse_status,
)

# BLE characteristics
SC_UUID = "0003caa2-0000-1000-8000-00805f9b0131"
CC_UUID = "0003cbb1-0000-1000-8000-00805f9b0131"


def ts():
    return datetime.now().strftime("%H:%M:%S")


SHELLY_URL = "http://192.168.1.146/status"


def read_power():
    """Read both Shelly EM power channels directly via HTTP API (~1s resolution)."""
    import urllib.request
    try:
        with urllib.request.urlopen(SHELLY_URL, timeout=5) as resp:
            data = json.loads(resp.read())
        emeters = data.get("emeters", [])
        return {
            "main": emeters[0]["power"] if len(emeters) > 0 else None,
            "heatpump": emeters[1]["power"] if len(emeters) > 1 else None,
        }
    except Exception:
        return {"main": None, "heatpump": None}


def build_time_sync():
    """Build a SETTINGS packet with current time (mimicking phone behavior)."""
    now = datetime.now()
    payload = bytes([
        PacketType.SETTINGS,
        0x06,
        0x06,
        0x1A,       # summer limit temp (26°C) — constant config
        0x02,       # constant
        now.day,    # day (phone sends day-of-month or day-of-week)
        now.hour,   # hour
        now.minute, # minute
        now.second, # second
    ])
    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


def build_0x29_request(value: int) -> bytes:
    """Build a REQUEST with param 0x29."""
    payload = bytes([
        PacketType.REQUEST,
        0x06,
        0x05,
        0x29,
        0x00,
        0x00,
        0x00,
        value & 0xFF,
    ])
    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


async def monitor_power(duration_s: int, label: str, interval: float = 2.0):
    """Monitor power sensors for a duration, return list of readings."""
    readings = []
    start = time.time()
    while time.time() - start < duration_s:
        power = read_power()
        elapsed = time.time() - start
        readings.append({"t": elapsed, **power})
        main = power.get("main", "?")
        hp = power.get("heatpump", "?")
        print(f"  [{ts()}] {label} {elapsed:5.0f}s  main={main}W  heatpump={hp}W")
        await asyncio.sleep(interval)
    return readings


async def send_and_read(client, cc, sc, command):
    """Send a command and read the response notification."""
    response = None
    def handler(_, data):
        nonlocal response
        response = bytes(data)

    await client.start_notify(sc, handler)
    await client.write_gatt_char(cc, command, response=True)
    await asyncio.sleep(1.0)
    await client.stop_notify(sc)
    return response


async def main():
    mac = os.environ.get("VISIONAIR_MAC")
    host = os.environ.get("ESPHOME_PROXY_HOST")
    key = os.environ.get("ESPHOME_API_KEY")

    if not all([mac, host, key]):
        print("ERROR: Set VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY")
        sys.exit(1)

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

    all_results = {}

    # --- BASELINE ---
    print(f"\n{'='*60}")
    print(f"[{ts()}] BASELINE: Fan at LOW (set by remote). Monitoring 2 min.")
    print(f"{'='*60}")
    all_results["baseline"] = await monitor_power(120, "BASELINE")

    # --- PHASE A: 0x18 only (control — should NOT change power) ---
    print(f"\n{'='*60}")
    print(f"[{ts()}] PHASE A: Send 0x18=HIGH only (no init). Expect NO change.")
    print(f"{'='*60}")
    async with connect() as client:
        sc, cc = find_chars(client)
        cmd = build_airflow_request(2)
        print(f"  [{ts()}] Sending 0x18=HIGH: {cmd.hex()}")
        ds = await send_and_read(client, cc, sc, cmd)
        if ds:
            s = parse_status(ds)
            print(f"  [{ts()}] BLE confirms: mode={s.airflow_mode}, indicator=0x{s.airflow_indicator:02x}")

    all_results["phase_a"] = await monitor_power(120, "PHASE_A")

    # --- RESET ---
    print(f"\n[{ts()}] Resetting to LOW...")
    async with connect() as client:
        sc, cc = find_chars(client)
        cmd = build_airflow_request(0)
        await send_and_read(client, cc, sc, cmd)
        print(f"  [{ts()}] Reset to LOW")
    await asyncio.sleep(60)

    # --- PHASE B: Time sync + 0x18 ---
    print(f"\n{'='*60}")
    print(f"[{ts()}] PHASE B: Send time sync + 0x18=HIGH.")
    print(f"{'='*60}")
    async with connect() as client:
        sc, cc = find_chars(client)

        # Send 3 time syncs (like the phone does periodically)
        for i in range(3):
            ts_pkt = build_time_sync()
            print(f"  [{ts()}] Sending time sync #{i+1}: {ts_pkt.hex()}")
            await client.write_gatt_char(cc, ts_pkt, response=True)
            await asyncio.sleep(1.0)

        # Now send 0x18=HIGH
        cmd = build_airflow_request(2)
        print(f"  [{ts()}] Sending 0x18=HIGH: {cmd.hex()}")
        ds = await send_and_read(client, cc, sc, cmd)
        if ds:
            s = parse_status(ds)
            print(f"  [{ts()}] BLE confirms: mode={s.airflow_mode}, indicator=0x{s.airflow_indicator:02x}")

    all_results["phase_b"] = await monitor_power(120, "PHASE_B")

    # --- RESET ---
    print(f"\n[{ts()}] Resetting to LOW...")
    async with connect() as client:
        sc, cc = find_chars(client)
        await send_and_read(client, cc, sc, build_airflow_request(0))
        print(f"  [{ts()}] Reset to LOW")
    await asyncio.sleep(60)

    # --- PHASE C: 0x29 burst + 0x18 ---
    print(f"\n{'='*60}")
    print(f"[{ts()}] PHASE C: Send 0x29 burst + 0x18=HIGH.")
    print(f"{'='*60}")
    async with connect() as client:
        sc, cc = find_chars(client)

        # Send 0x29=0 once, then 0x29=1 x30 (shortened from phone's ~60)
        cmd_29_0 = build_0x29_request(0)
        print(f"  [{ts()}] Sending 0x29=0: {cmd_29_0.hex()}")
        await client.write_gatt_char(cc, cmd_29_0, response=True)
        await asyncio.sleep(0.5)

        cmd_29_1 = build_0x29_request(1)
        print(f"  [{ts()}] Sending 0x29=1 x30...")
        for i in range(30):
            await client.write_gatt_char(cc, cmd_29_1, response=True)
            await asyncio.sleep(0.1)
        print(f"  [{ts()}] 0x29 burst complete")

        # Now send 0x18=HIGH
        cmd = build_airflow_request(2)
        print(f"  [{ts()}] Sending 0x18=HIGH: {cmd.hex()}")
        ds = await send_and_read(client, cc, sc, cmd)
        if ds:
            s = parse_status(ds)
            print(f"  [{ts()}] BLE confirms: mode={s.airflow_mode}, indicator=0x{s.airflow_indicator:02x}")

    all_results["phase_c"] = await monitor_power(120, "PHASE_C")

    # --- RESET ---
    print(f"\n[{ts()}] Final reset to LOW...")
    async with connect() as client:
        sc, cc = find_chars(client)
        await send_and_read(client, cc, sc, build_airflow_request(0))

    # --- SUMMARY ---
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    for phase, readings in all_results.items():
        main_vals = [r["main"] for r in readings if r.get("main") is not None]
        hp_vals = [r["heatpump"] for r in readings if r.get("heatpump") is not None]
        if main_vals:
            print(f"  {phase:12s}  main: avg={sum(main_vals)/len(main_vals):.1f}W "
                  f"min={min(main_vals):.1f}W max={max(main_vals):.1f}W")
        if hp_vals:
            print(f"  {'':12s}  hpump: avg={sum(hp_vals)/len(hp_vals):.1f}W "
                  f"min={min(hp_vals):.1f}W max={max(hp_vals):.1f}W")

    # Save raw data
    outfile = os.path.join(
        os.path.dirname(__file__), '..', '..', 'data', 'captures',
        f'init_fan_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    )
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    with open(outfile, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nRaw data: {outfile}")


if __name__ == "__main__":
    asyncio.run(main())
