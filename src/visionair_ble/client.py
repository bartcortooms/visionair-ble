"""VisionAir BLE Client - Primary interface for controlling devices.

This module provides VisionAirClient, which wraps a connected BleakClient
(or compatible client like ESPHomeClient) with device-specific operations.

Example:
    async with BleakClient(device) as client:
        visionair = VisionAirClient(client)
        status = await visionair.get_status()
        print(f"Airflow: {status.airflow} m³/h ({status.airflow_mode})")
        print(f"Configured volume: {status.configured_volume} m³")
        await visionair.set_airflow_mode("medium")
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .protocol import (
    AIRFLOW_HIGH,
    AIRFLOW_LOW,
    AIRFLOW_MEDIUM,
    COMMAND_CHAR_UUID,
    MAGIC,
    STATUS_CHAR_UUID,
    AirflowLevel,
    DeviceStatus,
    PacketType,
    SensorData,
    build_boost_command,
    build_sensor_request,
    build_sensor_select_request,
    build_settings_packet,
    build_status_request,
    parse_sensors,
    parse_status,
)

if TYPE_CHECKING:
    from bleak import BleakClient


class VisionAirClient:
    """Client for controlling VisionAir ventilation devices.

    This is the primary interface for controlling VisionAir devices
    (Purevent, Urban, Cube Vision'R). It wraps a connected BLE client
    and provides high-level operations.

    The caller is responsible for connection lifecycle - this class
    provides the protocol operations only.

    Works with both BleakClient (direct) and ESPHomeClient (proxy).

    Args:
        client: Connected BleakClient or compatible (e.g., ESPHomeClient)

    Example:
        async with BleakClient(device) as client:
            visionair = VisionAirClient(client)
            status = await visionair.get_status()
            print(f"Airflow: {status.airflow} m³/h")
            await visionair.set_airflow_mode("medium")
    """

    def __init__(self, client: "BleakClient") -> None:
        self._client = client
        self._last_status: DeviceStatus | None = None
        self._status_char: Any = None
        self._command_char: Any = None

    def _find_characteristics(self) -> None:
        """Find device characteristics from services.

        ESPHomeClient requires characteristic objects, not UUID strings.
        BleakClient accepts both, so we use objects for compatibility.
        """
        if self._status_char is not None:
            return

        for svc in self._client.services:
            for char in svc.characteristics:
                if char.uuid == STATUS_CHAR_UUID:
                    self._status_char = char
                elif char.uuid == COMMAND_CHAR_UUID:
                    self._command_char = char

        if not self._status_char or not self._command_char:
            raise RuntimeError(
                f"Device characteristics not found. "
                f"Expected {STATUS_CHAR_UUID} and {COMMAND_CHAR_UUID}"
            )

    async def get_status(self, timeout: float = 10.0) -> DeviceStatus:
        """Get current device status.

        Args:
            timeout: How long to wait for response in seconds

        Returns:
            DeviceStatus with current device state

        Raises:
            TimeoutError: If no response within timeout
        """
        self._find_characteristics()

        status_data: bytes | None = None
        event = asyncio.Event()

        def handler(*args: Any) -> None:
            nonlocal status_data
            data = args[-1]  # data is always last arg
            if bytes(data[:2]) == MAGIC and data[2] == PacketType.DEVICE_STATE:
                status_data = bytes(data)
                event.set()

        await self._client.start_notify(self._status_char, handler)
        try:
            await self._client.write_gatt_char(
                self._command_char, build_status_request(), response=True
            )
            await asyncio.wait_for(event.wait(), timeout=timeout)
        finally:
            await self._client.stop_notify(self._status_char)

        if not status_data:
            raise TimeoutError("No status response received")

        status = parse_status(status_data)
        if not status:
            raise ValueError("Invalid status response")

        self._last_status = status
        return status

    async def get_sensors(self, timeout: float = 10.0) -> SensorData:
        """Get live sensor measurements (temperatures, humidity).

        Args:
            timeout: How long to wait for response in seconds

        Returns:
            SensorData with current temperature and humidity readings

        Raises:
            TimeoutError: If no response within timeout
        """
        self._find_characteristics()

        sensor_data: bytes | None = None
        event = asyncio.Event()

        def handler(*args: Any) -> None:
            nonlocal sensor_data
            data = args[-1]
            if bytes(data[:2]) == MAGIC and data[2] == PacketType.PROBE_SENSORS:
                sensor_data = bytes(data)
                event.set()

        await self._client.start_notify(self._status_char, handler)
        try:
            await self._client.write_gatt_char(
                self._command_char, build_sensor_request(), response=True
            )
            await asyncio.wait_for(event.wait(), timeout=timeout)
        finally:
            await self._client.stop_notify(self._status_char)

        if not sensor_data:
            raise TimeoutError("No sensor response received")

        sensors = parse_sensors(sensor_data)
        if not sensors:
            raise ValueError("Invalid sensor response")

        return sensors

    async def get_fresh_status(
        self,
        timeout: float = 5.0,
        retries: int = 2,
        delay: float = 0.5,
    ) -> DeviceStatus:
        """Get device status with fresh sensor readings.

        This method requests probe sensor data and switches to the remote
        sensor to collect fresh temperature and humidity values. The regular
        get_status() method returns only the currently-selected sensor's
        temperature.

        The handler collects ALL notifications without filtering by type,
        since the device has limited notification throughput through ESPHome
        proxies and we can't afford to miss any.

        Humidity sources:
        - Remote humidity: DEVICE_STATE packet byte 4 (always present)
        - Probe 1 humidity: PROBE_SENSORS packet byte 8
        - Probe 2: No humidity sensor

        Args:
            timeout: How long to wait for each notification in seconds
            retries: Number of retry attempts for remote temp
            delay: Delay between retries in seconds

        Returns:
            DeviceStatus with fresh temperature and humidity readings

        Raises:
            TimeoutError: If no status responses received at all
        """
        self._find_characteristics()
        from dataclasses import replace

        probe_data: bytes | None = None
        state_packets: list[bytes] = []
        new_packet = asyncio.Event()

        def handler(*args: Any) -> None:
            nonlocal probe_data
            data = bytes(args[-1])
            if bytes(data[:2]) != MAGIC:
                return
            if data[2] == PacketType.PROBE_SENSORS:
                probe_data = data
            elif data[2] == PacketType.DEVICE_STATE:
                state_packets.append(data)
            new_packet.set()

        await self._client.start_notify(self._status_char, handler)
        try:
            # Send three commands in quick succession:
            # 1. Sensor request → PROBE_SENSORS (probe1/probe2 temps, probe1 humidity)
            # 2. sensor_select(2) → switch to remote sensor
            # 3. Status request → DEVICE_STATE (with remote temp when selector=2)
            for cmd in [
                build_sensor_request(),
                build_sensor_select_request(2),
                build_status_request(),
            ]:
                if not self._client.is_connected:
                    break
                await self._client.write_gatt_char(
                    self._command_char, cmd, response=True
                )

            # Collect notifications until we have everything or timeout.
            # We expect up to 3 responses: PROBE_SENSORS, stale DEVICE_STATE
            # from sensor_select, and fresh DEVICE_STATE from status request.
            for _ in range(5):
                if not self._client.is_connected:
                    break
                new_packet.clear()
                try:
                    await asyncio.wait_for(new_packet.wait(), timeout=timeout)
                except TimeoutError:
                    break  # No more notifications coming
                has_remote = any(
                    len(p) >= 43 and p[34] == 2 for p in state_packets
                )
                if probe_data and has_remote:
                    break

            # Retry status requests if we don't have remote temp yet
            for _ in range(retries):
                has_remote = any(
                    len(p) >= 43 and p[34] == 2 for p in state_packets
                )
                if has_remote or not self._client.is_connected:
                    break
                await asyncio.sleep(delay)
                new_packet.clear()
                try:
                    await self._client.write_gatt_char(
                        self._command_char, build_status_request(), response=True
                    )
                    await asyncio.wait_for(new_packet.wait(), timeout=timeout)
                except (TimeoutError, Exception):
                    pass

        finally:
            try:
                await self._client.stop_notify(self._status_char)
            except Exception:
                pass

        # Find best DEVICE_STATE packet (prefer one with selector=2)
        status_data: bytes | None = None
        remote_temp: int | None = None
        for pkt in state_packets:
            if len(pkt) >= 43:
                if status_data is None:
                    status_data = pkt
                if pkt[34] == 2:
                    status_data = pkt
                    remote_temp = pkt[32]

        if not status_data:
            raise TimeoutError("No status response received")

        status = parse_status(status_data)
        if not status:
            raise ValueError("Invalid status response")

        # Override with probe sensor readings (independent of sensor selection)
        sensors = parse_sensors(probe_data) if probe_data else None
        if sensors:
            if sensors.temp_probe1 is not None:
                status = replace(status, temp_probe1=sensors.temp_probe1)
            if sensors.temp_probe2 is not None:
                status = replace(status, temp_probe2=sensors.temp_probe2)
            if sensors.humidity_probe1 is not None:
                status = replace(status, humidity_probe1=sensors.humidity_probe1)

        if remote_temp is not None:
            status = replace(status, temp_remote=remote_temp)

        self._last_status = status
        return status

    async def set_airflow_mode(
        self,
        mode: str,
        preheat_enabled: bool | None = None,
        summer_limit_enabled: bool | None = None,
        preheat_temp: int | None = None,
        timeout: float = 10.0,
    ) -> DeviceStatus:
        """Set airflow mode and optionally other settings.

        This is the recommended method for controlling airflow, as it works
        with any installation regardless of configured volume.

        Settings not explicitly provided will be preserved from the device's
        current state (fetched automatically if needed).

        Args:
            mode: Airflow mode ("low", "medium", or "high")
            preheat_enabled: Enable winter preheat (None = keep current)
            summer_limit_enabled: Enable summer limit (None = keep current)
            preheat_temp: Preheat temperature in °C (None = keep current)
            timeout: How long to wait for acknowledgment

        Returns:
            Updated DeviceStatus after change

        Raises:
            ValueError: If mode is invalid
            TimeoutError: If no acknowledgment received
        """
        mode = mode.lower()
        if mode not in ("low", "medium", "high"):
            raise ValueError("Mode must be 'low', 'medium', or 'high'")

        # Map mode to protocol airflow value (these are protocol constants)
        airflow = {"low": AIRFLOW_LOW, "medium": AIRFLOW_MEDIUM, "high": AIRFLOW_HIGH}[mode]
        return await self.set_airflow(
            airflow, preheat_enabled, summer_limit_enabled, preheat_temp, timeout
        )

    async def set_airflow(
        self,
        airflow: int,
        preheat_enabled: bool | None = None,
        summer_limit_enabled: bool | None = None,
        preheat_temp: int | None = None,
        timeout: float = 10.0,
    ) -> DeviceStatus:
        """Set airflow level and optionally other settings.

        Note: The airflow values (131, 164, 201) are protocol constants that
        map to LOW, MEDIUM, HIGH modes. The actual m³/h output depends on your
        installation's configured volume. Consider using set_airflow_mode()
        instead for clearer code.

        Settings not explicitly provided will be preserved from the device's
        current state (fetched automatically if needed).

        Args:
            airflow: Protocol airflow value (131=LOW, 164=MEDIUM, 201=HIGH)
            preheat_enabled: Enable winter preheat (None = keep current)
            summer_limit_enabled: Enable summer limit (None = keep current)
            preheat_temp: Preheat temperature in °C (None = keep current)
            timeout: How long to wait for acknowledgment

        Returns:
            Updated DeviceStatus after change

        Raises:
            ValueError: If airflow value is invalid
            TimeoutError: If no acknowledgment received
        """
        if airflow not in (AIRFLOW_LOW, AIRFLOW_MEDIUM, AIRFLOW_HIGH):
            raise ValueError(
                f"Airflow must be {AIRFLOW_LOW}, {AIRFLOW_MEDIUM}, or {AIRFLOW_HIGH}"
            )

        self._find_characteristics()

        # Get current status to preserve unspecified settings
        if self._last_status is None:
            await self.get_status()

        current = self._last_status
        if current is None:
            preheat = preheat_enabled if preheat_enabled is not None else True
            summer = summer_limit_enabled if summer_limit_enabled is not None else True
            temp = preheat_temp if preheat_temp is not None else 16
        else:
            preheat = (
                preheat_enabled if preheat_enabled is not None else current.preheat_enabled
            )
            summer = (
                summer_limit_enabled
                if summer_limit_enabled is not None
                else current.summer_limit_enabled
            )
            temp = preheat_temp if preheat_temp is not None else current.preheat_temp

        packet = build_settings_packet(preheat, summer, temp, airflow)

        ack_received = asyncio.Event()

        def handler(*args: Any) -> None:
            data = args[-1]
            if bytes(data[:2]) == MAGIC and data[2] == PacketType.SETTINGS_ACK:
                ack_received.set()

        await self._client.start_notify(self._status_char, handler)
        try:
            await self._client.write_gatt_char(self._command_char, packet, response=True)
            await asyncio.wait_for(ack_received.wait(), timeout=timeout)
        finally:
            await self._client.stop_notify(self._status_char)

        # Get updated status
        await asyncio.sleep(0.5)
        return await self.get_status()

    async def set_airflow_low(self) -> DeviceStatus:
        """Set airflow to low level.

        The actual m³/h output is calculated as: configured_volume × 0.36 ACH
        """
        return await self.set_airflow_mode("low")

    async def set_airflow_medium(self) -> DeviceStatus:
        """Set airflow to medium level.

        The actual m³/h output is calculated as: configured_volume × 0.45 ACH
        """
        return await self.set_airflow_mode("medium")

    async def set_airflow_high(self) -> DeviceStatus:
        """Set airflow to high level.

        The actual m³/h output is calculated as: configured_volume × 0.55 ACH
        """
        return await self.set_airflow_mode("high")

    async def set_boost(self, enable: bool, timeout: float = 10.0) -> DeviceStatus:
        """Enable or disable BOOST mode.

        BOOST mode runs the fan at maximum for 30 minutes, then auto-deactivates.

        Args:
            enable: True to enable BOOST, False to disable
            timeout: How long to wait for acknowledgment

        Returns:
            Updated DeviceStatus after change
        """
        self._find_characteristics()

        packet = build_boost_command(enable)

        ack_received = asyncio.Event()

        def handler(*args: Any) -> None:
            data = args[-1]
            if bytes(data[:2]) == MAGIC and data[2] == PacketType.SETTINGS_ACK:
                ack_received.set()

        await self._client.start_notify(self._status_char, handler)
        try:
            await self._client.write_gatt_char(self._command_char, packet, response=True)
            await asyncio.wait_for(ack_received.wait(), timeout=timeout)
        finally:
            await self._client.stop_notify(self._status_char)

        await asyncio.sleep(0.5)
        return await self.get_status()

    async def set_preheat(
        self,
        enabled: bool,
        temperature: int | None = None,
    ) -> DeviceStatus:
        """Enable or disable winter preheat.

        Args:
            enabled: Whether to enable preheat
            temperature: Target temperature in °C (None = keep current)

        Returns:
            Updated DeviceStatus
        """
        if self._last_status is None:
            await self.get_status()

        current = self._last_status
        mode = current.airflow_mode if current and current.airflow_mode != "unknown" else "medium"

        return await self.set_airflow_mode(
            mode=mode,
            preheat_enabled=enabled,
            preheat_temp=temperature,
        )

    async def set_summer_limit(self, enabled: bool) -> DeviceStatus:
        """Enable or disable summer limit.

        Args:
            enabled: Whether to enable summer limit

        Returns:
            Updated DeviceStatus
        """
        if self._last_status is None:
            await self.get_status()

        current = self._last_status
        mode = current.airflow_mode if current and current.airflow_mode != "unknown" else "medium"

        return await self.set_airflow_mode(
            mode=mode,
            summer_limit_enabled=enabled,
        )

    @property
    def last_status(self) -> DeviceStatus | None:
        """Return the most recently fetched status, or None."""
        return self._last_status
