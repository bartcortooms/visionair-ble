#!/usr/bin/env python3
"""Dump raw status packet from VisionAir device.

This diagnostic script shows the raw bytes received from the device,
useful for debugging protocol issues or stale sensor values.

Usage:
    python dump_raw_status.py <MAC_ADDRESS>
    # or
    VMI_MAC=00:A0:50:... python dump_raw_status.py
"""

import asyncio
import os
import sys

from bleak import BleakClient, BleakScanner

# VisionAir BLE protocol constants
MAGIC = b"\xa5\xb6"
STATUS_CHAR_UUID = "0003caa2-0000-1000-8000-00805f9b0131"
COMMAND_CHAR_UUID = "0003cbb1-0000-1000-8000-00805f9b0131"
STATUS_REQUEST = bytes.fromhex("a5b6100005030000000016")


def hexdump(data: bytes, offset: int = 0) -> str:
    """Format bytes as hex dump with offsets."""
    lines = []
    for i in range(0, len(data), 16):
        hex_part = " ".join(f"{b:02x}" for b in data[i:i+16])
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i:i+16])
        lines.append(f"{offset+i:04x}  {hex_part:<48}  {ascii_part}")
    return "\n".join(lines)


def parse_key_bytes(data: bytes) -> dict:
    """Extract key bytes from status packet."""
    if len(data) < 61:
        return {}

    return {
        "device_id_b5_7": int.from_bytes(data[5:8], "little"),  # Bytes 5-7, constant per device
        "humidity_b4": data[4],  # Byte 4: Remote humidity %
        "temp_remote_b8": data[8],
        "volume_b22_23": int.from_bytes(data[22:24], "little"),
        "operating_days_b26_27": int.from_bytes(data[26:28], "little"),
        "filter_days_b28_29": int.from_bytes(data[28:30], "little"),
        "temp_active_b32": data[32],
        "sensor_selector_b34": data[34],
        "temp_probe1_b35": data[35],
        "temp_probe2_b42": data[42],
        "boost_active_b44": data[44],
        "airflow_indicator_b47": data[47],
        "preheat_enabled_b49": data[49],
        "summer_limit_b50": data[50],
        "preheat_temp_b56": data[56],
    }


def parse_history_key_bytes(data: bytes) -> dict:
    """Extract key bytes from history packet."""
    if len(data) < 14:
        return {}

    return {
        "temp_probe1_b6": data[6],
        "humidity_probe1_b8": data[8],
        "temp_probe2_b11": data[11],
        "filter_percent_b13": data[13],
    }


async def main(address: str):
    print(f"Scanning for {address}...")
    device = await BleakScanner.find_device_by_address(address, timeout=10.0)

    if not device:
        print(f"Device {address} not found")
        return

    print(f"Found: {device.name}")
    print("Connecting...")

    async with BleakClient(device, timeout=20.0) as client:
        print(f"Connected! MTU: {client.mtu_size}")

        # Find characteristics
        status_char = None
        command_char = None
        for service in client.services:
            for char in service.characteristics:
                if char.uuid == STATUS_CHAR_UUID:
                    status_char = char
                elif char.uuid == COMMAND_CHAR_UUID:
                    command_char = char

        if not status_char or not command_char:
            print("ERROR: Required characteristics not found")
            return

        # Set up notification handler
        status_data = None
        event = asyncio.Event()

        def handler(sender, data):
            nonlocal status_data
            if bytes(data[:2]) == MAGIC and data[2] == 0x01:
                status_data = bytes(data)
                event.set()

        await client.start_notify(status_char, handler)

        print("\n--- Sending Status Request ---")
        print(f"Request: {STATUS_REQUEST.hex()}")

        await client.write_gatt_char(command_char, STATUS_REQUEST, response=True)

        try:
            await asyncio.wait_for(event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print("ERROR: No response received")
            return
        finally:
            await client.stop_notify(status_char)

        print(f"\n--- Raw Status Response ({len(status_data)} bytes) ---")
        print(hexdump(status_data))

        print("\n--- Key Byte Values ---")
        parsed = parse_key_bytes(status_data)
        for key, value in parsed.items():
            print(f"  {key}: {value}")

        print("\n--- Sensor Selector Interpretation ---")
        selector = parsed.get("sensor_selector_b34", -1)
        sensor_names = {0: "Probe 2 (Air inlet)", 1: "Probe 1 (Resistor)", 2: "Remote Control"}
        print(f"  Active sensor: {sensor_names.get(selector, f'Unknown ({selector})')}")
        print(f"  Active sensor temp (B32): {parsed.get('temp_active_b32')}°C")

        # Now request history packet
        print("\n--- Sending History Request ---")
        history_request = bytes.fromhex("a5b6100605070000000014")
        print(f"Request: {history_request.hex()}")

        history_data = None
        event.clear()

        def history_handler(sender, data):
            nonlocal history_data
            if bytes(data[:2]) == MAGIC and data[2] == 0x03:
                history_data = bytes(data)
                event.set()

        await client.start_notify(status_char, history_handler)
        await client.write_gatt_char(command_char, history_request, response=True)

        try:
            await asyncio.wait_for(event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            print("ERROR: No history response received")
            return
        finally:
            await client.stop_notify(status_char)

        print(f"\n--- Raw History Response ({len(history_data)} bytes) ---")
        print(hexdump(history_data))

        print("\n--- History Key Byte Values ---")
        history_parsed = parse_history_key_bytes(history_data)
        for key, value in history_parsed.items():
            print(f"  {key}: {value}")

        print("\n--- Temperature Comparison: STATUS vs HISTORY ---")
        print(f"  Probe 1:  STATUS B35={parsed.get('temp_probe1_b35')}°C  vs  HISTORY B6={history_parsed.get('temp_probe1_b6')}°C")
        print(f"  Probe 2:  STATUS B42={parsed.get('temp_probe2_b42')}°C  vs  HISTORY B11={history_parsed.get('temp_probe2_b11')}°C")
        print(f"  Remote:   STATUS B8={parsed.get('temp_remote_b8')}°C  (no history equivalent)")
        print(f"  Humidity: STATUS B5={parsed.get('humidity_pct')}%  vs  HISTORY B8={history_parsed.get('humidity_probe1_b8')}%")


if __name__ == "__main__":
    address = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VMI_MAC")
    if not address:
        print("Usage: python dump_raw_status.py <MAC_ADDRESS>")
        print("   or: VMI_MAC=00:A0:50:... python dump_raw_status.py")
        sys.exit(1)
    asyncio.run(main(address))
