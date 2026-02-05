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
            if bytes(data[:2]) == MAGIC and data[2] == PacketType.STATUS_RESPONSE:
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
            if bytes(data[:2]) == MAGIC and data[2] == PacketType.SENSOR_RESPONSE:
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

    async def get_fresh_status(self, timeout: float = 10.0) -> DeviceStatus:
        """Get device status with fresh sensor readings.

        This method explicitly requests readings from each sensor (Probe2,
        Probe1, Remote) to collect fresh temperature values, and also fetches
        Probe 1 humidity from the sensor packet. The regular get_status()
        method may return stale cached values.

        Humidity sources:
        - Remote humidity: STATUS packet byte 5
        - Probe 1 humidity: SENSOR packet byte 8
        - Probe 2: No humidity sensor

        Args:
            timeout: How long to wait for each response in seconds

        Returns:
            DeviceStatus with fresh temperature and humidity readings

        Raises:
            TimeoutError: If no response within timeout
        """
        self._find_characteristics()

        fresh_temps: dict[int, int] = {}  # selector -> temp
        last_status_data: bytes | None = None
        probe1_humidity: int | None = None

        event = asyncio.Event()
        current_data: bytes | None = None
        expected_type: int = PacketType.STATUS_RESPONSE

        def handler(*args: Any) -> None:
            nonlocal current_data
            data = args[-1]
            if bytes(data[:2]) == MAGIC and data[2] == expected_type:
                current_data = bytes(data)
                event.set()

        await self._client.start_notify(self._status_char, handler)
        try:
            # Request fresh temperature readings from each sensor
            # Sensor 0 = Probe2 (inlet), 1 = Probe1 (outlet), 2 = Remote
            for sensor in (0, 1, 2):
                event.clear()
                current_data = None
                await self._client.write_gatt_char(
                    self._command_char, build_sensor_select_request(sensor), response=True
                )
                await asyncio.wait_for(event.wait(), timeout=timeout)

                if current_data and len(current_data) >= 43:
                    selector = current_data[34]
                    # Byte 32 contains fresh temperature for selected sensor
                    fresh_temps[selector] = current_data[32]
                    last_status_data = current_data

            # Request sensor packet for Probe 1 humidity
            event.clear()
            current_data = None
            expected_type = PacketType.SENSOR_RESPONSE
            await self._client.write_gatt_char(
                self._command_char, build_sensor_request(), response=True
            )
            await asyncio.wait_for(event.wait(), timeout=timeout)

            if current_data and len(current_data) >= 9:
                probe1_humidity = current_data[8]
        finally:
            await self._client.stop_notify(self._status_char)

        if not last_status_data:
            raise TimeoutError("No status response received")

        # Parse the last status packet for base values
        status = parse_status(last_status_data)
        if not status:
            raise ValueError("Invalid status response")

        # Override with fresh sensor readings
        from dataclasses import replace

        if 0 in fresh_temps:
            status = replace(status, temp_probe2=fresh_temps[0])
        if 1 in fresh_temps:
            status = replace(status, temp_probe1=fresh_temps[1])
        if 2 in fresh_temps:
            status = replace(status, temp_remote=fresh_temps[2])
        if probe1_humidity is not None:
            status = replace(status, humidity_probe1=probe1_humidity)

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
