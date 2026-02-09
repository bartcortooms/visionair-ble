import pytest

from visionair_ble.client import VisionAirClient
from visionair_ble.protocol import COMMAND_CHAR_UUID, STATUS_CHAR_UUID, MAGIC, PacketType


class _Char:
    def __init__(self, uuid: str):
        self.uuid = uuid


class _Service:
    def __init__(self, characteristics):
        self.characteristics = characteristics


class _FakeBleClient:
    def __init__(self, responses: list[bytes]):
        self.services = [_Service([_Char(STATUS_CHAR_UUID), _Char(COMMAND_CHAR_UUID)])]
        self.is_connected = True
        self._responses = responses
        self._handler = None

    async def start_notify(self, _char, handler):
        self._handler = handler

    async def stop_notify(self, _char):
        self._handler = None

    async def write_gatt_char(self, _char, _data, response=True):
        if self._handler and self._responses:
            pkt = self._responses.pop(0)
            self._handler(pkt)


def _packet(packet_type: int) -> bytearray:
    data = bytearray(182)
    data[0:2] = MAGIC
    data[2] = packet_type
    return data


@pytest.mark.asyncio
async def test_get_fresh_status_prefers_schedule_remote_humidity() -> None:
    """Regression test for issue #19.

    get_fresh_status should populate remote humidity from SCHEDULE byte 13
    rather than any stale DEVICE_STATE field.
    """
    schedule = _packet(PacketType.SCHEDULE)
    schedule[11] = 21  # remote temp
    schedule[13] = 52  # remote humidity

    status = _packet(PacketType.DEVICE_STATE)
    status[4] = 55  # legacy/stale candidate value; should NOT win
    status[11] = 200  # configured volume bytes for parse_status

    probes = _packet(PacketType.PROBE_SENSORS)
    probes[6] = 18
    probes[8] = 47
    probes[11] = 11

    fake = _FakeBleClient([bytes(schedule), bytes(status), bytes(probes)])
    client = VisionAirClient(fake)

    fresh = await client.get_fresh_status(timeout=0.2)

    assert fresh.temp_remote == 21
    assert fresh.humidity_remote == 52
