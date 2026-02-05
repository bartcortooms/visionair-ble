"""Tests for protocol encoding and decoding."""

import pytest

from visionair_ble.protocol import (
    AIRFLOW_HIGH,
    AIRFLOW_LOW,
    AIRFLOW_MEDIUM,
    ExperimentalFeatureError,
    build_boost_command,
    build_fixed_airflow_activate,
    build_holiday_activate,
    build_holiday_days_query,
    build_holiday_status_query,
    build_night_ventilation_activate,
    build_settings_packet,
    build_status_request,
    _build_special_mode_command,
    calc_checksum,
    is_visionair_device,
    parse_status,
    verify_checksum,
)


class TestChecksum:
    """Tests for checksum calculation."""

    def test_calc_checksum_simple(self):
        """Test XOR checksum calculation."""
        # 0x10 ^ 0x00 ^ 0x05 ^ 0x03 = 0x16
        assert calc_checksum(bytes([0x10, 0x00, 0x05, 0x03, 0x00, 0x00, 0x00, 0x00])) == 0x16

    def test_verify_checksum_valid(self):
        """Test checksum verification with valid packet."""
        packet = bytes.fromhex("a5b6100005030000000016")
        assert verify_checksum(packet)

    def test_verify_checksum_invalid(self):
        """Test checksum verification with invalid packet."""
        packet = bytes.fromhex("a5b61000050300000000ff")  # wrong checksum
        assert not verify_checksum(packet)


class TestPacketBuilding:
    """Tests for packet building functions."""

    def test_build_status_request(self):
        """Test status request packet."""
        packet = build_status_request()
        assert packet == bytes.fromhex("a5b6100005030000000016")
        assert verify_checksum(packet)

    def test_build_boost_on(self):
        """Test BOOST ON command."""
        packet = build_boost_command(True)
        assert packet == bytes.fromhex("a5b610060519000000010b")
        assert verify_checksum(packet)

    def test_build_boost_off(self):
        """Test BOOST OFF command."""
        packet = build_boost_command(False)
        assert packet == bytes.fromhex("a5b610060519000000000a")
        assert verify_checksum(packet)

    def test_build_settings_low(self):
        """Test settings packet for LOW airflow."""
        packet = build_settings_packet(
            preheat_enabled=True,
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_LOW,
        )
        assert packet == bytes.fromhex("a5b61a06061a020210190a03")
        assert verify_checksum(packet)

    def test_build_settings_medium(self):
        """Test settings packet for MEDIUM airflow."""
        packet = build_settings_packet(
            preheat_enabled=True,
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_MEDIUM,
        )
        # Verify structure: magic + type + header + flags + temp + airflow bytes + checksum
        assert packet[:2] == b"\xa5\xb6"  # magic
        assert packet[2] == 0x1a  # type
        assert packet[9] == 0x28  # airflow byte 1 for MEDIUM
        assert packet[10] == 0x15  # airflow byte 2 for MEDIUM
        assert verify_checksum(packet)

    def test_build_settings_high(self):
        """Test settings packet for HIGH airflow."""
        packet = build_settings_packet(
            preheat_enabled=True,
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_HIGH,
        )
        assert packet == bytes.fromhex("a5b61a06061a020210073027")
        assert verify_checksum(packet)

    def test_build_settings_invalid_airflow(self):
        """Test settings packet with invalid airflow raises."""
        with pytest.raises(ValueError, match="Airflow must be"):
            build_settings_packet(True, True, 16, 150)

    def test_build_settings_preheat_disabled(self):
        """Test settings packet with preheat disabled."""
        packet = build_settings_packet(
            preheat_enabled=False,
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_MEDIUM,
        )
        # Byte 6 should be 0x00 for preheat disabled
        assert packet[6] == 0x00
        assert verify_checksum(packet)


