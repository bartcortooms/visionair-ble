"""Tests for protocol encoding and decoding."""

import pytest

from visionair_ble.protocol import (
    AIRFLOW_HIGH,
    AIRFLOW_LOW,
    AIRFLOW_MEDIUM,
    AirflowLevel,
    ExperimentalFeatureError,
    build_boost_command,
    build_fixed_airflow_activate,
    build_holiday_activate,
    build_holiday_status_query,
    build_night_ventilation_activate,
    build_request_1a,
    build_sensor_select_request,
    build_settings_packet,
    build_status_request,
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

    def test_build_sensor_select_probe2(self):
        """Test sensor select for Probe 2 (inlet)."""
        packet = build_sensor_select_request(0)
        assert packet == bytes.fromhex("a5b610060518000000000b")
        assert verify_checksum(packet)

    def test_build_sensor_select_probe1(self):
        """Test sensor select for Probe 1 (outlet)."""
        packet = build_sensor_select_request(1)
        assert packet == bytes.fromhex("a5b610060518000000010a")
        assert verify_checksum(packet)

    def test_build_sensor_select_remote(self):
        """Test sensor select for Remote Control."""
        packet = build_sensor_select_request(2)
        assert packet == bytes.fromhex("a5b6100605180000000209")
        assert verify_checksum(packet)

    def test_build_sensor_select_invalid(self):
        """Test sensor select with invalid sensor raises."""
        with pytest.raises(ValueError, match="sensor must be"):
            build_sensor_select_request(3)

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
        packet[4] = 52  # humidity (direct %)
        packet[5:8] = (12345678).to_bytes(4, "little")[:3]  # device ID (partial)
        packet[8] = 17  # remote temp (cached, may be stale)
        packet[22:24] = (363).to_bytes(2, "little")  # configured volume
        packet[26:28] = (634).to_bytes(2, "little")  # operating days
        packet[28:30] = (331).to_bytes(2, "little")  # filter days
        packet[32] = 18  # active temp (live value for selected sensor)
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
        # Probe temps are None when sensor_selector != their sensor
        assert status.temp_probe1 is None
        assert status.temp_probe2 is None
        assert status.humidity_remote == 52
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

    These features have incomplete protocol understanding and always raise errors.
    """

    def test_request_1a_requires_experimental_flag(self):
        """Test that Request 0x1a raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_request_1a()

    def test_request_1a_with_experimental_flag(self):
        """Test Request 0x1a packet with experimental flag."""
        packet = build_request_1a(_experimental=True)
        assert packet == bytes.fromhex("a5b61006051a0000000009")
        assert verify_checksum(packet)

    def test_holiday_activate_requires_experimental_flag(self):
        """Test that Holiday activate raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_holiday_activate(7)

    def test_holiday_activate_unsupported(self):
        """Test that Holiday activate is unsupported even with experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="encoding is unknown"):
            build_holiday_activate(7, _experimental=True)

    def test_night_ventilation_requires_experimental_flag(self):
        """Test that Night Ventilation raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_night_ventilation_activate()

    def test_night_ventilation_unsupported(self):
        """Test that Night Ventilation is unsupported even with experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="encoding is unknown"):
            build_night_ventilation_activate(_experimental=True)

    def test_fixed_airflow_requires_experimental_flag(self):
        """Test that Fixed Air Flow raises without experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="experimental"):
            build_fixed_airflow_activate()

    def test_fixed_airflow_unsupported(self):
        """Test that Fixed Air Flow is unsupported even with experimental flag."""
        with pytest.raises(ExperimentalFeatureError, match="encoding is unknown"):
            build_fixed_airflow_activate(_experimental=True)

    def test_build_holiday_status_query(self):
        """Test Holiday status query packet (no experimental flag needed)."""
        packet = build_holiday_status_query()
        assert packet == bytes.fromhex("a5b61006052c000000003f")
        assert verify_checksum(packet)
