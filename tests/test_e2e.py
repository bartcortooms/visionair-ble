#!/usr/bin/env python3
"""
End-to-end tests for VisionAir BLE device connections.

This test module validates real device communication. It requires an actual
VisionAir device to be powered on and in range (direct or via proxy).

These tests are SKIPPED by default. To run them:

    # Run e2e tests (auto-scan for device)
    pytest -m e2e -v

    # Specify device address
    pytest -m e2e -v --device-address 00:A0:50:XX:XX:XX

    # Use ESPHome proxy
    pytest -m e2e -v --proxy-host 192.168.1.100 --proxy-key YOUR_KEY

    # Run directly (not via pytest)
    python tests/test_e2e.py [device_address]

    # Run directly with proxy (uses env vars)
    PROXY_HOST=192.168.1.100 PROXY_KEY=xxx python tests/test_e2e.py

Note: These tests are read-only and do not modify device settings.
"""

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest

from visionair_ble import VisionAirClient
from visionair_ble.connect import connect_direct, scan_direct
from visionair_ble.protocol import DeviceStatus, SensorData


# Test utilities
async def find_device(address: str | None = None, scan_timeout: float = 10.0) -> str:
    """Find a VisionAir device by address or scanning."""
    if address:
        print(f"Using provided device address: {address}")
        return address

    print(f"Scanning for VisionAir devices ({scan_timeout}s)...")
    devices = await scan_direct(timeout=scan_timeout)

    if not devices:
        raise RuntimeError(
            "No VisionAir devices found. "
            "Ensure device is powered on and in BLE range, or provide --device-address"
        )

    address, name = devices[0]
    print(f"Found device: {name} ({address})")
    return address


@asynccontextmanager
async def connect(
    address: str,
    proxy_host: str | None = None,
    proxy_key: str | None = None,
) -> AsyncIterator:
    """Connect to device directly or via proxy."""
    if proxy_host and proxy_key:
        from visionair_ble.connect import connect_via_proxy

        print(f"Connecting via proxy {proxy_host}...")
        async with connect_via_proxy(
            proxy_host, proxy_key, device_address=address
        ) as client:
            yield client
    else:
        print(f"Connecting directly to {address}...")
        async with connect_direct(address, timeout=20.0) as client:
            yield client


