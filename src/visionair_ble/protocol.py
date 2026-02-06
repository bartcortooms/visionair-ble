"""VisionAir BLE Protocol - Packet building and parsing.

This module contains the reverse-engineered protocol for communicating with
Ventilairsec VisionAir (Vision'R range) ventilation devices over Bluetooth Low Energy.

Supported devices:
- Purevent Vision'R (350 m³/h max)
- Urban Vision'R (201 m³/h max)
- Cube Vision'R

Protocol overview:
- All packets start with magic bytes 0xa5 0xb6
- Packet type in byte 2: 0x01=device_state, 0x03=probe_sensors, 0x10=request, 0x1a=settings, 0x23=ack
- Settings packets use XOR checksum (all bytes after magic, excluding final checksum byte)
- BLE uses Cypress PSoC demo profile UUIDs (vendor reused generic UUIDs)
- All devices advertise as "VisionAir" over BLE

Packet types:
- DEVICE_STATE (0x01): Device config, settings, and Remote sensor data
- PROBE_SENSORS (0x03): Current probe temperature and humidity readings
- SCHEDULE (0x02): Time slot configuration
- REQUEST (0x10): Commands sent to device
- SETTINGS (0x1a): Configuration changes
- SETTINGS_ACK (0x23): Acknowledgment of settings

Note: The DEVICE_STATE packet temperatures (bytes 8/35/42) are often stale.
Use PROBE_SENSORS packet or get_sensors() for accurate probe readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
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

    DEVICE_STATE = 0x01         # Device config + Remote sensor (182 bytes)
    SCHEDULE = 0x02             # Time slot schedule data
    PROBE_SENSORS = 0x03        # Probe sensor readings (182 bytes)
    REQUEST = 0x10              # Request command
    SETTINGS = 0x1A             # Settings command
    SETTINGS_ACK = 0x23         # Settings acknowledgment
    SCHEDULE_WRITE = 0x40       # Schedule config write (55 bytes) — experimental
    SCHEDULE_CONFIG = 0x46      # Schedule config response (182 bytes) — experimental
    SCHEDULE_QUERY = 0x47       # Schedule query — experimental
    HOLIDAY_STATUS = 0x50       # Holiday mode status


class RequestParam:
    """Request parameters (byte 5 in 0x10 request packets)."""

    DEVICE_STATE = 0x03         # Request device state + Remote sensor
    FULL_DATA = 0x06            # Request all data (DEVICE_STATE + SCHEDULE + PROBE_SENSORS)
    PROBE_SENSORS = 0x07        # Request probe sensor readings
    SENSOR_SELECT = 0x18        # Set sensor cycle
    BOOST = 0x19                # Activate BOOST
    HOLIDAY = 0x1A              # Set holiday days (byte 9 = days, 0=OFF)
    HOLIDAY_STATUS = 0x2C       # Query holiday mode status


class SettingsMode:
    """Settings mode (byte 7 in 0x1a settings packets)."""

    NORMAL = 0x00               # Normal airflow/preheat settings
    SUMMER_LIMIT = 0x02         # Summer limit temperature
    SPECIAL_MODE = 0x04         # Holiday/Night Vent/Fixed Air Flow
    SCHEDULE = 0x05             # Schedule on/off


class AirflowLevel(IntEnum):
    """Airflow mode identifiers.

    These are abstract identifiers for airflow modes, not actual m³/h values.
    The actual m³/h is calculated from configured_volume × ACH rate:
    - LOW: volume × 0.36
    - MEDIUM: volume × 0.45
    - HIGH: volume × 0.55
    """

    LOW = 1
    MEDIUM = 2
    HIGH = 3


# Backward compatibility aliases
AIRFLOW_LOW = AirflowLevel.LOW
AIRFLOW_MEDIUM = AirflowLevel.MEDIUM
AIRFLOW_HIGH = AirflowLevel.HIGH


class DeviceStateOffset:
    """Field offsets in device state packet (type 0x01, 182 bytes).

    This packet contains device configuration, settings, and Remote sensor data.
    Probe temperatures here (bytes 35, 42) are often stale - use PROBE_SENSORS packet.
    """

    TYPE = 2
    HUMIDITY = 4                # Humidity % from remote (1 byte)
    UNKNOWN_5_7 = 5             # Constant per device (3 bytes) - possibly device identifier
    UNKNOWN_8 = 8               # Always 18 in captures - NOT live temp (see TEMP_ACTIVE)
    CONFIGURED_VOLUME = 22      # 2 bytes, little-endian
    OPERATING_DAYS = 26         # 2 bytes, little-endian
    FILTER_DAYS = 28            # 2 bytes, little-endian
    TEMP_ACTIVE = 32            # Live temp for selected sensor (per SENSOR_SELECTOR)
    SENSOR_SELECTOR = 34        # Current sensor source (0/1/2)
    TEMP_PROBE1 = 35            # Outlet temp (may be stale)
    SUMMER_LIMIT_TEMP = 38
    TEMP_PROBE2 = 42            # Inlet temp (may be stale)
    HOLIDAY_DAYS = 43            # Holiday days remaining (0=OFF)
    BOOST_ACTIVE = 44
    AIRFLOW_INDICATOR = 47      # 38=low, 104=medium, 194=high
    PREHEAT_ENABLED = 49
    SUMMER_LIMIT_ENABLED = 50
    PREHEAT_TEMP = 56


class ProbeSensorOffset:
    """Field offsets in probe sensors packet (type 0x03)."""

    TYPE = 2
    TEMP_PROBE1 = 6             # Outlet temperature
    HUMIDITY_PROBE1 = 8         # Outlet humidity
    TEMP_PROBE2 = 11            # Inlet temperature
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

# Schedule slot mode byte <-> AirflowLevel
# These differ from settings airflow bytes (which use two-byte pairs).
# Schedule slots use a single byte per mode.
SCHEDULE_MODE_BYTES: dict[int, int] = {
    AirflowLevel.LOW: 0x28,
    AirflowLevel.MEDIUM: 0x32,
    # AirflowLevel.HIGH: unknown -- not captured yet
}

SCHEDULE_MODE_LOOKUP: dict[int, int] = {v: k for k, v in SCHEDULE_MODE_BYTES.items()}

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
    """Device state from DEVICE_STATE packet (type 0x01).

    Contains device configuration, settings, and Remote sensor readings.
    Probe temperatures here are often stale - use SensorData from PROBE_SENSORS packet.

    Fields with sensor metadata will be auto-discovered by the HA integration.
    """

    # Internal fields (no sensor metadata)
    device_id: int  # Bytes 5-7, constant per device (not a true ID, just a unique-ish value)
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
    holiday_days: int = field(default=0, metadata=sensor(
        "Holiday days remaining", unit="d", device_class="duration", enabled_default=False
    ))



@dataclass
class SensorData:
    """Probe sensor data from PROBE_SENSORS packet (type 0x03).

    Contains current/live temperature and humidity readings from probes.
    The DEVICE_STATE packet (0x01) temperatures are often stale.
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


