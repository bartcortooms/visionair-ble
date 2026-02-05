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

# =============================================================================
# Protocol Constants
# =============================================================================

# Packet framing
MAGIC = b"\xa5\xb6"
PACKET_SIZE = 11  # Standard command packet size


class PacketType:
    """Packet types (byte 2 in all packets)."""

    STATUS_RESPONSE = 0x01      # Status notification (182 bytes)
    SCHEDULE_RESPONSE = 0x02    # Schedule data
    SENSOR_RESPONSE = 0x03      # Sensor/history data
    REQUEST = 0x10              # Request command
    SETTINGS = 0x1A             # Settings command
    SETTINGS_ACK = 0x23         # Settings acknowledgment
    SCHEDULE_CONFIG = 0x46      # Schedule configuration
    SCHEDULE_QUERY = 0x47       # Schedule query
    HOLIDAY_STATUS = 0x50       # Holiday mode status


class RequestParam:
    """Request parameters (byte 5 in 0x10 request packets)."""

    STATUS = 0x03               # Request status
    HISTORY = 0x07              # Request sensor history
    SENSOR_SELECT = 0x18        # Set sensor cycle
    BOOST = 0x19                # Activate BOOST
    HOLIDAY_DAYS = 0x1A         # Query holiday days remaining
    HOLIDAY_STATUS = 0x2C       # Query holiday mode status


class SettingsMode:
    """Settings mode (byte 7 in 0x1a settings packets)."""

    NORMAL = 0x00               # Normal airflow/preheat settings
    SUMMER_LIMIT = 0x02         # Summer limit temperature
    SPECIAL_MODE = 0x04         # Holiday/Night Vent/Fixed Air Flow
    SCHEDULE = 0x05             # Schedule on/off


class AirflowLevel:
    """Airflow mode protocol values.

    These are internal protocol identifiers, NOT actual m³/h values.
    The actual m³/h is calculated from configured_volume × ACH rate.
    """

    LOW = 131       # Protocol identifier for LOW mode
    MEDIUM = 164    # Protocol identifier for MEDIUM mode
    HIGH = 201      # Protocol identifier for HIGH mode


# Backward compatibility aliases
AIRFLOW_LOW = AirflowLevel.LOW
AIRFLOW_MEDIUM = AirflowLevel.MEDIUM
AIRFLOW_HIGH = AirflowLevel.HIGH


class StatusOffset:
    """Field offsets in status response packet (type 0x01, 182 bytes)."""

    TYPE = 2
    DEVICE_ID = 4               # 4 bytes, little-endian
    HUMIDITY_RAW = 5            # Humidity * 2 from remote
    TEMP_REMOTE = 8             # Room temperature (from remote)
    CONFIGURED_VOLUME = 22      # 2 bytes, little-endian
    OPERATING_DAYS = 26         # 2 bytes, little-endian
    FILTER_DAYS = 28            # 2 bytes, little-endian
    SENSOR_SELECTOR = 34        # Current sensor source (0/1/2)
    TEMP_PROBE1 = 35            # Outlet temp (may be stale)
    SUMMER_LIMIT_TEMP = 38
    TEMP_PROBE2 = 42            # Inlet temp (may be stale)
    BOOST_ACTIVE = 44
    AIRFLOW_INDICATOR = 47      # 38=low, 104=medium, 194=high
    PREHEAT_ENABLED = 49
    SUMMER_LIMIT_ENABLED = 50
    PREHEAT_TEMP = 56


class SensorOffset:
    """Field offsets in sensor response packet (type 0x03)."""

    TYPE = 2
    TEMP_PROBE1 = 6             # Outlet temperature (live)
    HUMIDITY_PROBE1 = 8         # Outlet humidity
    TEMP_PROBE2 = 11            # Inlet temperature (live)
    FILTER_PERCENT = 13         # Filter remaining %


class AirflowIndicator:
    """Airflow indicator values (status byte 47)."""

    LOW = 38      # 0x26
    MEDIUM = 104  # 0x68
    HIGH = 194    # 0xC2


# =============================================================================
# BLE Configuration
# =============================================================================

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

# =============================================================================
# Airflow Configuration
# =============================================================================

# Airflow mode -> (byte1, byte2) for settings packet
# These byte pairs are universal mode selectors - the device firmware
# applies the appropriate airflow based on its volume calibration.
# Hypothesis from PSoC analysis: these may represent PWM duty cycles.
AIRFLOW_BYTES: dict[int, tuple[int, int]] = {
    AirflowLevel.LOW: (0x19, 0x0A),     # LOW mode
    AirflowLevel.MEDIUM: (0x28, 0x15),  # MEDIUM mode
    AirflowLevel.HIGH: (0x07, 0x30),    # HIGH mode
}

