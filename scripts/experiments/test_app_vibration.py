#!/usr/bin/env python3
"""Experiment: Does the VMI+ app cycle 0x18 when showing measurements?

Monitors vibration while the phone app connects and displays the
measurements screen. If vibration stays flat at LOW baseline (~0.035),
the app does NOT cycle 0x18. If spikes appear (>0.005 above baseline),
the app IS cycling modes to read sensor temperatures.

See https://github.com/bartcortooms/visionair-ble/issues/20

Prerequisites:
  - HA integrations (VisionAir + ESPHome proxy) DISABLED
  - Phone app force-stopped
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

print = functools.partial(print, flush=True)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(REPO_DIR))

from visionair_ble.connect import connect_via_proxy
from visionair_ble.client import VisionAirClient
from visionair_ble.protocol import build_schedule_toggle
from scripts.sound_monitor import read_vibration, stream_sensors, SensorReading

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


def quick_connect():
    return connect_via_proxy(PROXY_HOST, API_KEY, device_address=MAC, scan_timeout=30.0)


async def ble_schedule_toggle(enable: bool):
    action = "Enabling" if enable else "Disabling"
    print(f"  [{ts()}] {action} schedule...")
    async with quick_connect() as client:
        visionair = VisionAirClient(client)
        visionair._find_characteristics()
        await client.write_gatt_char(
            visionair._command_char, build_schedule_toggle(enable), response=True
        )
        await asyncio.sleep(0.5)
    print(f"  [{ts()}] Schedule {'enabled' if enable else 'disabled'}")


async def ble_set_mode(mode: str):
    print(f"  [{ts()}] Setting airflow mode to {mode.upper()}...")
    async with quick_connect() as client:
        visionair = VisionAirClient(client)
        status = await visionair.set_airflow_mode(mode)
        print(f"  [{ts()}] BLE response: mode={status.airflow_mode}")
    print(f"  [{ts()}] BLE disconnected (slot free)")


def vmictl(command: str):
    """Run a vmictl command."""
    vmictl_path = REPO_DIR / "scripts" / "capture" / "vmictl.py"
    result = subprocess.run(
        [sys.executable, str(vmictl_path), command],
        capture_output=True, text=True, timeout=60,
    )
    print(f"  [{ts()}] vmictl {command}: {result.stdout.strip()}")
    if result.returncode != 0:
        print(f"  [{ts()}] vmictl stderr: {result.stderr.strip()}")
    return result


async def main():
    global MAC, PROXY_HOST, API_KEY
    load_env()

    MAC = os.environ.get("VISIONAIR_MAC")
    PROXY_HOST = os.environ.get("ESPHOME_PROXY_HOST")
    API_KEY = os.environ.get("ESPHOME_API_KEY")

    if not all([MAC, PROXY_HOST, API_KEY]):
        print("ERROR: Set VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY in .env")
        sys.exit(1)

    output_dir = REPO_DIR / "data" / "captures" / f"app_vibration_{datetime.now():%Y%m%d_%H%M%S}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("EXPERIMENT: Does VMI+ app cycle 0x18 on measurements screen?")
    print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Output: {output_dir}")
    print("=" * 60)

    readings: list[dict] = []
    events: list[dict] = []
    baseline_readings: list[float] = []
    schedule_disabled = False

    def record_event(name: str):
        events.append({"time": ts(), "epoch": time.time(), "event": name})
        print(f"\n  >>> EVENT: {name} at {ts()}")

    try:
        # Phase 0: Disable schedule + set LOW
        print(f"\n--- Phase 0: Setup ---")
        await ble_schedule_toggle(False)
        schedule_disabled = True
        await asyncio.sleep(3)

        await ble_set_mode("low")
        await asyncio.sleep(2)

        # Phase 1: Wait for fan to settle (2 min — likely already at LOW)
        print(f"\n--- Phase 1: Settle ({ts()}) ---")
        print(f"  Waiting 2 minutes for fan to settle at LOW...")
        for i in range(4):
            v = await read_vibration()
            print(f"  [{ts()}] Settle check {i+1}/4: {v:.4f} m/s²")
            await asyncio.sleep(30)

        # Phase 2: Stream vibration while launching app
        print(f"\n--- Phase 2: Vibration stream + app launch ---")
        print(f"  Streaming vibration for 180 seconds.")
        print(f"  Events will be timestamped in the log.")

        stream_start = time.time()
        reading_count = 0
        def on_reading(r: SensorReading):
            nonlocal reading_count
            reading_count += 1
            entry = {
                "n": reading_count,
                "time": time.strftime("%H:%M:%S", time.localtime(r.timestamp)),
                "epoch": r.timestamp,
                "vibration": round(r.vibration, 4) if r.vibration else None,
            }
            readings.append(entry)
            elapsed = r.timestamp - stream_start
            marker = ""
            if r.vibration is not None:
                if reading_count <= 30:
                    baseline_readings.append(r.vibration)
                elif baseline_readings:
                    baseline_avg = sum(baseline_readings) / len(baseline_readings)
                    delta = r.vibration - baseline_avg
                    if abs(delta) > 0.005:
                        marker = f" *** SPIKE delta={delta:+.4f}"
            print(f"  [{entry['time']}] #{reading_count:3d} | {elapsed:6.1f}s | "
                  f"vibration={r.vibration:.4f}{marker}")

        # Start streaming in a background task
        stream_task = asyncio.create_task(stream_sensors(count=180, callback=on_reading))

        # Wait 30 seconds for baseline
        record_event("baseline_start")
        await asyncio.sleep(30)
        record_event("baseline_end")

        if baseline_readings:
            baseline_avg = sum(baseline_readings) / len(baseline_readings)
            print(f"\n  Baseline: {baseline_avg:.4f} m/s² ({len(baseline_readings)} samples)")
        else:
            print(f"\n  WARNING: No baseline readings collected!")

        # Launch phone app
        record_event("app_launch")
        vmictl("connect")
        await asyncio.sleep(15)  # Wait for app to connect to VMI

        # Navigate to measurements screen
        record_event("measurements_screen")
        vmictl("measurements-full")
        await asyncio.sleep(5)

        # Monitor for 2 minutes on measurements screen
        record_event("monitoring_start")
        print(f"\n  Monitoring vibration for 2 minutes on measurements screen...")
        await asyncio.sleep(120)
        record_event("monitoring_end")

        # Cancel stream
        stream_task.cancel()
        try:
            await stream_task
        except (asyncio.CancelledError, Exception):
            pass

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print(f"\n--- Cleanup ---")

        # Force-stop app
        adb_target = os.environ.get("ADB_TARGET", "")
        if adb_target:
            print(f"  [{ts()}] Force-stopping VMI+ app...")
            subprocess.run(
                ["adb", "-s", adb_target, "shell", "am", "force-stop",
                 "com.ventilairsec.ventilairsecinstallateur"],
                capture_output=True, timeout=10,
            )

        # Re-enable schedule
        if schedule_disabled:
            try:
                await asyncio.sleep(5)  # Wait for phone to disconnect
                await ble_schedule_toggle(True)
            except Exception as ex:
                print(f"  WARNING: Failed to re-enable schedule: {ex}")

    # Save data
    log = {
        "experiment": "app_vibration_monitoring",
        "issue": "#20",
        "start_time": datetime.now().isoformat(),
        "events": events,
        "readings_count": len(readings),
        "readings": readings,
    }

    # Analysis
    if baseline_readings and readings:
        baseline_avg = sum(baseline_readings) / len(baseline_readings)
        # Get readings after app launch
        app_launch_time = next(
            (e["epoch"] for e in events if e["event"] == "app_launch"), None
        )
        if app_launch_time:
            app_readings = [
                r["vibration"] for r in readings
                if r["epoch"] > app_launch_time and r["vibration"] is not None
            ]
            if app_readings:
                app_avg = sum(app_readings) / len(app_readings)
                app_max = max(app_readings)
                app_min = min(app_readings)
                max_delta = app_max - baseline_avg

                log["analysis"] = {
                    "baseline_avg": round(baseline_avg, 4),
                    "baseline_samples": len(baseline_readings),
                    "app_avg": round(app_avg, 4),
                    "app_max": round(app_max, 4),
                    "app_min": round(app_min, 4),
                    "max_delta_from_baseline": round(max_delta, 4),
                    "conclusion": (
                        "APP_CYCLES_0x18" if max_delta > 0.005
                        else "APP_DOES_NOT_CYCLE_0x18"
                    ),
                }

                print(f"\n{'='*60}")
                print("ANALYSIS")
                print(f"{'='*60}")
                print(f"  Baseline (pre-app):    {baseline_avg:.4f} m/s² "
                      f"({len(baseline_readings)} samples)")
                print(f"  During app polling:    avg={app_avg:.4f}, "
                      f"min={app_min:.4f}, max={app_max:.4f}")
                print(f"  Max delta from base:   {max_delta:+.4f} m/s²")
                print(f"  Threshold:             0.005 m/s²")

                if max_delta > 0.005:
                    print(f"\n  CONCLUSION: App DOES cycle 0x18 "
                          f"(vibration spike {max_delta:+.4f} > 0.005)")
                else:
                    print(f"\n  CONCLUSION: App does NOT cycle 0x18 "
                          f"(max delta {max_delta:+.4f} <= 0.005)")
                    print(f"  Remote temperature is obtained through another mechanism.")
                print(f"{'='*60}")

    log_path = output_dir / "experiment_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print(f"\n  Log saved to: {log_path}")


if __name__ == "__main__":
    asyncio.run(main())
