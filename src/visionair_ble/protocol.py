"""VisionAir BLE Protocol - Packet building and parsing.

This module contains the reverse-engineered protocol for communicating with
Ventilairsec VisionAir (Vision'R range) ventilation devices over Bluetooth Low Energy.

Supported devices:
- Purevent Vision'R (350 m³/h max)
- Urban Vision'R (201 m³/h max)
- Cube Vision'R

Protocol overview:
- All packets start with magic bytes 0xa5 0xb6
- Packet type in byte 2: 0x01=status, 0x03=sensors, 0x10=request, 0x1a=settings, 0x23=ack
- Settings packets use XOR checksum (all bytes after magic, excluding final checksum byte)
- BLE uses Cypress PSoC demo profile UUIDs (vendor reused generic UUIDs)
- All devices advertise as "VisionAir" over BLE

Important: The status packet (0x01) contains device configuration but often has stale
temperature readings. The sensor packet (0x03) contains live/current temperature and
humidity measurements. Always use get_sensors() for accurate temperature readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple


def sensor(
    name: str,
    *,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str = "measurement",
    enabled_default: bool = True,
    options: list[str] | None = None,
    precision: int | None = None,
) -> dict:
    """Create field metadata for a sensor.

    Args:
        name: Human-readable sensor name
        unit: Unit of measurement (e.g., "°C", "%", "m³/h")
        device_class: HA device class (temperature, humidity, etc.)
        state_class: HA state class (measurement, total_increasing)
        enabled_default: Whether sensor is enabled by default
        options: Valid options for enum sensors
        precision: Suggested display precision (decimal places)
    """
    meta = {
        "sensor": True,
        "name": name,
        "enabled_default": enabled_default,
    }
    if unit:
        meta["unit"] = unit
    if device_class:
        meta["device_class"] = device_class
    if state_class:
        meta["state_class"] = state_class
    if options:
        meta["options"] = options
        meta["device_class"] = "enum"
    if precision is not None:
        meta["precision"] = precision
    return meta


def format_sensors(data: "DeviceStatus | SensorData", enabled_only: bool = True) -> str:
    """Format sensor data for display using field metadata.

    Args:
        data: DeviceStatus or SensorData instance
        enabled_only: If True, only show sensors enabled by default

    Returns:
        Formatted string with sensor names, values, and units
    """
    import dataclasses

    lines = []
    for f in dataclasses.fields(data):
        meta = f.metadata
        if not meta.get("sensor"):
            continue
        if enabled_only and not meta.get("enabled_default", True):
            continue

        value = getattr(data, f.name)
        if value is None:
            continue

        name = meta.get("name", f.name)
        unit = meta.get("unit", "")

        # Format value
        if isinstance(value, float):
            formatted = f"{value:.1f}"
        elif isinstance(value, bool):
            formatted = "Yes" if value else "No"
        else:
            formatted = str(value)

        if unit:
            lines.append(f"{name}: {formatted} {unit}")
        else:
            lines.append(f"{name}: {formatted}")

    return "\n".join(lines)

# Magic prefix for all packets
MAGIC = b"\xa5\xb6"

# BLE GATT UUIDs (Cypress PSoC demo profile, reused by vendor)
STATUS_CHAR_UUID = "0003caa2-0000-1000-8000-00805f9b0131"  # Notify
COMMAND_CHAR_UUID = "0003cbb1-0000-1000-8000-00805f9b0131"  # Write

# BLE handles (for direct handle-based connections)
CMD_HANDLE = 0x0013
NOTIFY_HANDLE = 0x000E
CCCD_HANDLE = 0x000F

# Device identification
VISIONAIR_MAC_PREFIX = "00:A0:50"
DEVICE_NAMES = ("visionair", "purevent", "urban", "cube")

# Airflow mode protocol values
# These are internal protocol identifiers, NOT actual m³/h values.
# The actual m³/h is calculated from configured_volume × ACH rate.
AIRFLOW_LOW = 131      # Protocol identifier for LOW mode
AIRFLOW_MEDIUM = 164   # Protocol identifier for MEDIUM mode
AIRFLOW_HIGH = 201     # Protocol identifier for HIGH mode

# Airflow mode -> (byte1, byte2) for settings packet
# These byte pairs are universal mode selectors - the device firmware
# applies the appropriate airflow based on its volume calibration.
AIRFLOW_BYTES: dict[int, tuple[int, int]] = {
    AIRFLOW_LOW: (0x19, 0x0A),     # LOW mode
    AIRFLOW_MEDIUM: (0x28, 0x15),  # MEDIUM mode
    AIRFLOW_HIGH: (0x07, 0x30),    # HIGH mode
}

# Status response byte 47 -> airflow mode protocol value
AIRFLOW_INDICATOR: dict[int, int] = {
    38: AIRFLOW_LOW,     # 0x26
    104: AIRFLOW_MEDIUM, # 0x68
    194: AIRFLOW_HIGH,   # 0xC2
}

# Sensor selector (status byte 34)
SENSOR_NAMES: dict[int, str] = {
    0: "Probe 2 (Air inlet)",
    1: "Probe 1 (Resistor outlet)",
    2: "Remote Control",
}


class AirflowBytes(NamedTuple):
    """Airflow encoding as two bytes."""

    byte1: int
    byte2: int


@dataclass
class DeviceStatus:
    """Device status from status packet (type 0x01).

    Fields with sensor metadata will be auto-discovered by the HA integration.
    """

    # Internal fields (no sensor metadata)
    device_id: int
    airflow_indicator: int
    sensor_selector: int
    sensor_name: str

    # Sensors - airflow
    airflow: int = field(metadata=sensor("Airflow", unit="m³/h", device_class="volume_flow_rate"))
    airflow_mode: str = field(metadata=sensor(
        "Airflow mode", options=["low", "medium", "high", "unknown"]
    ))
    configured_volume: int | None = field(default=None, metadata=sensor(
        "Configured volume", unit="m³", enabled_default=False
    ))
    airflow_low: int | None = field(default=None, metadata=sensor(
        "Airflow low", unit="m³/h", device_class="volume_flow_rate", enabled_default=False
    ))
    airflow_medium: int | None = field(default=None, metadata=sensor(
        "Airflow medium", unit="m³/h", device_class="volume_flow_rate", enabled_default=False
    ))
    airflow_high: int | None = field(default=None, metadata=sensor(
        "Airflow high", unit="m³/h", device_class="volume_flow_rate", enabled_default=False
    ))

    # Sensors - temperatures
    temp_remote: int | None = field(default=None, metadata=sensor(
        "Room temperature", unit="°C", device_class="temperature", precision=0
    ))
    temp_probe1: int | None = field(default=None, metadata=sensor(
        "Outlet temperature", unit="°C", device_class="temperature", precision=0
    ))
    temp_probe2: int | None = field(default=None, metadata=sensor(
        "Inlet temperature", unit="°C", device_class="temperature", precision=0
    ))

    # Sensors - humidity
    humidity_remote: float | None = field(default=None, metadata=sensor(
        "Room humidity", unit="%", device_class="humidity", precision=0
    ))

    # Sensors - equipment life
    filter_days: int | None = field(default=None, metadata=sensor(
        "Filter days remaining", unit="d", device_class="duration"
    ))
    operating_days: int | None = field(default=None, metadata=sensor(
        "Operating days", unit="d", device_class="duration", state_class="total_increasing", enabled_default=False
    ))

    # Sensors - settings (read-only display of current settings)
    preheat_enabled: bool = field(default=False, metadata=sensor(
        "Preheat enabled", enabled_default=False
    ))
    preheat_temp: int = field(default=0, metadata=sensor(
        "Preheat setpoint", unit="°C", device_class="temperature", enabled_default=False, precision=0
    ))
    summer_limit_enabled: bool = field(default=False, metadata=sensor(
        "Summer limit enabled", enabled_default=False
    ))
    summer_limit_temp: int | None = field(default=None, metadata=sensor(
        "Summer limit setpoint", unit="°C", device_class="temperature", enabled_default=False, precision=0
    ))
    boost_active: bool = field(default=False, metadata=sensor(
        "Boost active", enabled_default=False
    ))



@dataclass
class SensorData:
    """Live sensor data from measurement packet (type 0x03).

    This packet contains the most current temperature and humidity readings.
    The status packet (0x01) temperatures are often stale/cached.
    """

    temp_probe1: int | None = field(default=None, metadata=sensor(
        "Outlet temperature (live)", unit="°C", device_class="temperature", precision=0
    ))
    temp_probe2: int | None = field(default=None, metadata=sensor(
        "Inlet temperature (live)", unit="°C", device_class="temperature", precision=0
    ))
    humidity_probe1: int | None = field(default=None, metadata=sensor(
        "Outlet humidity", unit="%", device_class="humidity", precision=0
    ))
    filter_percent: int | None = field(default=None, metadata=sensor(
        "Filter remaining", unit="%", enabled_default=False
    ))


def calc_checksum(data: bytes) -> int:
    """Calculate XOR checksum for packet payload.

    Args:
        data: Payload bytes (excluding magic prefix and final checksum)

    Returns:
        Single byte checksum (XOR of all bytes)
    """
    result = 0
    for b in data:
        result ^= b
    return result


def verify_checksum(packet: bytes) -> bool:
    """Verify packet checksum.

    Args:
        packet: Complete packet including magic prefix and checksum

    Returns:
        True if checksum is valid
    """
    if len(packet) < 4 or packet[:2] != MAGIC:
        return False
    expected = packet[-1]
    calculated = calc_checksum(packet[2:-1])
    return calculated == expected


def build_status_request() -> bytes:
    """Build a status request packet.

    Returns:
        Complete packet bytes: a5b6100005030000000016
    """
    return bytes.fromhex("a5b6100005030000000016")


def build_sensor_request() -> bytes:
    """Build a sensor/measurement request packet.

    Returns:
        Complete packet bytes: a5b6100605070000000014
    """
    return bytes.fromhex("a5b6100605070000000014")


def build_sensor_cycle_request() -> bytes:
    """Build an extended status request that cycles through sensors.

    Each time this command is sent, the device cycles to the next sensor
    (Probe2 → Remote → Probe1 → Probe2 → ...) and returns fresh data for
    that sensor in the "active sensor" bytes (32 = temp, 60 = humidity).

    To get fresh readings for all sensors, send this command 3 times.

    Returns:
        Complete packet bytes: a5b6100605180000000209
    """
    return bytes.fromhex("a5b6100605180000000209")


def build_boost_command(enable: bool) -> bytes:
    """Build a BOOST mode command packet.

    Args:
        enable: True to enable BOOST, False to disable

    Returns:
        Complete packet bytes
    """
    if enable:
        return bytes.fromhex("a5b610060519000000010b")
    else:
        return bytes.fromhex("a5b610060519000000000a")


# =============================================================================
# Special Modes (Holiday, Night Ventilation, Fixed Air Flow)
# =============================================================================
#
# All special modes use Settings command with byte 7 = 0x04.
# Bytes 8-9-10 encode HH:MM:SS timestamp of activation time.
#
# The device distinguishes modes based on preceding query packets:
# - Holiday: Query 0x1a sets days, then Settings 0x04 activates
# - Night Ventilation: Direct Settings 0x04 activation
# - Fixed Air Flow: Direct Settings 0x04 activation


def build_holiday_days_query(days: int) -> bytes:
    """Build query to set Holiday mode duration.

    This should be sent before build_holiday_activate() to set
    the number of days the device will run in Holiday mode.

    Args:
        days: Number of days (typically 1-30)

    Returns:
        Complete packet bytes
    """
    payload = bytes([0x10, 0x06, 0x05, 0x1A, 0x00, 0x00, 0x00, days])
    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


def build_holiday_status_query() -> bytes:
    """Build query to get Holiday mode status.

    Returns type 0x50 response with current Holiday mode state.

    Returns:
        Complete packet bytes
    """
    return bytes.fromhex("a5b61006052c000000003f")


def build_special_mode_command(preheat_enabled: bool = True) -> bytes:
    """Build a special mode activation command.

    Used for Holiday, Night Ventilation, and Fixed Air Flow modes.
    The specific mode is determined by preceding query packets:
    - For Holiday: send build_holiday_days_query() first
    - For Night Vent / Fixed Air Flow: send directly

    The command includes the current time as HH:MM:SS timestamp.

    Args:
        preheat_enabled: Whether to enable preheat during the mode

    Returns:
        Complete packet bytes
    """
    now = datetime.now()
    payload = bytes([
        0x1A,
        0x06,
        0x06,
        0x1A,
        0x02 if preheat_enabled else 0x00,  # byte 6: preheat
        0x04,                                # byte 7: special mode flag
        now.hour,                            # byte 8: hour
        now.minute,                          # byte 9: minute
        now.second,                          # byte 10: second
    ])
    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


def build_holiday_activate(days: int, preheat_enabled: bool = True) -> list[bytes]:
    """Build complete Holiday mode activation sequence.

    Returns a list of packets that should be sent in order:
    1. Days query to set duration
    2. Special mode command to activate

    Args:
        days: Number of days for Holiday mode (typically 1-30)
        preheat_enabled: Whether to enable preheat during Holiday

    Returns:
        List of packet bytes to send in sequence
    """
    return [
        build_holiday_days_query(days),
        build_special_mode_command(preheat_enabled),
    ]


def build_night_ventilation_activate(preheat_enabled: bool = True) -> bytes:
    """Build Night Ventilation mode activation command.

    Night Ventilation provides increased ventilation overnight.

    Args:
        preheat_enabled: Whether to enable preheat during the mode

    Returns:
        Complete packet bytes
    """
    return build_special_mode_command(preheat_enabled)


def build_fixed_airflow_activate(preheat_enabled: bool = True) -> bytes:
    """Build Fixed Air Flow mode activation command.

    Fixed Air Flow maintains a constant ventilation rate.

    Args:
        preheat_enabled: Whether to enable preheat during the mode

    Returns:
        Complete packet bytes
    """
    return build_special_mode_command(preheat_enabled)


def build_settings_packet(
    preheat_enabled: bool,
    summer_limit_enabled: bool,
    preheat_temp: int,
    airflow: int,
) -> bytes:
    """Build a settings command packet.

    Args:
        preheat_enabled: Enable winter preheat
        summer_limit_enabled: Enable summer limit
        preheat_temp: Target temperature in °C (typically 14-22)
        airflow: Airflow in m³/h (131, 164, or 201)

    Returns:
        Complete packet bytes ready to send

    Raises:
        ValueError: If airflow is not 131, 164, or 201
    """
    if airflow not in AIRFLOW_BYTES:
        raise ValueError(f"Airflow must be {AIRFLOW_LOW}, {AIRFLOW_MEDIUM}, or {AIRFLOW_HIGH}")

    af_b1, af_b2 = AIRFLOW_BYTES[airflow]

    payload = bytes([
        0x1A,
        0x06,
        0x06,
        0x1A,
        0x02 if preheat_enabled else 0x00,
        0x02 if summer_limit_enabled else 0x00,
        preheat_temp,
        af_b1,
        af_b2,
    ])

    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


def parse_status(data: bytes) -> DeviceStatus | None:
    """Parse status notification packet (type 0x01).

    Args:
        data: Raw packet bytes from status notification (182 bytes)

    Returns:
        DeviceStatus object or None if packet is invalid
    """
    if len(data) < 61 or data[:2] != MAGIC or data[2] != 0x01:
        return None

    airflow_indicator = data[47]
    sensor_selector = data[34]
    sensor_name = SENSOR_NAMES.get(sensor_selector, f"Unknown ({sensor_selector})")

    # Configured volume from bytes 22-23 (little-endian uint16)
    configured_volume = None
    airflow_low = None
    airflow_medium = None
    airflow_high = None
    if len(data) >= 24:
        configured_volume = int.from_bytes(data[22:24], "little")
        if configured_volume > 0:
            # Calculate actual airflow values based on volume and ACH rates
            airflow_low = round(configured_volume * 0.36)
            airflow_medium = round(configured_volume * 0.45)
            airflow_high = round(configured_volume * 0.55)

    # Determine current airflow mode and value from indicator
    airflow_mode = "unknown"
    airflow = 0
    if airflow_indicator == 38:  # 0x26 = LOW
        airflow_mode = "low"
        airflow = airflow_low or AIRFLOW_LOW
    elif airflow_indicator == 104:  # 0x68 = MEDIUM
        airflow_mode = "medium"
        airflow = airflow_medium or AIRFLOW_MEDIUM
    elif airflow_indicator == 194:  # 0xC2 = HIGH
        airflow_mode = "high"
        airflow = airflow_high or AIRFLOW_HIGH

    # Humidity from byte 5 (divide by 2 for percentage)
    humidity_raw = data[5] if len(data) > 5 else 0
    humidity = humidity_raw / 2 if humidity_raw else None

    # Equipment life fields (little-endian uint16)
    filter_days = None
    operating_days = None
    if len(data) >= 30:
        filter_days = int.from_bytes(data[28:30], "little")
        operating_days = int.from_bytes(data[26:28], "little")

    return DeviceStatus(
        device_id=int.from_bytes(data[4:8], "little"),
        configured_volume=configured_volume,
        airflow=airflow,
        airflow_low=airflow_low,
        airflow_medium=airflow_medium,
        airflow_high=airflow_high,
        airflow_indicator=airflow_indicator,
        airflow_mode=airflow_mode,
        preheat_enabled=data[49] != 0x00,
        summer_limit_enabled=data[50] != 0x00,
        summer_limit_temp=data[38] if len(data) > 38 else None,
        preheat_temp=data[56],
        boost_active=data[44] == 0x01 if len(data) > 44 else False,
        sensor_selector=sensor_selector,
        sensor_name=sensor_name,
        temp_remote=data[8] if len(data) > 8 else None,
        temp_probe1=data[35] if len(data) > 35 else None,
        temp_probe2=data[42] if len(data) > 42 else None,
        humidity_remote=humidity,
        filter_days=filter_days,
        operating_days=operating_days,
    )


def parse_sensors(data: bytes) -> SensorData | None:
    """Parse sensor/measurement packet (type 0x03).

    Args:
        data: Raw packet bytes from sensor notification (182 bytes)

    Returns:
        SensorData object or None if packet is invalid
    """
    if len(data) < 14 or data[:2] != MAGIC or data[2] != 0x03:
        return None

    return SensorData(
        temp_probe1=data[6] if len(data) > 6 else None,
        temp_probe2=data[11] if len(data) > 11 else None,
        humidity_probe1=data[8] if len(data) > 8 else None,
        filter_percent=data[13] if len(data) > 13 else None,
    )


def is_visionair_device(address: str, name: str | None) -> bool:
    """Check if a BLE device is a VisionAir device.

    Args:
        address: BLE MAC address
        name: Device name (may be None)

    Returns:
        True if this appears to be a VisionAir device
    """
    if address.upper().startswith(VISIONAIR_MAC_PREFIX):
        return True
    if name and any(n in name.lower() for n in DEVICE_NAMES):
        return True
    return False
