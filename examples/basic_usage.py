#!/usr/bin/env python3
"""Basic usage example for visionair-ble.

This example shows how to:
1. Scan for VisionAir devices
2. Connect and read status
3. Display sensor data using metadata
4. Change airflow settings (commented out)

Requirements:
    pip install visionair-ble

Usage:
    python basic_usage.py [MAC_ADDRESS]

If no MAC address is provided, scans for devices first.
"""

import asyncio
import sys

from visionair_ble import VisionAirClient, format_sensors
from visionair_ble.connect import connect_direct, scan_direct


async def main(address: str | None = None):
    # Scan if no address provided
    if not address:
        print("Scanning for VisionAir devices...")
        devices = await scan_direct(timeout=10.0)

        if not devices:
            print("No devices found. Make sure:")
            print("  - Device is powered on")
            print("  - No other app is connected to it")
            print("  - Device is within Bluetooth range")
            return

        print(f"Found {len(devices)} device(s):")
        for addr, name in devices:
            print(f"  {addr} - {name or 'Unknown'}")

        address = devices[0][0]
        print(f"\nConnecting to {address}...")

    # Connect and interact
    async with connect_direct(address) as client:
        visionair = VisionAirClient(client)

        # Get status and display using metadata
        status = await visionair.get_status()
        print(f"\n--- Device {status.device_id} ---")
        print(format_sensors(status))

        # Get live sensor data
        sensors = await visionair.get_sensors()
        print("\n--- Live Sensors ---")
        print(format_sensors(sensors))

        # Show all sensors (including disabled-by-default)
        print("\n--- All Status Fields ---")
        print(format_sensors(status, enabled_only=False))

        # Example: Change airflow (commented out for safety)
        # status = await visionair.set_airflow_mode("medium")
        # print(f"\nNew airflow: {status.airflow} m³/h")


if __name__ == "__main__":
    address = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(address))