class TestStatusParsing:
    """Tests for status packet parsing."""

    def test_parse_status_valid(self):
        """Test parsing a valid status packet."""
        # Minimal valid status packet (62 bytes minimum)
        packet = bytearray(70)
        packet[0:2] = b"\xa5\xb6"  # magic
        packet[2] = 0x01  # type
        packet[4:8] = (12345678).to_bytes(4, "little")  # device ID
        packet[5] = 104  # humidity raw (52%)
        packet[8] = 18  # remote temp
        packet[22:24] = (363).to_bytes(2, "little")  # configured volume
        packet[26:28] = (634).to_bytes(2, "little")  # operating days
        packet[28:30] = (331).to_bytes(2, "little")  # filter days
        packet[34] = 2  # sensor selector (remote)
        packet[35] = 16  # probe 1 temp
        packet[38] = 26  # summer limit temp
        packet[42] = 11  # probe 2 temp
        packet[44] = 0  # boost off
        packet[47] = 104  # airflow indicator (MEDIUM = 0x68)
        packet[49] = 0x02  # preheat on
        packet[50] = 0x02  # summer limit on
        packet[56] = 16  # preheat temp

        status = parse_status(bytes(packet))

        assert status is not None
        assert status.configured_volume == 363
        assert status.airflow_mode == "medium"
        assert status.airflow_low == 131  # 363 * 0.36 = 130.68 -> 131
        assert status.airflow_medium == 163  # 363 * 0.45 = 163.35 -> 163
        assert status.airflow_high == 200  # 363 * 0.55 = 199.65 -> 200
        assert status.airflow == 163  # MEDIUM = airflow_medium
        assert status.temp_remote == 18
        assert status.temp_probe1 == 16
        assert status.temp_probe2 == 11
        assert status.humidity_remote == 52.0
        assert status.filter_days == 331
        assert status.operating_days == 634
        assert status.preheat_enabled is True
        assert status.summer_limit_enabled is True
        assert status.summer_limit_temp == 26
        assert status.preheat_temp == 16
        assert status.boost_active is False
        assert status.sensor_name == "Remote Control"

    def test_parse_status_airflow_modes(self):
        """Test parsing airflow modes from indicator bytes."""
        base_packet = bytearray(70)
        base_packet[0:2] = b"\xa5\xb6"
        base_packet[2] = 0x01
        base_packet[22:24] = (400).to_bytes(2, "little")  # 400 m³ volume

        # LOW mode (indicator 38 = 0x26)
        packet = base_packet.copy()
        packet[47] = 38
        status = parse_status(bytes(packet))
        assert status.airflow_mode == "low"
        assert status.airflow == status.airflow_low

        # MEDIUM mode (indicator 104 = 0x68)
        packet = base_packet.copy()
        packet[47] = 104
        status = parse_status(bytes(packet))
        assert status.airflow_mode == "medium"
        assert status.airflow == status.airflow_medium

        # HIGH mode (indicator 194 = 0xC2)
        packet = base_packet.copy()
        packet[47] = 194
        status = parse_status(bytes(packet))
        assert status.airflow_mode == "high"
        assert status.airflow == status.airflow_high

        # Unknown indicator
        packet = base_packet.copy()
        packet[47] = 99  # Unknown value
        status = parse_status(bytes(packet))
        assert status.airflow_mode == "unknown"
        assert status.airflow == 0

    def test_parse_status_invalid_magic(self):
        """Test parsing fails with wrong magic bytes."""
        packet = bytes([0x00, 0x00, 0x01] + [0] * 60)
        assert parse_status(packet) is None

    def test_parse_status_wrong_type(self):
        """Test parsing fails with wrong message type."""
        packet = bytes([0xa5, 0xb6, 0x02] + [0] * 60)
        assert parse_status(packet) is None

    def test_parse_status_too_short(self):
        """Test parsing fails with packet too short."""
        packet = bytes([0xa5, 0xb6, 0x01] + [0] * 10)
        assert parse_status(packet) is None


class TestDeviceIdentification:
    """Tests for device identification."""

    def test_is_visionair_by_mac(self):
        """Test identification by MAC prefix."""
        assert is_visionair_device("00:A0:50:AB:CD:EF", None)
        assert is_visionair_device("00:a0:50:12:34:56", None)
        assert not is_visionair_device("AA:BB:CC:DD:EE:FF", None)

    def test_is_visionair_by_name(self):
        """Test identification by device name."""
        assert is_visionair_device("AA:BB:CC:DD:EE:FF", "VisionAir")
        assert is_visionair_device("AA:BB:CC:DD:EE:FF", "Purevent Device")
        assert is_visionair_device("AA:BB:CC:DD:EE:FF", "Urban Vision'R")
        assert is_visionair_device("AA:BB:CC:DD:EE:FF", "Cube")
        assert not is_visionair_device("AA:BB:CC:DD:EE:FF", "Other Device")
        assert not is_visionair_device("AA:BB:CC:DD:EE:FF", None)


