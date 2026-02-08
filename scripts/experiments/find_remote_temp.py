#!/usr/bin/env python3
"""Search raw BLE response bytes for Remote temperature.

Connects via ESPHome proxy, sends DEVICE_STATE_Q, FULL_DATA_Q, and
PROBE_SENSORS_Q requests, then searches every byte in the responses
for values matching the known sensor temperatures from the VMI+ app.

Reference values from VMI+ app measurements screen (2026-02-08 12:16):
  - Remote temp: 21°C
  - Probe 1 (Resistor outlet): 16°C
  - Probe 2 (Air inlet): 13°C
  - Remote humidity: 51%

See https://github.com/bartcortooms/visionair-ble/issues/20
"""

import asyncio
import functools
import os
import sys
import time
from pathlib import Path

print = functools.partial(print, flush=True)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(REPO_DIR))

from visionair_ble.connect import connect_via_proxy
from visionair_ble.client import VisionAirClient
from visionair_ble.protocol import (
    MAGIC, PacketType, DeviceStateOffset, ProbeSensorOffset,
    build_request, RequestParam,
    STATUS_CHAR_UUID, COMMAND_CHAR_UUID,
)


def load_env():
    env_path = REPO_DIR / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def hexdump(data: bytes) -> str:
    lines = []
    for i in range(0, len(data), 16):
        hex_part = " ".join(f"{b:02x}" for b in data[i:i+16])
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i+16])
        lines.append(f"  {i:04x}  {hex_part:<48}  {ascii_part}")
    return "\n".join(lines)


# Known byte mappings for DEVICE_STATE (to label known fields)
KNOWN_DS_BYTES = {
    0: "MAGIC[0]", 1: "MAGIC[1]", 2: "TYPE", 3: "?",
    4: "Remote humidity %",
    5: "device_id[0]", 6: "device_id[1]", 7: "device_id[2]",
    8: "unknown (always 18)",
    22: "configured_volume[0]", 23: "configured_volume[1]",
    26: "operating_days[0]", 27: "operating_days[1]",
    28: "filter_days[0]", 29: "filter_days[1]",
    32: "TEMP_ACTIVE (mode-dependent)",
    34: "SENSOR_SELECTOR (mode index)",
    35: "temp_probe1 (unreliable)",
    38: "summer_limit_temp",
    42: "temp_probe2 (unreliable)",
    43: "holiday_days",
    44: "boost_active",
    47: "airflow_indicator",
    49: "unknown_49",
    50: "summer_limit_enabled",
    53: "preheat_enabled",
    56: "preheat_temp",
}

KNOWN_PS_BYTES = {
    0: "MAGIC[0]", 1: "MAGIC[1]", 2: "TYPE",
    6: "temp_probe1", 8: "humidity_probe1",
    11: "temp_probe2", 13: "filter_percent",
}


def search_temps(data: bytes, packet_name: str, known_map: dict,
                 targets: dict[str, list[int]]):
    """Search all bytes for target temperature values."""
    print(f"\n  Searching {packet_name} ({len(data)} bytes) for target values:")
    for target_name, target_values in targets.items():
        matches = []
        for i, b in enumerate(data):
            if b in target_values:
                known = known_map.get(i, "")
                label = f" ({known})" if known else ""
                matches.append((i, b, label))
        if matches:
            print(f"    {target_name}:")
            for offset, val, label in matches:
                print(f"      byte[{offset}] = {val} (0x{val:02x}){label}")
        else:
            print(f"    {target_name}: no matches")