@dataclass
class ScheduleSlot:
    """A single hourly schedule slot.

    Each slot defines the preheat temperature and airflow mode for one hour
    of the day (0-23). The hour is implied by position in the ScheduleConfig.slots list.

    The mode_byte field stores the raw protocol byte for round-trip fidelity:
    a schedule read from the device can be written back unchanged, even if it
    contains unrecognized mode bytes (e.g., the unknown HIGH value).
    """

    preheat_temp: int  # Preheat temperature in degrees C
    mode_byte: int     # Raw protocol mode byte (0x28=LOW, 0x32=MEDIUM)

    @property
    def airflow_mode(self) -> str:
        """Human-readable airflow mode, or 'unknown' if mode byte unrecognized."""
        level = SCHEDULE_MODE_LOOKUP.get(self.mode_byte)
        if level == AirflowLevel.LOW:
            return "low"
        elif level == AirflowLevel.MEDIUM:
            return "medium"
        elif level == AirflowLevel.HIGH:
            return "high"
        return "unknown"

    @classmethod
    def from_mode(cls, preheat_temp: int, airflow: int) -> "ScheduleSlot":
        """Create a slot from an AirflowLevel value.

        Only LOW and MEDIUM are supported (HIGH mode byte is unknown).

        Args:
            preheat_temp: Preheat temperature in degrees C
            airflow: AirflowLevel.LOW or AirflowLevel.MEDIUM

        Raises:
            ValueError: If airflow is HIGH (unknown byte) or invalid
        """
        if airflow not in SCHEDULE_MODE_BYTES:
            if airflow == AirflowLevel.HIGH:
                raise ValueError(
                    "HIGH airflow mode byte for schedule slots is unknown"
                )
            raise ValueError(f"Invalid airflow level: {airflow}")
        return cls(preheat_temp=preheat_temp, mode_byte=SCHEDULE_MODE_BYTES[airflow])


