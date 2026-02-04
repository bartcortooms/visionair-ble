"""Standalone connection helpers for VisionAir BLE devices.

This module provides convenience functions for connecting to devices
outside of Home Assistant. For HA integrations, use HA's Bluetooth stack
instead - it handles proxy routing automatically.

Example:
    from visionair_ble import VisionAirClient
    from visionair_ble.connect import connect_direct

    async with connect_direct("00:A0:50:XX:XX:XX") as client:
        visionair = VisionAirClient(client)
        status = await visionair.get_status()
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from bleak import BleakClient, BleakScanner

from .protocol import is_visionair_device

if TYPE_CHECKING:
    from bleak_esphome.backend.client import ESPHomeClient


@asynccontextmanager
async def connect_direct(
    address: str,
    timeout: float = 20.0,
) -> AsyncIterator[BleakClient]:
    """Connect directly to a device via local Bluetooth.

    Use this when the device is within Bluetooth range of the machine.

    Args:
        address: Device MAC address (e.g., "00:A0:50:XX:XX:XX")
        timeout: Connection timeout in seconds

    Yields:
        Connected BleakClient

    Example:
        async with connect_direct("00:A0:50:XX:XX:XX") as client:
            visionair = VisionAirClient(client)
            status = await visionair.get_status()
    """
    client = BleakClient(address, timeout=timeout)
    try:
        await client.connect()
        yield client
    finally:
        if client.is_connected:
            await client.disconnect()


@asynccontextmanager
async def connect_via_proxy(
    proxy_host: str,
    api_key: str,
    device_address: str | None = None,
    proxy_port: int = 6053,
    scan_timeout: float = 10.0,
    connect_timeout: float = 30.0,
) -> AsyncIterator["ESPHomeClient"]:
    """Connect to a device through an ESPHome BLE proxy.

    Use this when the device is out of range of the local machine
    but within range of an ESPHome device with bluetooth_proxy enabled.

    Requires optional dependencies: pip install visionair-ble[proxy]

    Args:
        proxy_host: ESPHome device hostname or IP address
        api_key: ESPHome API encryption key (noise_psk)
        device_address: Device MAC address. If None, scans for device.
        proxy_port: ESPHome API port (default: 6053)
        scan_timeout: Time to wait for device discovery
        connect_timeout: BLE connection timeout

    Yields:
        Connected ESPHomeClient (BleakClient-compatible)

    Example:
        async with connect_via_proxy("192.168.1.100", api_key) as client:
            visionair = VisionAirClient(client)
            status = await visionair.get_status()
    """
    # Import here to make proxy dependencies optional
    from aioesphomeapi import APIClient
    from bleak_esphome import connect_scanner
    from bleak_esphome.backend.client import ESPHomeClient
    import habluetooth

    # Initialize habluetooth manager (required for bleak-esphome)
    manager = habluetooth.BluetoothManager()
    habluetooth.set_manager(manager)

    # Connect to ESPHome proxy
    api_client = APIClient(proxy_host, proxy_port, None, noise_psk=api_key)
    await api_client.connect(login=True)

    try:
        info = await api_client.device_info()

        # Set up BLE scanner
        client_data = connect_scanner(api_client, info, available=True)
        scanner = client_data.scanner
        scanner.async_setup()

        # Wait for device discovery
        await asyncio.sleep(scan_timeout)

        # Find device
        devices = scanner.discovered_devices_and_advertisement_data
        target_device = None

        for addr, (device, _) in devices.items():
            if device_address:
                if addr.upper() == device_address.upper():
                    target_device = device
                    break
            elif is_visionair_device(addr, device.name):
                target_device = device
                break

        if not target_device:
            raise ConnectionError(
                "Device not found. Ensure it's powered on, "
                "not connected to another device, and in range of the proxy."
            )

        # Connect to device
        ble_client = ESPHomeClient(
            target_device,
            client_data=client_data,
            timeout=connect_timeout,
        )
        await ble_client.connect(pair=False)

        try:
            yield ble_client
        finally:
            if ble_client.is_connected:
                await ble_client.disconnect()

    finally:
        await api_client.disconnect()


async def scan_direct(timeout: float = 10.0) -> list[tuple[str, str | None]]:
    """Scan for VisionAir devices using local Bluetooth.

    Args:
        timeout: Scan duration in seconds

    Returns:
        List of (address, name) tuples for discovered devices
    """
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    results = []
    for device, _ in devices.values():
        if is_visionair_device(device.address, device.name):
            results.append((device.address, device.name))
    return results


async def scan_via_proxy(
    proxy_host: str,
    api_key: str,
    proxy_port: int = 6053,
    scan_timeout: float = 10.0,
) -> list[tuple[str, str | None]]:
    """Scan for VisionAir devices through an ESPHome BLE proxy.

    Requires optional dependencies: pip install visionair-ble[proxy]

    Args:
        proxy_host: ESPHome device hostname or IP
        api_key: ESPHome API encryption key
        proxy_port: ESPHome API port
        scan_timeout: How long to scan

    Returns:
        List of (address, name) tuples for discovered devices
    """
    from aioesphomeapi import APIClient
    from bleak_esphome import connect_scanner
    import habluetooth

    manager = habluetooth.BluetoothManager()
    habluetooth.set_manager(manager)

    api_client = APIClient(proxy_host, proxy_port, None, noise_psk=api_key)
    await api_client.connect(login=True)

    try:
        info = await api_client.device_info()
        client_data = connect_scanner(api_client, info, available=True)
        scanner = client_data.scanner
        scanner.async_setup()

        await asyncio.sleep(scan_timeout)

        devices = scanner.discovered_devices_and_advertisement_data
        results = []
        for addr, (device, _) in devices.items():
            if is_visionair_device(addr, device.name):
                results.append((addr, device.name))
        return results

    finally:
        await api_client.disconnect()