async def main():
    load_env()
    host = os.environ.get("ESPHOME_PROXY_HOST")
    key = os.environ.get("ESPHOME_API_KEY")
    mac = os.environ.get("VISIONAIR_MAC")

    if not all([host, key, mac]):
        print("ERROR: Set VISIONAIR_MAC, ESPHOME_PROXY_HOST, ESPHOME_API_KEY in .env")
        sys.exit(1)

    # Target temperatures to search for
    # Each value could be encoded as direct °C, or ×10, or other encodings
    targets = {
        "Remote temp 21°C": [21, 210],       # 0x15, 0xD2
        "Probe 1 temp 16°C": [16, 160],      # 0x10, 0xA0
        "Probe 2 temp 13°C": [13, 130],       # 0x0D, 0x82
        "Remote humidity 51%": [51],           # 0x33
    }

    print("=" * 70)
    print("BYTE HUNT: Searching raw BLE responses for Remote temperature")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print("\nConnecting via ESPHome proxy...")

    async with connect_via_proxy(host, key, device_address=mac, scan_timeout=30) as client:
        visionair = VisionAirClient(client)
        visionair._find_characteristics()

        # Collect all responses from a single notification subscription
        responses = {}
        event = asyncio.Event()
        expected_types = set()

        def handler(data):
            raw = bytes(data)
            if len(raw) >= 3 and raw[:2] == MAGIC:
                ptype = raw[2]
                type_name = {
                    0x01: "DEVICE_STATE",
                    0x02: "SCHEDULE",
                    0x03: "PROBE_SENSORS",
                }.get(ptype, f"UNKNOWN_0x{ptype:02x}")
                responses[type_name] = raw
                print(f"  Received {type_name} ({len(raw)} bytes)")
                if type_name in expected_types:
                    expected_types.discard(type_name)
                    if not expected_types:
                        event.set()

        await client.start_notify(visionair._status_char, handler)

        # === Request 1: DEVICE_STATE_Q (0x03) ===
        print("\n--- Request 1: DEVICE_STATE_Q ---")
        event.clear()
        expected_types = {"DEVICE_STATE"}
        req = build_request(RequestParam.DEVICE_STATE)
        print(f"  Sending: {req.hex()}")
        await client.write_gatt_char(visionair._command_char, req, response=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=10)
        except asyncio.TimeoutError:
            print("  TIMEOUT waiting for DEVICE_STATE")

        await asyncio.sleep(1)

        # === Request 2: FULL_DATA_Q (0x06) ===
        print("\n--- Request 2: FULL_DATA_Q ---")
        event.clear()
        expected_types = {"DEVICE_STATE", "SCHEDULE", "PROBE_SENSORS"}
        req = build_request(RequestParam.FULL_DATA, extended=True)
        print(f"  Sending: {req.hex()}")
        await client.write_gatt_char(visionair._command_char, req, response=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=10)
        except asyncio.TimeoutError:
            missing = expected_types - set(responses.keys())
            if missing:
                print(f"  TIMEOUT (missing: {missing})")

        await asyncio.sleep(1)

        # === Request 3: PROBE_SENSORS_Q (0x07) ===
        print("\n--- Request 3: PROBE_SENSORS_Q ---")
        event.clear()
        expected_types = {"PROBE_SENSORS"}
        req = build_request(RequestParam.PROBE_SENSORS, extended=True)
        print(f"  Sending: {req.hex()}")
        await client.write_gatt_char(visionair._command_char, req, response=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=10)
        except asyncio.TimeoutError:
            print("  TIMEOUT waiting for PROBE_SENSORS")

        await client.stop_notify(visionair._status_char)

    # === Dump raw responses ===
    print("\n" + "=" * 70)
    print("RAW RESPONSES")
    print("=" * 70)

    for name, data in sorted(responses.items()):
        print(f"\n--- {name} ({len(data)} bytes) ---")
        print(hexdump(data))

    # === Show known field values ===
    if "DEVICE_STATE" in responses:
        ds = responses["DEVICE_STATE"]
        print("\n--- DEVICE_STATE known fields ---")
        print(f"  byte[4]  Remote humidity: {ds[4]}%")
        print(f"  byte[32] TEMP_ACTIVE: {ds[32]}°C")
        print(f"  byte[34] SENSOR_SELECTOR: {ds[34]}")
        print(f"  byte[35] temp_probe1 (unreliable): {ds[35]}°C")
        print(f"  byte[42] temp_probe2 (unreliable): {ds[42]}°C")
        print(f"  byte[47] airflow_indicator: 0x{ds[47]:02x}")
        print(f"  byte[53] preheat_enabled: {ds[53]}")

    if "PROBE_SENSORS" in responses:
        ps = responses["PROBE_SENSORS"]
        print("\n--- PROBE_SENSORS known fields ---")
        print(f"  byte[6]  temp_probe1: {ps[6]}°C")
        print(f"  byte[8]  humidity_probe1: {ps[8]}%")
        print(f"  byte[11] temp_probe2: {ps[11]}°C")
        print(f"  byte[13] filter_percent: {ps[13]}%")

    # === Search for target values ===
    print("\n" + "=" * 70)
    print("TEMPERATURE SEARCH")
    print("=" * 70)

    for name, data in sorted(responses.items()):
        known_map = {}
        if name == "DEVICE_STATE":
            known_map = KNOWN_DS_BYTES
        elif name == "PROBE_SENSORS":
            known_map = KNOWN_PS_BYTES
        search_temps(data, name, known_map, targets)

    # === Highlight unmapped bytes that match Remote temp ===
    if "DEVICE_STATE" in responses:
        ds = responses["DEVICE_STATE"]
        remote_vals = targets["Remote temp 21°C"]
        print("\n--- UNMAPPED bytes in DEVICE_STATE matching Remote temp ---")
        unmapped_matches = []
        for i, b in enumerate(ds):
            if b in remote_vals and i not in KNOWN_DS_BYTES:
                unmapped_matches.append((i, b))
        if unmapped_matches:
            for offset, val in unmapped_matches:
                # Show surrounding context
                start = max(0, offset - 2)
                end = min(len(ds), offset + 3)
                context = " ".join(
                    f"[{ds[j]:02x}]" if j == offset else f"{ds[j]:02x}"
                    for j in range(start, end)
                )
                print(f"  byte[{offset}] = {val} (0x{val:02x})  context: ...{context}...")
        else:
            print("  None found in unmapped bytes")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
