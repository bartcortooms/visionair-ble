"""Pytest configuration for VisionAir BLE tests."""

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command-line options for E2E tests."""
    parser.addoption(
        "--device-address",
        action="store",
        default=None,
        help="BLE address of VisionAir device for E2E tests (e.g., 00:A0:50:XX:XX:XX)",
    )
    parser.addoption(
        "--proxy-host",
        action="store",
        default=None,
        help="ESPHome proxy hostname/IP for remote BLE connections",
    )
    parser.addoption(
        "--proxy-key",
        action="store",
        default=None,
        help="ESPHome proxy API key (noise_psk)",
    )


@pytest.fixture
def device_address(request: pytest.FixtureRequest) -> str | None:
    """Fixture providing the device address from CLI or None for auto-scan."""
    return request.config.getoption("--device-address")


@pytest.fixture
def proxy_host(request: pytest.FixtureRequest) -> str | None:
    """Fixture providing the proxy host from CLI."""
    return request.config.getoption("--proxy-host")


@pytest.fixture
def proxy_key(request: pytest.FixtureRequest) -> str | None:
    """Fixture providing the proxy API key from CLI."""
    return request.config.getoption("--proxy-key")
