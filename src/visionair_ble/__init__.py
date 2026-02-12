"""VisionAir BLE - Unofficial library for VisionAir ventilation devices.

This library provides an interface for controlling Ventilairsec VisionAir
(Vision'R range) ventilation devices over Bluetooth Low Energy.

Supported devices:
- Purevent Vision'R (350 m³/h max)
- Urban Vision'R (201 m³/h max)
- Cube Vision'R

Disclaimer: This project is not affiliated with, endorsed by, or connected to
Ventilairsec, Purevent, VisionAir, or any related companies. All trademarks
are the property of their respective owners.

Basic Usage:
    from visionair_ble import VisionAirClient
    from visionair_ble.connect import connect_direct

    async with connect_direct("00:A0:50:XX:XX:XX") as client:
        visionair = VisionAirClient(client)
        status = await visionair.get_status()
        print(f"Airflow: {status.airflow} m³/h ({status.airflow_mode})")
        await visionair.set_airflow_mode("medium")

Home Assistant Integration:
    from visionair_ble import VisionAirClient

    # HA provides the BLEDevice and handles proxy routing automatically
    ble_device = async_ble_device_from_address(hass, "00:A0:50:XX:XX:XX")
    async with BleakClient(ble_device) as client:
        visionair = VisionAirClient(client)
        status = await visionair.get_status()

Via ESPHome Proxy:
    from visionair_ble import VisionAirClient
    from visionair_ble.connect import connect_via_proxy

    async with connect_via_proxy("192.168.1.100", api_key) as client:
        visionair = VisionAirClient(client)
        await visionair.set_airflow_high()
"""

from __future__ import annotations

from .client import VisionAirClient
from .protocol import (
    # Constants
    AIRFLOW_HIGH,
    AIRFLOW_LOW,
    AIRFLOW_MEDIUM,
    COMMAND_CHAR_UUID,
    STATUS_CHAR_UUID,
    VISIONAIR_MAC_PREFIX,
    # Data classes
    DeviceStatus,
    ScheduleConfig,
    ScheduleSlot,
    SensorData,
    # Functions
    build_boost_command,
    build_full_data_request,
    build_holiday_command,
    build_preheat_request,
    build_schedule_config_request,
    build_schedule_toggle,
    build_schedule_write,
    build_sensor_request,
    build_mode_select_request,
    build_sync_packet,
    build_status_request,
    calc_checksum,
    format_sensors,
    is_visionair_device,
    parse_schedule_config,
    parse_schedule_data,
    parse_sensors,
    parse_status,
)

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # Primary interface
    "VisionAirClient",
    # Data classes
    "DeviceStatus",
    "ScheduleConfig",
    "ScheduleSlot",
    "SensorData",
    # Constants
    "AIRFLOW_LOW",
    "AIRFLOW_MEDIUM",
    "AIRFLOW_HIGH",
    "STATUS_CHAR_UUID",
    "COMMAND_CHAR_UUID",
    "VISIONAIR_MAC_PREFIX",
    # Protocol functions (for advanced use)
    "build_boost_command",
    "build_full_data_request",
    "build_holiday_command",
    "build_preheat_request",
    "build_schedule_config_request",
    "build_schedule_toggle",
    "build_schedule_write",
    "build_sensor_request",
    "build_mode_select_request",
    "build_sync_packet",
    "build_status_request",
    "calc_checksum",
    "format_sensors",
    "is_visionair_device",
    "parse_schedule_config",
    "parse_schedule_data",
    "parse_sensors",
    "parse_status",
]