@dataclass
class ScheduleConfig:
    """Full 24-hour schedule configuration.

    Contains 24 hourly slots where index = hour (0-23).
    Each slot defines the preheat temperature and airflow mode for that hour.
    """

    slots: list[ScheduleSlot]  # Exactly 24 slots, index = hour (0-23)


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
    """Build a device state request packet.

    Requests DEVICE_STATE packet (type 0x01) with device config and Remote sensor.

    Returns:
        Complete packet bytes: a5b6100005030000000016
    """
    return build_request(RequestParam.DEVICE_STATE)


def build_sensor_request() -> bytes:
    """Build a probe sensors request packet.

    Requests PROBE_SENSORS packet (type 0x03) with current probe readings.

    Returns:
        Complete packet bytes: a5b6100605070000000014
    """
    return build_request(RequestParam.PROBE_SENSORS, extended=True)


def build_full_data_request() -> bytes:
    """Build a full data request packet.

    This triggers the device to send a sequence of responses:
    - SETTINGS_ACK (0x23)
    - DEVICE_STATE (0x01) - device config + Remote sensor
    - SCHEDULE (0x02) - time slot configuration
    - PROBE_SENSORS (0x03) - current probe readings

    This is the request pattern used by the VMI app for polling.

    Returns:
        Complete packet bytes: a5b6100605060000000015
    """
    return build_request(RequestParam.FULL_DATA, extended=True)


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
# Holiday mode: Fully decoded. Uses REQUEST param 0x1a with days in byte 9.
# Read back via DEVICE_STATE byte 43. The 0x50 response is constant/not useful.
#
# Night Ventilation / Fixed Air Flow: Protocol understanding is incomplete.
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


def build_holiday_command(days: int) -> bytes:
    """Build a Holiday mode command packet.

    Sets the number of holiday days. The device reflects this value in
    DEVICE_STATE byte 43. Send days=0 to disable holiday mode.

    Args:
        days: Number of holiday days (0=OFF, 1-255=active)

    Returns:
        Complete packet bytes

    Raises:
        ValueError: If days is not in range 0-255
    """
    if not 0 <= days <= 255:
        raise ValueError("days must be between 0 and 255")
    return build_request(RequestParam.HOLIDAY, value=days, extended=True)


def build_holiday_status_query() -> bytes:
    """Build query to get Holiday mode status via type 0x50 response.

    Note: The 0x50 response is constant and does not reflect holiday state.
    Use DEVICE_STATE byte 43 (holiday_days) for reliable holiday status.

    Returns:
        Complete packet bytes
    """
    return build_request(RequestParam.HOLIDAY_STATUS, extended=True)


def _raise_special_mode_unsupported(feature: str, *, _experimental: bool) -> None:
    _require_experimental(_experimental, feature)
    raise ExperimentalFeatureError(
        f"{feature} encoding is unknown. "
        "In legacy captures, byte 8 appeared to be a sequence counter and "
        "bytes 9-10 were mode-specific. This SETTINGS-based path (byte7=0x04) "
        "has not been observed in current captures. "
        "We cannot generate valid packets without the encoding algorithm."
    )


def build_night_ventilation_activate(
    preheat_enabled: bool = True, *, _experimental: bool = False
) -> bytes:
    """Build Night Ventilation mode activation command.

    ⚠️  EXPERIMENTAL: Encoding is unknown. Byte 8 is a sequence counter and
    bytes 9-10 are mode-specific.

    Args:
        preheat_enabled: Whether to enable preheat during the mode
        _experimental: Must be True to use this function

    Returns:
        Complete packet bytes

    Raises:
        ExperimentalFeatureError: If _experimental is not True
    """
    _raise_special_mode_unsupported("Night Ventilation mode", _experimental=_experimental)
    return b""


