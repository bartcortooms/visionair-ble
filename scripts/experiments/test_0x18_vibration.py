#!/usr/bin/env python3
"""Experiment: Does REQUEST param 0x18 change the physical fan speed?

Uses the vibration sensor (accelerometer on the VMI housing) to detect
actual motor speed changes, rather than relying on BLE state bytes.

See https://github.com/bartcortooms/visionair-ble/issues/22

Vibration reference values:
  LOW:  ~0.035 m/s² (range 0.030 – 0.039)
  HIGH: ~0.048 m/s² (range 0.044 – 0.053)
  MAX:  ~0.069 m/s² (range 0.060 – 0.077)

A shift of >0.005 m/s² indicates a real fan speed change.

Procedure:
  1. Disable schedule via BLE
  2. Set LOW, wait 4 min for full ramp-down
  3. Read vibration baseline (expect ~0.035)
  4. Send set_airflow_mode("high") via BLE
  5. Wait 30 seconds for ramp-up
  6. Read vibration (expect ~0.048 if fan changed)
  7. Call get_fresh_status(), check airflow_mode == "high"
  8. Set LOW again, wait 4 min for ramp-down
  9. Read vibration (expect return to ~0.035)
  10. Send set_airflow_mode("low"), verify get_fresh_status()
  11. Re-enable schedule (always, even on error)

Prerequisites:
  - HA VisionAir integration DISABLED
  - HA ESPHome proxy integration DISABLED
  - .env with VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY
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

# Force unbuffered output
print = functools.partial(print, flush=True)

# Add repo root to path for imports
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(REPO_DIR))

from visionair_ble.connect import connect_via_proxy
from visionair_ble.client import VisionAirClient
from visionair_ble.protocol import build_schedule_toggle, MAGIC, PacketType
from scripts.sound_monitor import read_vibration


MAC = PROXY_HOST = API_KEY = None


def load_env():
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


def say(text: str):
    """Announce via text-to-speech (blocking)."""
    try:
        subprocess.run(
            [os.path.expanduser("~/.local/bin/speak"), text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def quick_connect():
    return connect_via_proxy(PROXY_HOST, API_KEY, device_address=MAC, scan_timeout=30.0)


async def vibration_reading(label: str, n_samples: int = 3) -> float:
    """Take multiple vibration readings and return the average."""
    readings = []
    for i in range(n_samples):
        v = await read_vibration()
        readings.append(v)
        print(f"  [{ts()}] {label} sample {i+1}/{n_samples}: {v:.4f} m/s²")
        if i < n_samples - 1:
            await asyncio.sleep(2)
    avg = sum(readings) / len(readings)
    print(f"  [{ts()}] {label} average: {avg:.4f} m/s² (samples: {[f'{r:.4f}' for r in readings]})")
    return avg


async def ble_schedule_toggle(enable: bool):
    """Connect, toggle schedule, disconnect."""
    action = "Enabling" if enable else "Disabling"
    print(f"\n  [{ts()}] {action} schedule...")
    async with quick_connect() as client:
        visionair = VisionAirClient(client)
        visionair._find_characteristics()
        await client.write_gatt_char(
            visionair._command_char, build_schedule_toggle(enable), response=True
        )
        await asyncio.sleep(0.5)
    print(f"  [{ts()}] Schedule {'enabled' if enable else 'disabled'}")


async def ble_set_mode(mode: str) -> dict:
    """Connect, set airflow mode, return status info, disconnect."""
    print(f"\n  [{ts()}] Setting airflow mode to {mode.upper()}...")
    async with quick_connect() as client:
        visionair = VisionAirClient(client)
        status = await visionair.set_airflow_mode(mode)
        result = {
            "timestamp": ts(),
            "action": f"set_{mode}",
            "airflow_mode": status.airflow_mode,
            "airflow_indicator": f"0x{status.airflow_indicator:02x}",
            "mode_selector": status.mode_selector,
        }
        print(f"  [{ts()}] BLE response: mode={status.airflow_mode}, "
              f"indicator=0x{status.airflow_indicator:02x}, "
              f"selector={status.mode_selector}")
        return result


async def ble_get_status() -> dict:
    """Connect, get fresh status, disconnect. Returns partial result on failure."""
    print(f"\n  [{ts()}] Reading fresh status...")
    try:
        async with quick_connect() as client:
            visionair = VisionAirClient(client)
            status = await visionair.get_status()
            result = {
                "timestamp": ts(),
                "airflow_mode": status.airflow_mode,
                "airflow_indicator": f"0x{status.airflow_indicator:02x}",
                "mode_selector": status.mode_selector,
                "airflow": status.airflow,
            }
            print(f"  [{ts()}] Status: mode={status.airflow_mode}, "
                  f"airflow={status.airflow} m³/h, "
                  f"indicator=0x{status.airflow_indicator:02x}")
            return result
    except Exception as e:
        print(f"  [{ts()}] Status read failed: {e} (continuing)")
        return {"timestamp": ts(), "error": str(e)}


async def wait_with_progress(seconds: int, label: str):
    """Wait with periodic progress updates."""
    interval = 30
    elapsed = 0
    while elapsed < seconds:
        remaining = seconds - elapsed
        wait = min(interval, remaining)
        print(f"  [{ts()}] {label}: {remaining}s remaining...")
        await asyncio.sleep(wait)
        elapsed += wait
    print(f"  [{ts()}] {label}: done")


async def main():
    global MAC, PROXY_HOST, API_KEY
    load_env()

    MAC = os.environ.get("VISIONAIR_MAC")
    PROXY_HOST = os.environ.get("ESPHOME_PROXY_HOST")
    API_KEY = os.environ.get("ESPHOME_API_KEY")

    if not all([MAC, PROXY_HOST, API_KEY]):
        print("ERROR: Set VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY in .env")
        sys.exit(1)

    output_dir = REPO_DIR / "data" / "captures" / f"0x18_vibration_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("EXPERIMENT: Does 0x18 change physical fan speed?")
    print("Method: Vibration sensor (accelerometer on VMI housing)")
    print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Output: {output_dir}")
    print("=" * 60)

    log = {
        "start_time": datetime.now().isoformat(),
        "phases": [],
    }
    schedule_disabled = False

    try:
        # === Phase 0: Setup ===
        print(f"\n{'='*60}")
        print("Phase 0: Setup — disable schedule, set LOW baseline")
        print(f"{'='*60}")

        # Disable schedule
        await ble_schedule_toggle(False)
        schedule_disabled = True
        await asyncio.sleep(3)

        # Set LOW to establish baseline
        say("Setting low")
        set_low_result = await ble_set_mode("low")
        log["phases"].append({"phase": "setup", "set_low": set_low_result})
        await asyncio.sleep(2)

        # Wait 4 minutes for ramp-down (in case fan was at a higher speed)
        print(f"\n  [{ts()}] Waiting 4 min for fan to settle at LOW...")
        await wait_with_progress(240, "Ramp-down")

        # === Phase 1: LOW baseline ===
        print(f"\n{'='*60}")
        print("Phase 1: LOW baseline vibration")
        print(f"{'='*60}")

        baseline_vibration = await vibration_reading("LOW baseline", n_samples=5)
        baseline_status = await ble_get_status()

        phase1 = {
            "phase": "LOW_baseline",
            "vibration_avg": baseline_vibration,
            "status": baseline_status,
        }
        log["phases"].append(phase1)

        print(f"\n  BASELINE: vibration={baseline_vibration:.4f} m/s², "
              f"mode={baseline_status.get('airflow_mode', 'N/A')}")
        say(f"Baseline {baseline_vibration:.3f}")

        # === Phase 2: Set HIGH and measure ===
        print(f"\n{'='*60}")
        print("Phase 2: Send set_airflow_mode('high'), measure vibration")
        print(f"{'='*60}")

        say("Setting high")
        set_high_result = await ble_set_mode("high")
        await asyncio.sleep(2)

        # Wait 30 seconds for potential ramp-up
        print(f"\n  [{ts()}] Waiting 30s for fan ramp-up...")
        await wait_with_progress(30, "Ramp-up wait")

        # Read vibration after setting HIGH
        high_vibration = await vibration_reading("After HIGH", n_samples=5)

        # Get fresh status to verify BLE reports "high"
        high_status = await ble_get_status()

        phase2 = {
            "phase": "after_HIGH",
            "set_result": set_high_result,
            "vibration_avg": high_vibration,
            "status": high_status,
        }
        log["phases"].append(phase2)

        vibration_delta = high_vibration - baseline_vibration
        print(f"\n  AFTER HIGH: vibration={high_vibration:.4f} m/s², "
              f"delta={vibration_delta:+.4f} m/s²")
        print(f"  BLE mode: {high_status.get('airflow_mode', 'N/A')}")

        if abs(vibration_delta) > 0.005:
            print(f"  >>> VIBRATION SHIFTED by {vibration_delta:+.4f} — fan speed CHANGED")
            say("Fan speed changed")
        else:
            print(f"  >>> Vibration delta {vibration_delta:+.4f} < 0.005 — NO physical change")
            say("No change")

        # === Phase 3: Return to LOW ===
        print(f"\n{'='*60}")
        print("Phase 3: Set LOW, wait for ramp-down, verify return to baseline")
        print(f"{'='*60}")

        say("Setting low")
        set_low2_result = await ble_set_mode("low")
        await asyncio.sleep(2)

        # Wait 4 minutes for full ramp-down
        print(f"\n  [{ts()}] Waiting 4 min for fan to settle at LOW...")
        await wait_with_progress(240, "Ramp-down")

        # Read vibration after returning to LOW
        return_vibration = await vibration_reading("Return to LOW", n_samples=5)

        # Verify BLE reports "low"
        low_status = await ble_get_status()

        phase3 = {
            "phase": "return_to_LOW",
            "set_result": set_low2_result,
            "vibration_avg": return_vibration,
            "status": low_status,
        }
        log["phases"].append(phase3)

        return_delta = return_vibration - baseline_vibration
        print(f"\n  RETURN TO LOW: vibration={return_vibration:.4f} m/s², "
              f"delta from baseline={return_delta:+.4f}")
        print(f"  BLE mode: {low_status.get('airflow_mode', 'N/A')}")

        # === Cleanup: Re-enable schedule ===
        print(f"\n{'='*60}")
        print("Cleanup: Re-enable schedule")
        print(f"{'='*60}")

        await ble_schedule_toggle(True)
        schedule_disabled = False

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if schedule_disabled:
            print(f"\n  [{ts()}] Re-enabling schedule (cleanup)...")
            try:
                await ble_schedule_toggle(True)
            except Exception as ex:
                print(f"  WARNING: Failed to re-enable schedule: {ex}")

    # === Save log ===
    log["end_time"] = datetime.now().isoformat()
    log_path = output_dir / "experiment_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"\n  Log saved to: {log_path}")

    # === Analysis ===
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")

    phases = log["phases"]
    baseline_v = None
    high_v = None
    return_v = None

    for p in phases:
        if p["phase"] == "LOW_baseline":
            baseline_v = p["vibration_avg"]
        elif p["phase"] == "after_HIGH":
            high_v = p["vibration_avg"]
        elif p["phase"] == "return_to_LOW":
            return_v = p["vibration_avg"]

    if baseline_v is not None and high_v is not None:
        delta = high_v - baseline_v

        print(f"\n  LOW baseline:     {baseline_v:.4f} m/s²")
        print(f"  After HIGH cmd:   {high_v:.4f} m/s²")
        if return_v is not None:
            print(f"  Return to LOW:    {return_v:.4f} m/s²")
        print(f"  Delta (HIGH-LOW): {delta:+.4f} m/s²")
        print(f"  Threshold:        0.005 m/s²")

        # BLE status checks
        high_status = next((p for p in phases if p["phase"] == "after_HIGH"), {})
        low_status = next((p for p in phases if p["phase"] == "return_to_LOW"), {})

        ble_high_ok = high_status.get("status", {}).get("airflow_mode") == "high"
        ble_low_ok = low_status.get("status", {}).get("airflow_mode") == "low"

        print(f"\n  BLE reports 'high' after set_airflow_mode('high'): {'YES' if ble_high_ok else 'NO'}")
        print(f"  BLE reports 'low' after set_airflow_mode('low'):    {'YES' if ble_low_ok else 'NO'}")

        if abs(delta) > 0.005:
            print(f"\n  RESULT: PASS — 0x18 DOES change the physical fan speed")
            print(f"          Vibration shifted by {delta:+.4f} m/s² (>{0.005})")
            log["result"] = "PASS"
        else:
            print(f"\n  RESULT: FAIL — 0x18 does NOT change the physical fan speed")
            print(f"          Vibration delta {delta:+.4f} m/s² is below threshold")
            print(f"          The command only changes BLE state bytes, not the motor")
            log["result"] = "FAIL"

        if return_v is not None:
            return_delta = abs(return_v - baseline_v)
            if return_delta < 0.005:
                print(f"  Return to baseline: OK (delta {return_delta:.4f} < 0.005)")
            else:
                print(f"  Return to baseline: UNEXPECTED (delta {return_delta:.4f} >= 0.005)")
    else:
        print("\n  ERROR: Missing vibration data, cannot determine result")
        log["result"] = "ERROR"

    # Re-save with result
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2, default=str)

    print(f"\n{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