# E2E Tests - require real device, skipped by default
# Run with: pytest -m e2e
@pytest.mark.e2e
class TestDeviceConnection:
    """Test basic device connectivity."""

    @pytest.mark.asyncio
    async def test_can_connect(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test that we can establish a BLE connection to the device."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            assert client.is_connected
            print(f"Successfully connected to {address}")


@pytest.mark.e2e
class TestStatusRetrieval:
    """Test device status retrieval."""

    @pytest.mark.asyncio
    async def test_get_status_returns_valid_data(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test that get_status returns a properly populated DeviceStatus."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            status = await visionair.get_status(timeout=10.0)

            # Verify we got a DeviceStatus object
            assert isinstance(status, DeviceStatus)

            # Verify required fields are populated
            assert status.device_id > 0, "Device ID should be positive"
            assert status.airflow >= 0, "Airflow should be non-negative"
            assert status.airflow_mode in (
                "low",
                "medium",
                "high",
                "unknown",
            ), f"Unexpected airflow mode: {status.airflow_mode}"

            # Verify configured volume (if set)
            if status.configured_volume is not None:
                assert (
                    50 <= status.configured_volume <= 2000
                ), f"Unusual configured volume: {status.configured_volume}"

            # Verify temperature readings are reasonable (if present)
            for temp in [status.temp_remote, status.temp_probe1, status.temp_probe2]:
                if temp is not None:
                    assert (
                        -20 <= temp <= 50
                    ), f"Temperature out of expected range: {temp}C"

            # Verify humidity readings are reasonable (if present)
            if status.humidity_remote is not None:
                assert (
                    0 <= status.humidity_remote <= 100
                ), f"Humidity out of range: {status.humidity_remote}%"

            print(f"Status retrieved successfully:")
            print(f"  Device ID: {status.device_id}")
            print(f"  Airflow: {status.airflow} m3/h ({status.airflow_mode})")
            print(f"  Configured volume: {status.configured_volume} m3")
            print(f"  Preheat: {status.preheat_enabled} ({status.preheat_temp}C)")
            print(f"  Summer limit: {status.summer_limit_enabled} (threshold: {status.summer_limit_temp}C)")
            print(f"  Boost active: {status.boost_active}")

    @pytest.mark.asyncio
    async def test_get_status_cached_property(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test that last_status is updated after get_status."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)

            # Initially should be None
            assert visionair.last_status is None

            status = await visionair.get_status()
            assert visionair.last_status is status
            print("last_status property works correctly")


@pytest.mark.e2e
class TestSensorRetrieval:
    """Test live sensor data retrieval."""

    @pytest.mark.asyncio
    async def test_get_sensors_returns_valid_data(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test that get_sensors returns properly populated SensorData."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            sensors = await visionair.get_sensors(timeout=10.0)

            # Verify we got a SensorData object
            assert isinstance(sensors, SensorData)

            # Verify temperatures if present
            for temp in [sensors.temp_probe1, sensors.temp_probe2]:
                if temp is not None:
                    assert (
                        -20 <= temp <= 50
                    ), f"Temperature out of expected range: {temp}C"

            # Verify humidity if present
            if sensors.humidity_probe1 is not None:
                assert (
                    0 <= sensors.humidity_probe1 <= 100
                ), f"Humidity out of range: {sensors.humidity_probe1}%"

            # Verify filter percentage if present
            if sensors.filter_percent is not None:
                assert (
                    0 <= sensors.filter_percent <= 100
                ), f"Filter percent out of range: {sensors.filter_percent}%"

            print(f"Sensors retrieved successfully:")
            print(f"  Probe 1 temp: {sensors.temp_probe1}°C")
            print(f"  Probe 2 temp: {sensors.temp_probe2}°C")
            print(f"  Probe 1 humidity: {sensors.humidity_probe1}%")
            print(f"  Filter percentage: {sensors.filter_percent}%")


@pytest.mark.e2e
class TestFreshStatus:
    """Test fresh status retrieval with sensor cycling."""

    @pytest.mark.asyncio
    async def test_get_fresh_status(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test that get_fresh_status returns accurate readings for all sensors."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            status = await visionair.get_fresh_status(timeout=15.0)

            # Verify we got a DeviceStatus object
            assert isinstance(status, DeviceStatus)

            # Verify temperatures are populated (fresh readings)
            assert status.temp_probe1 is not None, "Probe 1 temp should be populated"
            assert status.temp_probe2 is not None, "Probe 2 temp should be populated"
            assert status.temp_remote is not None, "Remote temp should be populated"

            # Verify remote humidity (fresh reading)
            assert status.humidity_remote is not None, "Remote humidity should be populated"

            # Verify reasonable ranges
            for temp in [status.temp_probe1, status.temp_probe2, status.temp_remote]:
                if temp is not None:
                    assert -20 <= temp <= 50, f"Temperature out of range: {temp}C"

            if status.humidity_remote is not None:
                assert 0 <= status.humidity_remote <= 100, f"Humidity out of range: {status.humidity_remote}%"

            print(f"Fresh status retrieved successfully:")
            print(f"  Remote: {status.temp_remote}°C, {status.humidity_remote}%")
            print(f"  Probe 1: {status.temp_probe1}°C")
            print(f"  Probe 2: {status.temp_probe2}°C")
            print(f"  Airflow: {status.airflow} m³/h ({status.airflow_mode})")


@pytest.mark.e2e
class TestFreshStatusReliability:
    """Test that get_fresh_status reliably returns all sensor readings.

    This catches intermittent failures where stale BLE notifications
    cause sensor_select responses to be misattributed, resulting in
    None values for temp_remote or humidity_probe1.
    """

    ITERATIONS = 5

    @pytest.mark.asyncio
    async def test_fresh_status_all_sensors_repeated(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Call get_fresh_status multiple times; every iteration must return all sensors."""
        address = await find_device(device_address)
        failures: list[str] = []
        connection_retries = 2

        for i in range(1, self.ITERATIONS + 1):
            # Brief pause between iterations to let the proxy recover
            if i > 1:
                await asyncio.sleep(2)

            # Retry connection failures (proxy can be flaky between runs)
            for attempt in range(connection_retries + 1):
                try:
                    async with connect(address, proxy_host, proxy_key) as client:
                        visionair = VisionAirClient(client)
                        status = await visionair.get_fresh_status()

                        missing = []
                        if status.temp_remote is None:
                            missing.append("temp_remote")
                        if status.temp_probe1 is None:
                            missing.append("temp_probe1")
                        if status.temp_probe2 is None:
                            missing.append("temp_probe2")
                        if status.humidity_remote is None:
                            missing.append("humidity_remote")
                        if status.humidity_probe1 is None:
                            missing.append("humidity_probe1")

                        if missing:
                            msg = f"Run {i}: missing {', '.join(missing)}"
                            failures.append(msg)
                            print(f"  FAIL {msg}")
                        else:
                            print(
                                f"  Run {i}: OK "
                                f"(remote={status.temp_remote}°C/{status.humidity_remote}%, "
                                f"p1={status.temp_probe1}°C/{status.humidity_probe1}%, "
                                f"p2={status.temp_probe2}°C)"
                            )
                    break  # Connection succeeded, move to next iteration
                except ConnectionError:
                    if attempt < connection_retries:
                        print(f"  Run {i}: connection failed, retrying...")
                        await asyncio.sleep(5)
                    else:
                        print(f"  Run {i}: connection failed after {connection_retries + 1} attempts")
                        raise

        assert not failures, (
            f"{len(failures)}/{self.ITERATIONS} iterations had missing sensors:\n"
            + "\n".join(f"  {f}" for f in failures)
        )


@pytest.mark.e2e
class TestHolidayMode:
    """Test holiday mode set/clear via real device.

    WARNING: These tests MODIFY device settings. Holiday mode is activated
    briefly and then cleared. The cleanup always runs, even on test failure.
    """

    @pytest.mark.asyncio
    async def test_set_and_clear_holiday(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test setting holiday days and reading back from DeviceStatus.holiday_days."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)

            try:
                # Set holiday to 3 days
                status = await visionair.set_holiday(3)
                assert isinstance(status, DeviceStatus)
                assert status.holiday_days == 3, (
                    f"Expected holiday_days=3, got {status.holiday_days}"
                )
                print(f"  set_holiday(3): holiday_days={status.holiday_days}")

                # Clear holiday
                status = await visionair.clear_holiday()
                assert isinstance(status, DeviceStatus)
                assert status.holiday_days == 0, (
                    f"Expected holiday_days=0 after clear, got {status.holiday_days}"
                )
                print(f"  clear_holiday(): holiday_days={status.holiday_days}")
            finally:
                # Always clean up — ensure holiday is off
                try:
                    await visionair.clear_holiday()
                except Exception:
                    pass


@pytest.mark.e2e
class TestScheduleRead:
    """Test schedule reading from real device (read-only).

    Sends a Schedule Config Request (param 0x27) and parses the
    SCHEDULE_CONFIG (0x46) response.
    """

    @pytest.mark.asyncio
    async def test_get_schedule(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test reading schedule config from device."""
        from visionair_ble.protocol import ScheduleConfig

        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            config = await visionair.get_schedule(timeout=15.0)

            assert isinstance(config, ScheduleConfig)
            assert len(config.slots) == 24

            for i, slot in enumerate(config.slots):
                print(f"  Hour {i:2d}: {slot.preheat_temp}C {slot.airflow_mode} (0x{slot.mode_byte:02x})")
                assert 0 <= slot.preheat_temp <= 40


@pytest.mark.e2e
class TestScheduleWrite:
    """Test schedule write/read round-trip via real device.

    WARNING: These tests MODIFY device settings. The original schedule is
    always restored in a finally block, even on test failure.
    """

    @pytest.mark.asyncio
    async def test_write_schedule_roundtrip(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test writing a schedule and reading it back unchanged."""
        from visionair_ble.protocol import ScheduleConfig

        address = await find_device(device_address)

        # Read current schedule
        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            original = await visionair.get_schedule(timeout=15.0)
            assert isinstance(original, ScheduleConfig)
            assert len(original.slots) == 24

        # Write the same schedule back (reconnect — device may drop
        # the BLE connection after processing a schedule write)
        await asyncio.sleep(2)
        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            try:
                await visionair.set_schedule(original, timeout=15.0)
                print("  Wrote schedule back to device")
            except Exception:
                # Restore on failure
                await asyncio.sleep(2)
                async with connect(address, proxy_host, proxy_key) as c2:
                    await VisionAirClient(c2).set_schedule(original, timeout=15.0)
                raise

        # Read back and verify (fresh connection)
        await asyncio.sleep(2)
        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)
            readback = await visionair.get_schedule(timeout=15.0)
            assert isinstance(readback, ScheduleConfig)
            assert len(readback.slots) == 24

            for i, (orig, back) in enumerate(
                zip(original.slots, readback.slots, strict=True)
            ):
                assert orig.preheat_temp == back.preheat_temp, (
                    f"Hour {i}: preheat_temp {orig.preheat_temp} != {back.preheat_temp}"
                )
                assert orig.mode_byte == back.mode_byte, (
                    f"Hour {i}: mode_byte 0x{orig.mode_byte:02x} != 0x{back.mode_byte:02x}"
                )

            print("  Round-trip verified: all 24 slots match")


@pytest.mark.e2e
class TestMultipleOperations:
    """Test multiple operations in sequence."""

    @pytest.mark.asyncio
    async def test_status_and_sensors_sequence(
        self, device_address: str | None, proxy_host: str | None, proxy_key: str | None
    ) -> None:
        """Test that we can retrieve both status and sensors in one session."""
        address = await find_device(device_address)

        async with connect(address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)

            # Get status first
            status = await visionair.get_status()
            assert isinstance(status, DeviceStatus)

            # Then get sensors
            sensors = await visionair.get_sensors()
            assert isinstance(sensors, SensorData)

            # Verify status is still cached
            assert visionair.last_status is status

            print("Successfully retrieved status and sensors in sequence")
            print(f"  Airflow mode: {status.airflow_mode}")
            print(f"  Probe 1 temp: {sensors.temp_probe1}°C")
            print(f"  Filter: {sensors.filter_percent}%")


# Direct execution support
async def run_e2e_tests(
    address: str | None = None,
    proxy_host: str | None = None,
    proxy_key: str | None = None,
) -> bool:
    """Run E2E tests directly without pytest."""
    print("=" * 60)
    print("VisionAir BLE End-to-End Tests")
    print("=" * 60)
    print()

    if proxy_host and proxy_key:
        print(f"Mode: ESPHome proxy ({proxy_host})")
    else:
        print("Mode: Direct BLE")

    try:
        resolved_address = await find_device(address)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return False

    tests_passed = 0
    tests_failed = 0

    # Run tests
    try:
        async with connect(resolved_address, proxy_host, proxy_key) as client:
            visionair = VisionAirClient(client)

            print("\n--- Connection test ---")
            if client.is_connected:
                print("PASSED")
                tests_passed += 1
            else:
                print("FAILED: Not connected")
                tests_failed += 1

            print("\n--- Status retrieval ---")
            try:
                status = await visionair.get_status()
                print(f"  Device ID: {status.device_id}")
                print(f"  Airflow: {status.airflow} m3/h ({status.airflow_mode})")
                print(f"  Volume: {status.configured_volume} m3")
                print(
                    f"  Temps: remote={status.temp_remote}C, "
                    f"p1={status.temp_probe1}C, p2={status.temp_probe2}C"
                )
                print(f"  Humidity: {status.humidity_remote}%")
                print(
                    f"  Preheat: {'ON' if status.preheat_enabled else 'OFF'} "
                    f"({status.preheat_temp}C)"
                )
                print(f"  Summer limit: {'ON' if status.summer_limit_enabled else 'OFF'} (threshold: {status.summer_limit_temp}C)")
                print(f"  Boost: {'ON' if status.boost_active else 'OFF'}")
                print(f"  Filter days: {status.filter_days}")
                print("PASSED")
                tests_passed += 1
            except Exception as e:
                print(f"FAILED: {e}")
                tests_failed += 1

            print("\n--- Sensor retrieval ---")
            try:
                sensors = await visionair.get_sensors()
                print(f"  Probe 1 temp: {sensors.temp_probe1}°C")
                print(f"  Probe 2 temp: {sensors.temp_probe2}°C")
                print(f"  Probe 1 humidity: {sensors.humidity_probe1}%")
                print(f"  Filter percent: {sensors.filter_percent}%")
                print("PASSED")
                tests_passed += 1
            except Exception as e:
                print(f"FAILED: {e}")
                tests_failed += 1

            print("\n--- Fresh status (sensor cycling) ---")
            try:
                fresh = await visionair.get_fresh_status()
                print(f"  Remote: {fresh.temp_remote}°C, {fresh.humidity_remote}%")
                print(f"  Probe 1: {fresh.temp_probe1}°C")
                print(f"  Probe 2: {fresh.temp_probe2}°C")
                print(f"  Airflow: {fresh.airflow} m3/h ({fresh.airflow_mode})")
                print("PASSED")
                tests_passed += 1
            except Exception as e:
                print(f"FAILED: {e}")
                tests_failed += 1

            print("\n--- last_status cache ---")
            try:
                assert visionair.last_status is not None
                print("PASSED")
                tests_passed += 1
            except AssertionError as e:
                print(f"FAILED: {e}")
                tests_failed += 1

    except Exception as e:
        print(f"\nConnection failed: {e}")
        tests_failed += 1

    # Summary
    print()
    print("=" * 60)
    print(f"Results: {tests_passed} passed, {tests_failed} failed")
    print("=" * 60)

    return tests_failed == 0


def load_dotenv():
    """Load .env file if it exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


if __name__ == "__main__":
    # Load .env file if present
    load_dotenv()

    # Get settings from args or environment
    address = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEVICE_ADDRESS")
    proxy_host = os.environ.get("PROXY_HOST")
    proxy_key = os.environ.get("PROXY_KEY")

    success = asyncio.run(run_e2e_tests(address, proxy_host, proxy_key))
    sys.exit(0 if success else 1)