def build_fixed_airflow_activate(
    preheat_enabled: bool = True, *, _experimental: bool = False
) -> bytes:
    """Build Fixed Air Flow mode activation command.

    ⚠️  EXPERIMENTAL: Encoding is unknown. Byte 8 is a sequence counter and
    bytes 9-10 are mode-specific.

    Args:
        preheat_enabled: Whether to enable preheat during the mode
        _experimental: Must be True to use this function

    Returns:
        Complete packet bytes

    Raises:
        ExperimentalFeatureError: If _experimental is not True
    """
    _raise_special_mode_unsupported("Fixed Air Flow mode", _experimental=_experimental)
    return b""


def build_schedule_write(
    config: ScheduleConfig, *, _experimental: bool = False
) -> bytes:
    """Build a schedule config write packet (type 0x40).

    Constructs a 55-byte packet with 24 hourly time slots. Each slot is
    2 bytes: preheat temperature (degrees C) and mode byte.

    Args:
        config: ScheduleConfig with exactly 24 slots
        _experimental: Must be True to use this function

    Returns:
        55-byte packet: a5b6 40 06 31 00 [24x2-byte slots] [checksum]

    Raises:
        ExperimentalFeatureError: If _experimental is not True
        ValueError: If config does not have exactly 24 slots
    """
    _require_experimental(_experimental, "Schedule write")

    if len(config.slots) != 24:
        raise ValueError(
            f"Schedule must have exactly 24 slots, got {len(config.slots)}"
        )

    payload = bytearray([PacketType.SCHEDULE_WRITE, 0x06, 0x31, 0x00])

    for slot in config.slots:
        payload.append(slot.preheat_temp)
        payload.append(slot.mode_byte)

    checksum = calc_checksum(bytes(payload))
    return MAGIC + bytes(payload) + bytes([checksum])


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
    """Parse device state packet (type 0x01).

    Args:
        data: Raw packet bytes from DEVICE_STATE notification (182 bytes)

    Returns:
        DeviceStatus object or None if packet is invalid
    """
    if len(data) < 61 or data[:2] != MAGIC or data[DeviceStateOffset.TYPE] != PacketType.DEVICE_STATE:
        return None

    airflow_indicator = data[DeviceStateOffset.AIRFLOW_INDICATOR]
    sensor_selector = data[DeviceStateOffset.SENSOR_SELECTOR]
    sensor_name = SENSOR_NAMES.get(sensor_selector, f"Unknown ({sensor_selector})")

    # Configured volume from bytes 22-23 (little-endian uint16)
    configured_volume = None
    airflow_low = None
    airflow_medium = None
    airflow_high = None
    if len(data) >= DeviceStateOffset.CONFIGURED_VOLUME + 2:
        configured_volume = int.from_bytes(
            data[DeviceStateOffset.CONFIGURED_VOLUME:DeviceStateOffset.CONFIGURED_VOLUME + 2], "little"
        )
        if configured_volume > 0:
            # Calculate actual airflow values based on volume and ACH rates
            airflow_low = round(configured_volume * 0.36)
            airflow_medium = round(configured_volume * 0.45)
            airflow_high = round(configured_volume * 0.55)

    # Determine current airflow mode and value from indicator
    # airflow is 0 if configured_volume is unavailable (we can't calculate m³/h)
    airflow_mode = "unknown"
    airflow = 0
    if airflow_indicator == AirflowIndicator.LOW:
        airflow_mode = "low"
        airflow = airflow_low or 0
    elif airflow_indicator == AirflowIndicator.MEDIUM:
        airflow_mode = "medium"
        airflow = airflow_medium or 0
    elif airflow_indicator == AirflowIndicator.HIGH:
        airflow_mode = "high"
        airflow = airflow_high or 0

    # Humidity from remote
    humidity = data[DeviceStateOffset.HUMIDITY] if len(data) > DeviceStateOffset.HUMIDITY else None

    # Equipment life fields (little-endian uint16)
    filter_days = None
    operating_days = None
    if len(data) >= DeviceStateOffset.FILTER_DAYS + 2:
        filter_days = int.from_bytes(
            data[DeviceStateOffset.FILTER_DAYS:DeviceStateOffset.FILTER_DAYS + 2], "little"
        )
        operating_days = int.from_bytes(
            data[DeviceStateOffset.OPERATING_DAYS:DeviceStateOffset.OPERATING_DAYS + 2], "little"
        )

    return DeviceStatus(
        # Bytes 5-7 are constant per device, use as pseudo-identifier (3 bytes, LE)
        device_id=int.from_bytes(data[DeviceStateOffset.UNKNOWN_5_7:DeviceStateOffset.UNKNOWN_5_7 + 3], "little"),
        configured_volume=configured_volume,
        airflow=airflow,
        airflow_low=airflow_low,
        airflow_medium=airflow_medium,
        airflow_high=airflow_high,
        airflow_indicator=airflow_indicator,
        airflow_mode=airflow_mode,
        preheat_enabled=data[DeviceStateOffset.PREHEAT_ENABLED] != 0x00,
        summer_limit_enabled=data[DeviceStateOffset.SUMMER_LIMIT_ENABLED] != 0x00,
        summer_limit_temp=data[DeviceStateOffset.SUMMER_LIMIT_TEMP] if len(data) > DeviceStateOffset.SUMMER_LIMIT_TEMP else None,
        preheat_temp=data[DeviceStateOffset.PREHEAT_TEMP],
        holiday_days=data[DeviceStateOffset.HOLIDAY_DAYS] if len(data) > DeviceStateOffset.HOLIDAY_DAYS else 0,
        boost_active=data[DeviceStateOffset.BOOST_ACTIVE] == 0x01 if len(data) > DeviceStateOffset.BOOST_ACTIVE else False,
        sensor_selector=sensor_selector,
        sensor_name=sensor_name,
        # Use live temperature from byte 32 only when that sensor is selected.
        # DEVICE_STATE packet bytes 8/35/42 are stale - use get_sensors() for accurate readings.
        temp_remote=(
            data[DeviceStateOffset.TEMP_ACTIVE] if sensor_selector == 2 and len(data) > DeviceStateOffset.TEMP_ACTIVE
            else None
        ),
        temp_probe1=(
            data[DeviceStateOffset.TEMP_ACTIVE] if sensor_selector == 1 and len(data) > DeviceStateOffset.TEMP_ACTIVE
            else None
        ),
        temp_probe2=(
            data[DeviceStateOffset.TEMP_ACTIVE] if sensor_selector == 0 and len(data) > DeviceStateOffset.TEMP_ACTIVE
            else None
        ),
        humidity_remote=humidity,
        filter_days=filter_days,
        operating_days=operating_days,
    )