# Status response byte 47 -> airflow mode protocol value
AIRFLOW_INDICATOR: dict[int, int] = {
    AirflowIndicator.LOW: AirflowLevel.LOW,
    AirflowIndicator.MEDIUM: AirflowLevel.MEDIUM,
    AirflowIndicator.HIGH: AirflowLevel.HIGH,
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
    humidity_probe1: int | None = field(default=None, metadata=sensor(
        "Outlet humidity", unit="%", device_class="humidity", precision=0
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


def build_request(param: int, value: int = 0, extended: bool = False) -> bytes:
    """Build a standard request packet (type 0x10).

    Args:
        param: Request parameter (from RequestParam class)
        value: Optional value byte (default 0)
        extended: If True, use extended format (0x06 at byte 3), else short format (0x00)

    Returns:
        Complete packet bytes with checksum
    """
    if extended:
        # Extended format: 10 06 05 param 00 00 00 value
        payload = bytes([
            PacketType.REQUEST,
            0x06,
            0x05,
            param,
            0x00,
            0x00,
            0x00,
            value,
        ])
    else:
        # Short format: 10 00 05 param 00 00 00 00
        payload = bytes([
            PacketType.REQUEST,
            0x00,
            0x05,
            param,
            0x00,
            0x00,
            0x00,
            0x00,
        ])
    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


def build_status_request() -> bytes:
    """Build a status request packet.

    Returns:
        Complete packet bytes: a5b6100005030000000016
    """
    return build_request(RequestParam.STATUS)


def build_sensor_request() -> bytes:
    """Build a sensor/measurement request packet.

    Returns:
        Complete packet bytes: a5b6100605070000000014
    """
    return build_request(RequestParam.HISTORY, extended=True)


def build_sensor_select_request(sensor: int) -> bytes:
    """Build a request to get fresh data for a specific sensor.

    The response will have byte 34 (sensor_selector) matching the requested
    sensor, and bytes 32/60 will contain fresh temperature/humidity.

    To get fresh readings for all sensors, call this with 0, 1, and 2.

    Args:
        sensor: Sensor to read:
            0 = Probe 2 (Air inlet)
            1 = Probe 1 (Resistor outlet)
            2 = Remote Control

    Returns:
        Complete packet bytes

    Raises:
        ValueError: If sensor is not 0, 1, or 2
    """
    if sensor not in (0, 1, 2):
        raise ValueError("sensor must be 0 (Probe2), 1 (Probe1), or 2 (Remote)")

    return build_request(RequestParam.SENSOR_SELECT, value=sensor, extended=True)


def build_boost_command(enable: bool) -> bytes:
    """Build a BOOST mode command packet.

    Args:
        enable: True to enable BOOST, False to disable

    Returns:
        Complete packet bytes
    """
    return build_request(RequestParam.BOOST, value=1 if enable else 0, extended=True)


# =============================================================================
# Special Modes (Holiday, Night Ventilation, Fixed Air Flow)
# =============================================================================
#
# ⚠️  EXPERIMENTAL - Protocol understanding is incomplete!
#
# What we know:
# - All special modes use Settings command with byte 7 = 0x04
# - Bytes 8-9-10 encode HH:MM:SS timestamp
# - Holiday mode: days are set via query 0x1a before activation
#
# What we DON'T know:
# - How the device distinguishes Holiday vs Night Vent vs Fixed Air Flow
# - How to deactivate special modes (no OFF packets captured)
# - Whether Night Vent and Fixed Air Flow require different preceding queries
#
# These functions require _experimental=True flag to acknowledge the risks.


class ExperimentalFeatureError(Exception):
    """Raised when experimental features are used without explicit opt-in."""

    pass


def _require_experimental(flag: bool, feature: str) -> None:
    """Raise if experimental flag is not set."""
    if not flag:
        raise ExperimentalFeatureError(
            f"{feature} is experimental and may not work correctly. "
            f"Pass _experimental=True to acknowledge the risks. "
            f"See docs/protocol.md for details on what is unknown."
        )


def build_holiday_days_query(days: int, *, _experimental: bool = False) -> bytes:
    """Build query to set Holiday mode duration.

    ⚠️  EXPERIMENTAL: Holiday mode activation sequence is not fully verified.
    We don't know how to deactivate Holiday mode once activated.

    This should be sent before build_holiday_activate() to set
    the number of days the device will run in Holiday mode.

    Args:
        days: Number of days (typically 1-30)
        _experimental: Must be True to use this function

    Returns:
        Complete packet bytes

    Raises:
        ExperimentalFeatureError: If _experimental is not True
    """
    _require_experimental(_experimental, "Holiday mode")
    return build_request(RequestParam.HOLIDAY_DAYS, value=days, extended=True)


def build_holiday_status_query() -> bytes:
    """Build query to get Holiday mode status.

    Returns type 0x50 response with current Holiday mode state.
    Note: Parsing of the 0x50 response is not yet implemented.

    Returns:
        Complete packet bytes
    """
    return build_request(RequestParam.HOLIDAY_STATUS, extended=True)


def _build_special_mode_command(preheat_enabled: bool = True) -> bytes:
    """Build a special mode activation command (internal use).

    This is the shared packet structure for Holiday, Night Ventilation,
    and Fixed Air Flow modes. The command includes the current time
    as HH:MM:SS timestamp in bytes 8-9-10.

    Args:
        preheat_enabled: Whether to enable preheat during the mode

    Returns:
        Complete packet bytes
    """
    now = datetime.now()
    payload = bytes([
        PacketType.SETTINGS,
        0x06,
        0x06,
        0x1A,
        0x02 if preheat_enabled else 0x00,  # byte 6: preheat
        SettingsMode.SPECIAL_MODE,           # byte 7: special mode flag
        now.hour,                            # byte 8: hour
        now.minute,                          # byte 9: minute
        now.second,                          # byte 10: second
    ])
    checksum = calc_checksum(payload)
    return MAGIC + payload + bytes([checksum])


def build_holiday_activate(
    days: int, preheat_enabled: bool = True, *, _experimental: bool = False
) -> list[bytes]:
    """Build complete Holiday mode activation sequence.

    ⚠️  EXPERIMENTAL: We don't know how to deactivate Holiday mode once activated.

    Returns a list of packets that should be sent in order:
    1. Days query to set duration
    2. Special mode command to activate

    Args:
        days: Number of days for Holiday mode (typically 1-30)
        preheat_enabled: Whether to enable preheat during Holiday
        _experimental: Must be True to use this function

    Returns:
        List of packet bytes to send in sequence

    Raises:
        ExperimentalFeatureError: If _experimental is not True
    """
    _require_experimental(_experimental, "Holiday mode")
    return [
        build_holiday_days_query(days, _experimental=True),
        _build_special_mode_command(preheat_enabled),
    ]


def build_night_ventilation_activate(
    preheat_enabled: bool = True, *, _experimental: bool = False
) -> bytes:
    """Build Night Ventilation mode activation command.

    ⚠️  EXPERIMENTAL: We don't know how the device distinguishes this from
    Holiday mode or Fixed Air Flow. The packet structure appears identical.
    We also don't know how to deactivate this mode.

    Args:
        preheat_enabled: Whether to enable preheat during the mode
        _experimental: Must be True to use this function

    Returns:
        Complete packet bytes

    Raises:
        ExperimentalFeatureError: If _experimental is not True
    """
    _require_experimental(_experimental, "Night Ventilation mode")
    return _build_special_mode_command(preheat_enabled)


def build_fixed_airflow_activate(
    preheat_enabled: bool = True, *, _experimental: bool = False
) -> bytes:
    """Build Fixed Air Flow mode activation command.

    ⚠️  EXPERIMENTAL: We don't know how the device distinguishes this from
    Holiday mode or Night Ventilation. The packet structure appears identical.
    We also don't know how to deactivate this mode.

    Args:
        preheat_enabled: Whether to enable preheat during the mode
        _experimental: Must be True to use this function

    Returns:
        Complete packet bytes

    Raises:
        ExperimentalFeatureError: If _experimental is not True
    """
    _require_experimental(_experimental, "Fixed Air Flow mode")
    return _build_special_mode_command(preheat_enabled)


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
        airflow: Airflow mode (AirflowLevel.LOW/MEDIUM/HIGH or 131/164/201)

    Returns:
        Complete packet bytes ready to send

    Raises:
        ValueError: If airflow is not a valid AirflowLevel
    """
    if airflow not in AIRFLOW_BYTES:
        raise ValueError(
            f"Airflow must be AirflowLevel.LOW ({AirflowLevel.LOW}), "
            f"AirflowLevel.MEDIUM ({AirflowLevel.MEDIUM}), or "
            f"AirflowLevel.HIGH ({AirflowLevel.HIGH})"
        )

    af_b1, af_b2 = AIRFLOW_BYTES[airflow]

    payload = bytes([
        PacketType.SETTINGS,
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
    if len(data) < 61 or data[:2] != MAGIC or data[StatusOffset.TYPE] != PacketType.STATUS_RESPONSE:
        return None

    airflow_indicator = data[StatusOffset.AIRFLOW_INDICATOR]
    sensor_selector = data[StatusOffset.SENSOR_SELECTOR]
    sensor_name = SENSOR_NAMES.get(sensor_selector, f"Unknown ({sensor_selector})")

    # Configured volume from bytes 22-23 (little-endian uint16)
    configured_volume = None
    airflow_low = None
    airflow_medium = None
    airflow_high = None
    if len(data) >= StatusOffset.CONFIGURED_VOLUME + 2:
        configured_volume = int.from_bytes(
            data[StatusOffset.CONFIGURED_VOLUME:StatusOffset.CONFIGURED_VOLUME + 2], "little"
        )
        if configured_volume > 0:
            # Calculate actual airflow values based on volume and ACH rates
            airflow_low = round(configured_volume * 0.36)
            airflow_medium = round(configured_volume * 0.45)
            airflow_high = round(configured_volume * 0.55)

    # Determine current airflow mode and value from indicator
    airflow_mode = "unknown"
    airflow = 0
    if airflow_indicator == AirflowIndicator.LOW:
        airflow_mode = "low"
        airflow = airflow_low or AirflowLevel.LOW
    elif airflow_indicator == AirflowIndicator.MEDIUM:
        airflow_mode = "medium"
        airflow = airflow_medium or AirflowLevel.MEDIUM
    elif airflow_indicator == AirflowIndicator.HIGH:
        airflow_mode = "high"
        airflow = airflow_high or AirflowLevel.HIGH

    # Humidity from byte 5 (divide by 2 for percentage)
    humidity_raw = data[StatusOffset.HUMIDITY_RAW] if len(data) > StatusOffset.HUMIDITY_RAW else 0
    humidity = humidity_raw / 2 if humidity_raw else None

    # Equipment life fields (little-endian uint16)
    filter_days = None
    operating_days = None
    if len(data) >= StatusOffset.FILTER_DAYS + 2:
        filter_days = int.from_bytes(
            data[StatusOffset.FILTER_DAYS:StatusOffset.FILTER_DAYS + 2], "little"
        )
        operating_days = int.from_bytes(
            data[StatusOffset.OPERATING_DAYS:StatusOffset.OPERATING_DAYS + 2], "little"
        )

    return DeviceStatus(
        device_id=int.from_bytes(data[StatusOffset.DEVICE_ID:StatusOffset.DEVICE_ID + 4], "little"),
        configured_volume=configured_volume,
        airflow=airflow,
        airflow_low=airflow_low,
        airflow_medium=airflow_medium,
        airflow_high=airflow_high,
        airflow_indicator=airflow_indicator,
        airflow_mode=airflow_mode,
        preheat_enabled=data[StatusOffset.PREHEAT_ENABLED] != 0x00,
        summer_limit_enabled=data[StatusOffset.SUMMER_LIMIT_ENABLED] != 0x00,
        summer_limit_temp=data[StatusOffset.SUMMER_LIMIT_TEMP] if len(data) > StatusOffset.SUMMER_LIMIT_TEMP else None,
        preheat_temp=data[StatusOffset.PREHEAT_TEMP],
        boost_active=data[StatusOffset.BOOST_ACTIVE] == 0x01 if len(data) > StatusOffset.BOOST_ACTIVE else False,
        sensor_selector=sensor_selector,
        sensor_name=sensor_name,
        temp_remote=data[StatusOffset.TEMP_REMOTE] if len(data) > StatusOffset.TEMP_REMOTE else None,
        temp_probe1=data[StatusOffset.TEMP_PROBE1] if len(data) > StatusOffset.TEMP_PROBE1 else None,
        temp_probe2=data[StatusOffset.TEMP_PROBE2] if len(data) > StatusOffset.TEMP_PROBE2 else None,
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
    if len(data) < 14 or data[:2] != MAGIC or data[SensorOffset.TYPE] != PacketType.SENSOR_RESPONSE:
        return None

    return SensorData(
        temp_probe1=data[SensorOffset.TEMP_PROBE1] if len(data) > SensorOffset.TEMP_PROBE1 else None,
        temp_probe2=data[SensorOffset.TEMP_PROBE2] if len(data) > SensorOffset.TEMP_PROBE2 else None,
        humidity_probe1=data[SensorOffset.HUMIDITY_PROBE1] if len(data) > SensorOffset.HUMIDITY_PROBE1 else None,
        filter_percent=data[SensorOffset.FILTER_PERCENT] if len(data) > SensorOffset.FILTER_PERCENT else None,
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