class TestSpecialModes:
    """Tests for Holiday, Night Ventilation, and Fixed Air Flow modes.

    These are experimental features that require _experimental=True flag.
    """

    # --- Experimental flag requirement tests ---

    def test_holiday_days_query_requires_experimental_flag(self):
        """Test that Holiday days query raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_holiday_days_query(7)

    def test_holiday_activate_requires_experimental_flag(self):
        """Test that Holiday activate raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_holiday_activate(7)

    def test_night_ventilation_requires_experimental_flag(self):
        """Test that Night Ventilation raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_night_ventilation_activate()

    def test_fixed_airflow_requires_experimental_flag(self):
        """Test that Fixed Air Flow raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_fixed_airflow_activate()

    # --- Packet structure tests (with experimental flag) ---

    def test_build_holiday_days_query_7_days(self):
        """Test Holiday days query for 7 days."""
        packet = build_holiday_days_query(7, _experimental=True)
        assert packet == bytes.fromhex("a5b61006051a000000070e")
        assert verify_checksum(packet)

    def test_build_holiday_days_query_14_days(self):
        """Test Holiday days query for 14 days."""
        packet = build_holiday_days_query(14, _experimental=True)
        assert packet == bytes.fromhex("a5b61006051a0000000e07")
        assert verify_checksum(packet)

    def test_build_holiday_days_query_3_days(self):
        """Test Holiday days query for 3 days."""
        packet = build_holiday_days_query(3, _experimental=True)
        assert packet == bytes.fromhex("a5b61006051a000000030a")
        assert verify_checksum(packet)

    def test_build_holiday_status_query(self):
        """Test Holiday status query packet (no experimental flag needed)."""
        packet = build_holiday_status_query()
        assert packet == bytes.fromhex("a5b61006052c000000003f")
        assert verify_checksum(packet)

    def test_build_special_mode_command_structure(self):
        """Test special mode command has correct structure."""
        packet = _build_special_mode_command(preheat_enabled=True)

        assert packet[:2] == b"\xa5\xb6"  # magic
        assert packet[2] == 0x1A  # type
        assert packet[3:6] == bytes([0x06, 0x06, 0x1A])  # header
        assert packet[6] == 0x02  # preheat enabled
        assert packet[7] == 0x04  # special mode flag
        # bytes 8-10 are HH:MM:SS (time-dependent)
        assert 0 <= packet[8] <= 23  # valid hour
        assert 0 <= packet[9] <= 59  # valid minute
        assert 0 <= packet[10] <= 59  # valid second
        assert verify_checksum(packet)

    def test_build_special_mode_preheat_disabled(self):
        """Test special mode with preheat disabled."""
        packet = _build_special_mode_command(preheat_enabled=False)
        assert packet[6] == 0x00  # preheat disabled
        assert packet[7] == 0x04  # special mode flag still set
        assert verify_checksum(packet)

    def test_build_holiday_activate_returns_sequence(self):
        """Test Holiday activate returns correct packet sequence."""
        packets = build_holiday_activate(7, preheat_enabled=True, _experimental=True)

        assert len(packets) == 2
        # First packet is days query
        assert packets[0] == bytes.fromhex("a5b61006051a000000070e")
        # Second packet is special mode activation
        assert packets[1][7] == 0x04  # special mode flag
        assert verify_checksum(packets[0])
        assert verify_checksum(packets[1])

    def test_build_night_ventilation_activate(self):
        """Test Night Ventilation activation."""
        packet = build_night_ventilation_activate(preheat_enabled=True, _experimental=True)
        assert packet[7] == 0x04  # special mode flag
        assert verify_checksum(packet)

    def test_build_fixed_airflow_activate(self):
        """Test Fixed Air Flow activation."""
        packet = build_fixed_airflow_activate(preheat_enabled=False, _experimental=True)
        assert packet[6] == 0x00  # preheat disabled
        assert packet[7] == 0x04  # special mode flag
        assert verify_checksum(packet)
