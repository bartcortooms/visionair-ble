#!/usr/bin/env python3
"""Query the sound/vibration monitor (M5StickC Plus2 on VMI).

The monitor runs ESPHome firmware with:
- SPM1423 PDM microphone → Sound Level RMS/Peak (dB)
- MPU6886 accelerometer → Vibration Level (m/s², std dev of 500 samples)

Usage as CLI:
    # Single reading
    python scripts/sound_monitor.py

    # Continuous monitoring (one reading per second, 30 readings)
    python scripts/sound_monitor.py --stream 30

    # Just vibration level (for scripting)
    python scripts/sound_monitor.py --vibration

Usage as library:
    from scripts.sound_monitor import read_vibration, read_sensors, stream_sensors

    level = await read_vibration()  # float, e.g. 0.047
    sensors = await read_sensors()  # dict with all sensor values
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass

from aioesphomeapi import APIClient, SensorState
from dotenv import load_dotenv


@dataclass
class SensorReading:
    vibration: float | None = None
    sound_rms: float | None = None
    sound_peak: float | None = None
    timestamp: float = 0.0


def _get_config() -> tuple[str, int, str]:
    """Return (host, port, noise_psk) from environment."""
    load_dotenv()
    host = os.environ.get("SOUND_MONITOR_HOST", "192.168.1.51")
    port = int(os.environ.get("SOUND_MONITOR_PORT", "6053"))
    psk = os.environ.get("ESPHOME_API_KEY", "")
    return host, port, psk


async def read_sensors(timeout: float = 10.0) -> SensorReading:
    """Connect, read all sensor values once, disconnect."""
    host, port, psk = _get_config()
    client = APIClient(host, port, password="", noise_psk=psk)

    reading = SensorReading(timestamp=time.time())
    got_vibration = asyncio.Event()

    try:
        await client.connect(login=True)
        entities, services = await client.list_entities_services()

        # Build key→name map
        key_to_name: dict[int, str] = {}
        for entity in entities:
            if hasattr(entity, "key") and hasattr(entity, "name"):
                key_to_name[entity.key] = entity.name

        def on_state(state):
            if not isinstance(state, SensorState):
                return
            name = key_to_name.get(state.key, "")
            if name == "Vibration Level":
                reading.vibration = state.state
                reading.timestamp = time.time()
                got_vibration.set()
            elif name == "Sound Level RMS":
                reading.sound_rms = state.state
            elif name == "Sound Level Peak":
                reading.sound_peak = state.state

        client.subscribe_states(on_state)
        await asyncio.wait_for(got_vibration.wait(), timeout=timeout)
        # Give a moment for sound sensors to arrive too
        await asyncio.sleep(0.5)
    finally:
        await client.disconnect()

    return reading


async def read_vibration(timeout: float = 10.0) -> float:
    """Read just the vibration level. Returns m/s² (std dev)."""
    reading = await read_sensors(timeout)
    if reading.vibration is None:
        raise RuntimeError("No vibration reading received")
    return reading.vibration


async def stream_sensors(
    count: int = 0,
    interval: float = 1.0,
    callback=None,
):
    """Stream sensor readings. If count=0, stream indefinitely.

    callback receives a SensorReading for each update.
    If no callback, prints to stdout.
    """
    host, port, psk = _get_config()
    client = APIClient(host, port, password="", noise_psk=psk)

    await client.connect(login=True)
    entities, services = await client.list_entities_services()

    key_to_name: dict[int, str] = {}
    for entity in entities:
        if hasattr(entity, "key") and hasattr(entity, "name"):
            key_to_name[entity.key] = entity.name

    current = SensorReading(timestamp=time.time())
    readings_count = 0
    done = asyncio.Event()

    def on_state(state):
        nonlocal current, readings_count
        if not isinstance(state, SensorState):
            return
        name = key_to_name.get(state.key, "")
        if name == "Vibration Level":
            current.vibration = state.state
            current.timestamp = time.time()
            readings_count += 1
            if callback:
                callback(SensorReading(
                    vibration=current.vibration,
                    sound_rms=current.sound_rms,
                    sound_peak=current.sound_peak,
                    timestamp=current.timestamp,
                ))
            else:
                parts = []
                if current.vibration is not None:
                    parts.append(f"vibration={current.vibration:.4f}")
                if current.sound_rms is not None:
                    parts.append(f"rms={current.sound_rms:.1f}dB")
                if current.sound_peak is not None:
                    parts.append(f"peak={current.sound_peak:.1f}dB")
                ts = time.strftime("%H:%M:%S", time.localtime(current.timestamp))
                print(f"[{ts}] {' | '.join(parts)}")
            if count > 0 and readings_count >= count:
                done.set()
        elif name == "Sound Level RMS":
            current.sound_rms = state.state
        elif name == "Sound Level Peak":
            current.sound_peak = state.state

    try:
        client.subscribe_states(on_state)
        if count > 0:
            try:
                await asyncio.wait_for(done.wait(), timeout=count * interval + 30)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.Event().wait()  # run forever
    except KeyboardInterrupt:
        pass
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Query VMI sound/vibration monitor")
    parser.add_argument(
        "--stream", type=int, nargs="?", const=0, default=None,
        help="Stream readings (optionally specify count, 0=infinite)",
    )
    parser.add_argument(
        "--vibration", action="store_true",
        help="Print only the vibration value (for scripting)",
    )
    args = parser.parse_args()

    if args.stream is not None:
        asyncio.run(stream_sensors(count=args.stream))
    elif args.vibration:
        level = asyncio.run(read_vibration())
        print(f"{level:.4f}")
    else:
        reading = asyncio.run(read_sensors())
        print(f"Vibration: {reading.vibration:.4f} m/s²" if reading.vibration else "Vibration: N/A")
        print(f"Sound RMS: {reading.sound_rms:.1f} dB" if reading.sound_rms else "Sound RMS: N/A")
        print(f"Sound Peak: {reading.sound_peak:.1f} dB" if reading.sound_peak else "Sound Peak: N/A")


if __name__ == "__main__":
    main()
