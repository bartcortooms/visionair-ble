"""Tests for protocol encoding and decoding."""

import pytest

from visionair_ble.protocol import (
    AIRFLOW_HIGH,
    AIRFLOW_LOW,
    AIRFLOW_MEDIUM,
    MAGIC,
    SCHEDULE_MODE_BYTES,
    SCHEDULE_MODE_LOOKUP,
    AirflowLevel,
    ExperimentalFeatureError,
    PacketType,
    ScheduleConfig,
    ScheduleSlot,
    build_boost_command,
    build_fixed_airflow_activate,
    build_holiday_command,
    build_preheat_request,
    build_holiday_status_query,
    build_night_ventilation_activate,
    build_schedule_config_request,
    build_schedule_toggle,
    build_schedule_write,
    build_sensor_select_request,
    build_settings_packet,
    build_status_request,
    calc_checksum,
    is_visionair_device,
    parse_schedule_config,
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

    def test_build_sensor_select_low(self):
        """Test sensor select LOW/Probe2 (REQUEST 0x18 value=0)."""
        packet = build_sensor_select_request(AirflowLevel.LOW)
        assert packet == bytes.fromhex("a5b610060518000000000b")
        assert verify_checksum(packet)

    def test_build_sensor_select_medium(self):
        """Test airflow mode MEDIUM command (REQUEST 0x18 value=1)."""
        packet = build_sensor_select_request(AirflowLevel.MEDIUM)
        assert packet == bytes.fromhex("a5b610060518000000010a")
        assert verify_checksum(packet)

    def test_build_sensor_select_high(self):
        """Test airflow mode HIGH command (REQUEST 0x18 value=2)."""
        packet = build_sensor_select_request(AirflowLevel.HIGH)
        assert packet == bytes.fromhex("a5b6100605180000000209")
        assert verify_checksum(packet)

    def test_build_sensor_select_invalid(self):
        """Test airflow request with invalid mode raises."""
        with pytest.raises(ValueError, match="Mode must be"):
            build_sensor_select_request(99)

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

    def test_build_preheat_on(self):
        """Test preheat ON command (REQUEST param 0x2F, value 1)."""
        packet = build_preheat_request(True)
        assert packet == bytes.fromhex("a5b61006052f000000013d")
        assert verify_checksum(packet)

    def test_build_preheat_off(self):
        """Test preheat OFF command (REQUEST param 0x2F, value 0)."""
        packet = build_preheat_request(False)
        assert packet == bytes.fromhex("a5b61006052f000000003c")
        assert verify_checksum(packet)

    def test_build_settings_low(self):
        """Test settings packet for LOW airflow."""
        packet = build_settings_packet(
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_LOW,
        )
        assert packet == bytes.fromhex("a5b61a06061a020210190a03")
        assert verify_checksum(packet)

    def test_build_settings_medium(self):
        """Test settings packet for MEDIUM airflow."""
        packet = build_settings_packet(
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_MEDIUM,
        )
        # Verify structure: magic + type + header + flags + temp + airflow bytes + checksum
        assert packet[:2] == b"\xa5\xb6"  # magic
        assert packet[2] == 0x1a  # type
        assert packet[6] == 0x02  # byte 6 is always 0x02
        assert packet[9] == 0x28  # airflow byte 1 for MEDIUM
        assert packet[10] == 0x15  # airflow byte 2 for MEDIUM
        assert verify_checksum(packet)

    def test_build_settings_high(self):
        """Test settings packet for HIGH airflow."""
        packet = build_settings_packet(
            summer_limit_enabled=True,
            preheat_temp=16,
            airflow=AIRFLOW_HIGH,
        )
        assert packet == bytes.fromhex("a5b61a06061a020210073027")
        assert verify_checksum(packet)

    def test_build_settings_invalid_airflow(self):
        """Test settings packet with invalid airflow raises."""
        with pytest.raises(ValueError, match="Airflow must be"):
            build_settings_packet(True, 16, 150)

    def test_build_settings_summer_limit_disabled(self):
        """Test settings packet with summer limit disabled."""
        packet = build_settings_packet(
            summer_limit_enabled=False,
            preheat_temp=16,
            airflow=AIRFLOW_MEDIUM,
        )
        # Byte 6 is always 0x02, byte 7 should be 0x00 for summer limit disabled
        assert packet[6] == 0x02
        assert packet[7] == 0x00
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
        packet[8] = 17  # unknown constant
        packet[22:24] = (363).to_bytes(2, "little")  # configured volume
        packet[26:28] = (634).to_bytes(2, "little")  # operating days
        packet[28:30] = (331).to_bytes(2, "little")  # filter days
        packet[32] = 19  # active temp (depends on mode index)
        packet[34] = 2  # mode index (2 = HIGH)
        packet[35] = 16  # probe 1 temp
        packet[38] = 26  # summer limit temp
        packet[42] = 11  # probe 2 temp
        packet[44] = 0  # boost off
        packet[47] = 38  # airflow indicator (HIGH = 0x26)
        packet[50] = 0x02  # summer limit on
        packet[53] = 0x01  # preheat on
        packet[56] = 16  # preheat temp

        status = parse_status(bytes(packet))

        assert status is not None
        assert status.configured_volume == 363
        assert status.airflow_mode == "high"
        assert status.airflow_low == 131  # 363 * 0.36 = 130.68 -> 131
        assert status.airflow_medium == 163  # 363 * 0.45 = 163.35 -> 163
        assert status.airflow_high == 200  # 363 * 0.55 = 199.65 -> 200
        assert status.airflow == 200  # HIGH = airflow_high
        assert status.temp_remote == 19
        # Probe temps are None when sensor_selector != their index
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
        """Test parsing airflow modes from indicator bytes.

        Indicator values verified via capture (airflow_indicator_byte47_20260207):
        0x68 (104) = LOW, 0xc2 (194) = MEDIUM, 0x26 (38) = HIGH
        """
        base_packet = bytearray(70)
        base_packet[0:2] = b"\xa5\xb6"
        base_packet[2] = 0x01
        base_packet[22:24] = (400).to_bytes(2, "little")  # 400 m³ volume

        # LOW mode (indicator 0x68 = 104)
        packet = base_packet.copy()
        packet[47] = 104
        status = parse_status(bytes(packet))
        assert status.airflow_mode == "low"
        assert status.airflow == status.airflow_low

        # MEDIUM mode (indicator 0xc2 = 194)
        packet = base_packet.copy()
        packet[47] = 194
        status = parse_status(bytes(packet))
        assert status.airflow_mode == "medium"
        assert status.airflow == status.airflow_medium

        # HIGH mode (indicator 0x26 = 38)
        packet = base_packet.copy()
        packet[47] = 38
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


class TestHolidayMode:
    """Tests for Holiday mode command and status parsing."""

    def test_build_holiday_command_3_days(self):
        """Test Holiday command for 3 days."""
        packet = build_holiday_command(3)
        assert packet == bytes.fromhex("a5b61006051a000000030a")
        assert verify_checksum(packet)

    def test_build_holiday_command_7_days(self):
        """Test Holiday command for 7 days."""
        packet = build_holiday_command(7)
        assert packet == bytes.fromhex("a5b61006051a000000070e")
        assert verify_checksum(packet)

    def test_build_holiday_command_off(self):
        """Test Holiday OFF command (days=0)."""
        packet = build_holiday_command(0)
        assert packet == bytes.fromhex("a5b61006051a0000000009")
        assert verify_checksum(packet)

    def test_build_holiday_command_invalid(self):
        """Test Holiday command rejects invalid days."""
        with pytest.raises(ValueError, match="days must be between 0 and 255"):
            build_holiday_command(-1)
        with pytest.raises(ValueError, match="days must be between 0 and 255"):
            build_holiday_command(256)

    def test_parse_status_holiday_days(self):
        """Test parsing holiday_days from byte 43 of DEVICE_STATE."""
        packet = bytearray(70)
        packet[0:2] = b"\xa5\xb6"
        packet[2] = 0x01
        packet[22:24] = (363).to_bytes(2, "little")
        packet[47] = 104  # MEDIUM airflow

        # Holiday inactive
        packet[43] = 0
        status = parse_status(bytes(packet))
        assert status is not None
        assert status.holiday_days == 0

        # Holiday active (5 days)
        packet[43] = 5
        status = parse_status(bytes(packet))
        assert status is not None
        assert status.holiday_days == 5

    def test_build_holiday_status_query(self):
        """Test Holiday status query packet."""
        packet = build_holiday_status_query()
        assert packet == bytes.fromhex("a5b61006052c000000003f")
        assert verify_checksum(packet)


class TestSpecialModes:
    """Tests for Night Ventilation and Fixed Air Flow modes.

    These features have incomplete protocol understanding and always raise errors.
    """

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


class TestScheduleModeBytes:
    """Tests for schedule mode byte constants."""

    def test_mode_bytes_bidirectional(self):
        """SCHEDULE_MODE_BYTES and SCHEDULE_MODE_LOOKUP are inverses."""
        for airflow, mode_byte in SCHEDULE_MODE_BYTES.items():
            assert SCHEDULE_MODE_LOOKUP[mode_byte] == airflow

    def test_low_mode_byte(self):
        assert SCHEDULE_MODE_BYTES[AirflowLevel.LOW] == 0x28

    def test_medium_mode_byte(self):
        assert SCHEDULE_MODE_BYTES[AirflowLevel.MEDIUM] == 0x32

    def test_high_mode_byte(self):
        assert SCHEDULE_MODE_BYTES[AirflowLevel.HIGH] == 0x3C


class TestScheduleSlot:
    """Tests for ScheduleSlot creation and properties."""

    def test_from_mode_low(self):
        slot = ScheduleSlot.from_mode(16, AirflowLevel.LOW)
        assert slot.preheat_temp == 16
        assert slot.mode_byte == 0x28
        assert slot.airflow_mode == "low"

    def test_from_mode_medium(self):
        slot = ScheduleSlot.from_mode(18, AirflowLevel.MEDIUM)
        assert slot.preheat_temp == 18
        assert slot.mode_byte == 0x32
        assert slot.airflow_mode == "medium"

    def test_from_mode_high(self):
        slot = ScheduleSlot.from_mode(16, AirflowLevel.HIGH)
        assert slot.preheat_temp == 16
        assert slot.mode_byte == 0x3C
        assert slot.airflow_mode == "high"

    def test_from_mode_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid airflow level"):
            ScheduleSlot.from_mode(16, 99)

    def test_unknown_mode_byte(self):
        slot = ScheduleSlot(preheat_temp=16, mode_byte=0xFF)
        assert slot.airflow_mode == "unknown"
        assert slot.mode_byte == 0xFF

    def test_high_mode_byte(self):
        slot = ScheduleSlot(preheat_temp=16, mode_byte=0x3C)
        assert slot.airflow_mode == "high"

    def test_raw_construction(self):
        slot = ScheduleSlot(preheat_temp=20, mode_byte=0x28)
        assert slot.preheat_temp == 20
        assert slot.airflow_mode == "low"


class TestBuildScheduleWrite:
    """Tests for schedule write packet building."""

    def test_all_low(self):
        """Build schedule with all LOW slots at 16C."""
        config = ScheduleConfig(slots=[ScheduleSlot(16, 0x28)] * 24)
        packet = build_schedule_write(config)

        assert len(packet) == 55
        assert packet[:2] == MAGIC
        assert packet[2] == PacketType.SCHEDULE_WRITE
        assert packet[3:6] == bytes([0x06, 0x31, 0x00])
        # First slot: 16C (0x10), LOW (0x28)
        assert packet[6] == 0x10
        assert packet[7] == 0x28
        assert verify_checksum(packet)

    def test_mixed_modes(self):
        """Build schedule with mixed LOW and MEDIUM slots."""
        slots = [ScheduleSlot(16, 0x28)] * 24
        slots[1] = ScheduleSlot(16, 0x32)  # Hour 1: MEDIUM
        config = ScheduleConfig(slots=slots)
        packet = build_schedule_write(config)

        assert len(packet) == 55
        assert packet[6:8] == bytes([0x10, 0x28])  # Hour 0: LOW
        assert packet[8:10] == bytes([0x10, 0x32])  # Hour 1: MEDIUM
        assert verify_checksum(packet)

    def test_wrong_slot_count_too_few(self):
        config = ScheduleConfig(slots=[ScheduleSlot(16, 0x28)] * 12)
        with pytest.raises(ValueError, match="24 slots"):
            build_schedule_write(config)

    def test_wrong_slot_count_too_many(self):
        config = ScheduleConfig(slots=[ScheduleSlot(16, 0x28)] * 25)
        with pytest.raises(ValueError, match="24 slots"):
            build_schedule_write(config)

    def test_preserves_all_mode_bytes(self):
        """All mode bytes including unknown ones are written as-is for round-trip."""
        slots = [ScheduleSlot(16, 0x28)] * 24
        slots[5] = ScheduleSlot(16, 0x3C)  # HIGH
        slots[6] = ScheduleSlot(16, 0xFF)  # Unknown mode byte
        config = ScheduleConfig(slots=slots)
        packet = build_schedule_write(config)

        # Hour 5 at offset 6 + 5*2 = 16
        assert packet[16] == 0x10  # 16C
        assert packet[17] == 0x3C  # HIGH preserved
        # Hour 6 at offset 6 + 6*2 = 18
        assert packet[18] == 0x10  # 16C
        assert packet[19] == 0xFF  # Unknown preserved
        assert verify_checksum(packet)


class TestParseScheduleConfig:
    """Tests for schedule config response parsing."""

    def _make_packet(self, slots=None):
        """Build a valid 182-byte 0x46 packet."""
        packet = bytearray(182)
        packet[0:2] = MAGIC
        packet[2] = PacketType.SCHEDULE_CONFIG
        packet[3:6] = bytes([0x06, 0x31, 0x00])
        if slots is None:
            # Default: all LOW at 16C
            for i in range(24):
                packet[6 + i * 2] = 0x10
                packet[6 + i * 2 + 1] = 0x28
        else:
            for i, (temp, mode) in enumerate(slots):
                packet[6 + i * 2] = temp
                packet[6 + i * 2 + 1] = mode
        return bytes(packet)

    def test_parse_all_low(self):
        packet = self._make_packet()
        config = parse_schedule_config(packet)

        assert config is not None
        assert len(config.slots) == 24
        assert config.slots[0].preheat_temp == 16
        assert config.slots[0].mode_byte == 0x28
        assert config.slots[0].airflow_mode == "low"

    def test_parse_mixed_modes(self):
        slots = [(16, 0x28)] * 24
        slots[8] = (18, 0x32)  # Hour 8: MEDIUM at 18C
        packet = self._make_packet(slots)
        config = parse_schedule_config(packet)

        assert config.slots[8].preheat_temp == 18
        assert config.slots[8].mode_byte == 0x32
        assert config.slots[8].airflow_mode == "medium"
        # Other slots unchanged
        assert config.slots[0].airflow_mode == "low"

    def test_parse_high_mode_byte(self):
        slots = [(16, 0x28)] * 24
        slots[5] = (16, 0x3C)  # HIGH
        packet = self._make_packet(slots)
        config = parse_schedule_config(packet)

        assert config.slots[5].mode_byte == 0x3C
        assert config.slots[5].airflow_mode == "high"

    def test_parse_unknown_mode_byte(self):
        slots = [(16, 0x28)] * 24
        slots[5] = (16, 0xFF)  # Truly unknown mode
        packet = self._make_packet(slots)
        config = parse_schedule_config(packet)

        assert config.slots[5].mode_byte == 0xFF
        assert config.slots[5].airflow_mode == "unknown"

    def test_parse_invalid_magic(self):
        packet = bytes([0x00, 0x00, PacketType.SCHEDULE_CONFIG] + [0] * 179)
        assert parse_schedule_config(packet) is None

    def test_parse_wrong_type(self):
        packet = bytearray(182)
        packet[0:2] = MAGIC
        packet[2] = PacketType.DEVICE_STATE
        assert parse_schedule_config(bytes(packet)) is None

    def test_parse_wrong_header(self):
        packet = bytearray(182)
        packet[0:2] = MAGIC
        packet[2] = PacketType.SCHEDULE_CONFIG
        packet[3:6] = bytes([0x00, 0x00, 0x00])
        assert parse_schedule_config(bytes(packet)) is None

    def test_parse_too_short(self):
        packet = bytearray(10)
        packet[0:2] = MAGIC
        packet[2] = PacketType.SCHEDULE_CONFIG
        assert parse_schedule_config(bytes(packet)) is None


class TestScheduleRoundTrip:
    """Tests for schedule parse-build round-trip fidelity."""

    def test_round_trip_slot_data(self):
        """Build -> simulate 0x46 response -> parse -> build: slot data matches."""
        slots = [ScheduleSlot(16, 0x28)] * 24
        slots[3] = ScheduleSlot(18, 0x32)  # Hour 3: MEDIUM at 18C
        original = ScheduleConfig(slots=slots)

        packet = build_schedule_write(original)

        # Simulate device response: same slot data, different type byte, padded
        response = bytearray(182)
        response[0:2] = MAGIC
        response[2] = PacketType.SCHEDULE_CONFIG
        response[3:6] = packet[3:6]  # Header
        response[6:54] = packet[6:54]  # Slot data

        parsed = parse_schedule_config(bytes(response))
        assert parsed is not None

        rebuilt = build_schedule_write(parsed)
        # Slot data (bytes 6-53) should match exactly
        assert packet[6:54] == rebuilt[6:54]

    def test_round_trip_with_high_mode(self):
        """Round-trip preserves HIGH mode bytes."""
        slots = [ScheduleSlot(16, 0x28)] * 24
        slots[10] = ScheduleSlot(20, 0x3C)  # HIGH
        original = ScheduleConfig(slots=slots)

        packet = build_schedule_write(original)

        response = bytearray(182)
        response[0:2] = MAGIC
        response[2] = PacketType.SCHEDULE_CONFIG
        response[3:6] = packet[3:6]
        response[6:54] = packet[6:54]

        parsed = parse_schedule_config(bytes(response))
        assert parsed.slots[10].mode_byte == 0x3C
        assert parsed.slots[10].airflow_mode == "high"

        rebuilt = build_schedule_write(parsed)
        assert packet[6:54] == rebuilt[6:54]


class TestBuildScheduleConfigRequest:
    """Tests for schedule config request packet."""

    def test_produces_valid_packet(self):
        packet = build_schedule_config_request()
        assert packet[:2] == MAGIC
        assert packet[2] == 0x10  # REQUEST type
        assert packet[5] == 0x27  # RequestParam.SCHEDULE_CONFIG
        assert verify_checksum(packet)

    def test_length(self):
        packet = build_schedule_config_request()
        assert len(packet) == 11


class TestBuildScheduleToggle:
    """Tests for schedule toggle packet."""

    def test_enable(self):
        packet = build_schedule_toggle(True)
        assert packet[:2] == MAGIC
        assert packet[2] == 0x10  # REQUEST type
        assert packet[5] == 0x1D  # RequestParam.SCHEDULE_TOGGLE
        assert packet[9] == 1  # value=1 (ON)
        assert verify_checksum(packet)

    def test_disable(self):
        packet = build_schedule_toggle(False)
        assert packet[:2] == MAGIC
        assert packet[5] == 0x1D
        assert packet[9] == 0  # value=0 (OFF)
        assert verify_checksum(packet)


class TestScheduleCapturedData:
    """Tests against real BLE capture data from controlled VMI sessions."""

    # Run 4: Changed hour 0 from LOW to MEDIUM
    RUN4_WRITE = bytes.fromhex(
        "a5b64006310010321028102810281028102810281028102810321032"
        "103210321032103210321032103210281028102810281028102877"
    )

    # Run 5: Changed hour 0 from MEDIUM to HIGH
    RUN5_WRITE = bytes.fromhex(
        "a5b640063100103c1028102810281028102810281028102810321032"
        "103210321032103210321032103210281028102810281028102879"
    )

    # Run 6: Changed hour 0 preheat from 16°C to 18°C (mode still HIGH)
    RUN6_WRITE = bytes.fromhex(
        "a5b640063100123c102810281028102810281028102810281032"
        "10321032103210321032103210321032102810281028102810287b"
    )

    def test_run4_structure(self):
        """Run 4 packet has correct structure."""
        p = self.RUN4_WRITE
        assert p[:2] == MAGIC
        assert p[2] == PacketType.SCHEDULE_WRITE
        assert p[3:6] == bytes([0x06, 0x31, 0x00])
        assert len(p) == 55
        assert verify_checksum(p)

    def test_run4_hour0_medium(self):
        """Run 4: hour 0 changed to MEDIUM (0x32) at 16°C."""
        config = parse_schedule_config(self._to_response(self.RUN4_WRITE))
        assert config.slots[0].preheat_temp == 16
        assert config.slots[0].mode_byte == 0x32
        assert config.slots[0].airflow_mode == "medium"

    def test_run5_hour0_high(self):
        """Run 5: hour 0 changed to HIGH (0x3C) at 16°C."""
        config = parse_schedule_config(self._to_response(self.RUN5_WRITE))
        assert config.slots[0].preheat_temp == 16
        assert config.slots[0].mode_byte == 0x3C
        assert config.slots[0].airflow_mode == "high"

    def test_run6_preheat_18c(self):
        """Run 6: hour 0 preheat changed to 18°C, mode still HIGH."""
        config = parse_schedule_config(self._to_response(self.RUN6_WRITE))
        assert config.slots[0].preheat_temp == 18
        assert config.slots[0].mode_byte == 0x3C
        assert config.slots[0].airflow_mode == "high"

    def test_run4_rebuild_matches(self):
        """Rebuilding from parsed Run 4 data produces identical slot bytes."""
        config = parse_schedule_config(self._to_response(self.RUN4_WRITE))
        rebuilt = build_schedule_write(config)
        assert rebuilt[6:54] == self.RUN4_WRITE[6:54]

    def test_run5_rebuild_matches(self):
        """Rebuilding from parsed Run 5 data produces identical slot bytes."""
        config = parse_schedule_config(self._to_response(self.RUN5_WRITE))
        rebuilt = build_schedule_write(config)
        assert rebuilt[6:54] == self.RUN5_WRITE[6:54]

    def test_default_schedule_pattern(self):
        """All three captures share the same default schedule pattern.

        Hours 1-8: LOW (0x28) at 16°C
        Hours 9-17: MEDIUM (0x32) at 16°C
        Hours 18-23: LOW (0x28) at 16°C
        Hour 0: varies per run (the one we changed)
        """
        config = parse_schedule_config(self._to_response(self.RUN4_WRITE))
        # Hours 1-8 are LOW
        for h in range(1, 9):
            assert config.slots[h].mode_byte == 0x28, f"hour {h}"
            assert config.slots[h].preheat_temp == 16, f"hour {h}"
        # Hours 9-17 are MEDIUM
        for h in range(9, 18):
            assert config.slots[h].mode_byte == 0x32, f"hour {h}"
            assert config.slots[h].preheat_temp == 16, f"hour {h}"
        # Hours 18-23 are LOW
        for h in range(18, 24):
            assert config.slots[h].mode_byte == 0x28, f"hour {h}"
            assert config.slots[h].preheat_temp == 16, f"hour {h}"

    def _to_response(self, write_packet: bytes) -> bytes:
        """Convert a 0x40 write packet to a 0x46 response for parsing."""
        response = bytearray(182)
        response[0:2] = MAGIC
        response[2] = PacketType.SCHEDULE_CONFIG
        response[3:6] = write_packet[3:6]  # Header
        response[6:54] = write_packet[6:54]  # Slot data
        return bytes(response)
