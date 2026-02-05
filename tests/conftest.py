"""Pytest configuration for VisionAir BLE tests."""

import os
from pathlib import Path

import pytest


def _load_dotenv() -> None:
    """Load .env file if it exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


# Load .env at import time
_load_dotenv()


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
    """Fixture providing the device address from CLI, env, or None for auto-scan."""
    return request.config.getoption("--device-address") or os.environ.get("DEVICE_ADDRESS")


@pytest.fixture
def proxy_host(request: pytest.FixtureRequest) -> str | None:
    """Fixture providing the proxy host from CLI or env."""
    return request.config.getoption("--proxy-host") or os.environ.get("PROXY_HOST")


@pytest.fixture
def proxy_key(request: pytest.FixtureRequest) -> str | None:
    """Fixture providing the proxy API key from CLI or env."""
    return request.config.getoption("--proxy-key") or os.environ.get("PROXY_KEY")