def parse_sensors(data: bytes) -> SensorData | None:
    """Parse probe sensors packet (type 0x03).

    Args:
        data: Raw packet bytes from PROBE_SENSORS notification (182 bytes)

    Returns:
        SensorData object or None if packet is invalid
    """
    if len(data) < 14 or data[:2] != MAGIC or data[ProbeSensorOffset.TYPE] != PacketType.PROBE_SENSORS:
        return None

    return SensorData(
        temp_probe1=data[ProbeSensorOffset.TEMP_PROBE1] if len(data) > ProbeSensorOffset.TEMP_PROBE1 else None,
        temp_probe2=data[ProbeSensorOffset.TEMP_PROBE2] if len(data) > ProbeSensorOffset.TEMP_PROBE2 else None,
        humidity_probe1=data[ProbeSensorOffset.HUMIDITY_PROBE1] if len(data) > ProbeSensorOffset.HUMIDITY_PROBE1 else None,
        filter_percent=data[ProbeSensorOffset.FILTER_PERCENT] if len(data) > ProbeSensorOffset.FILTER_PERCENT else None,
    )


def parse_schedule_config(data: bytes) -> ScheduleConfig | None:
    """Parse schedule config response packet (type 0x46).

    Args:
        data: Raw packet bytes from SCHEDULE_CONFIG notification (182 bytes,
              or 55+ bytes if zero-padding is stripped)

    Returns:
        ScheduleConfig with 24 slots, or None if packet is invalid
    """
    if len(data) < 55 or data[:2] != MAGIC or data[2] != PacketType.SCHEDULE_CONFIG:
        return None

    # Verify header bytes
    if data[3:6] != bytes([0x06, 0x31, 0x00]):
        return None

    slots = []
    for i in range(24):
        offset = 6 + (i * 2)
        slots.append(ScheduleSlot(preheat_temp=data[offset], mode_byte=data[offset + 1]))

    return ScheduleConfig(slots=slots)


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
