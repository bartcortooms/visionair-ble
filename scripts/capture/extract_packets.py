#!/usr/bin/env python3
"""
Extract VMI packets from btsnoop logs for analysis.

Outputs structured packet data for correlation with UI screenshots.
"""

import struct
import sys
import json
from pathlib import Path
from datetime import datetime


def parse_btsnoop(filepath: str) -> list:
    """Parse btsnoop file and return list of packet records."""
    with open(filepath, 'rb') as f:
        magic = f.read(8)
        if magic != b'btsnoop\x00':
            # Try btsnooz format (base64 or different header)
            f.seek(0)
            data = f.read()
            if b'btsnoop' in data:
                # Find btsnoop header in file
                idx = data.find(b'btsnoop\x00')
                if idx >= 0:
                    f.seek(idx)
                    magic = f.read(8)
                else:
                    print(f"Error: Not a btsnoop file", file=sys.stderr)
                    return []
            else:
                print(f"Error: Not a btsnoop file", file=sys.stderr)
                return []

        version, datalink = struct.unpack('>II', f.read(8))

        records = []
        while True:
            header = f.read(24)
            if len(header) < 24:
                break

            orig_len, incl_len, flags, drops, ts = struct.unpack('>IIIIQ', header)
            data = f.read(incl_len)
            if len(data) < incl_len:
                break

            records.append({
                'timestamp': ts,
                'direction': 'TX' if flags & 1 else 'RX',
                'data': data
            })

        return records


def find_vmi_packets(records: list) -> dict:
    """Find all VMI packets in the records.

    Returns dict with:
    - writes: list of command writes to 0x0013
    - notifies: list of notifications from 0x000e
    """
    # Concatenate all raw data
    all_data = b''.join(r['data'] for r in records)

    result = {
        'writes': [],      # Commands TO device (handle 0x0013)
        'notifies': [],    # Notifications FROM device (handle 0x000e)
        'raw_packets': []  # All a5b6 packets found
    }

    # Find all a5b6 markers
    pos = 0
    pkt_num = 0
    while True:
        idx = all_data.find(b'\xa5\xb6', pos)
        if idx == -1:
            break

        if idx + 3 > len(all_data):
            break

        msg_type = all_data[idx + 2]

        # Determine expected length
        if msg_type in (0x01, 0x02, 0x03, 0x23):  # Status, Schedule, History, Ack
            pkt_len = 182
        elif msg_type == 0x10:  # Query
            pkt_len = 11
        elif msg_type == 0x1a:  # Settings
            pkt_len = 12
        else:
            pkt_len = min(20, len(all_data) - idx)

        if idx + pkt_len <= len(all_data):
            pkt_data = all_data[idx:idx + pkt_len]
            pkt_num += 1

            pkt_info = {
                'num': pkt_num,
                'type': msg_type,
                'type_name': get_type_name(msg_type),
                'hex': pkt_data.hex(),
                'len': len(pkt_data)
            }

            result['raw_packets'].append(pkt_info)

            # Classify as write or notify based on type
            if msg_type in (0x10, 0x1a):  # Commands
                result['writes'].append(pkt_info)
            else:  # Notifications (0x01, 0x02, 0x03, 0x23)
                result['notifies'].append(pkt_info)

        pos = idx + 1

    return result


def get_type_name(msg_type: int) -> str:
    """Get human-readable name for message type."""
    names = {
        0x01: 'STATUS',
        0x02: 'SCHEDULE',
        0x03: 'HISTORY',
        0x10: 'QUERY',
        0x1a: 'SETTINGS',
        0x23: 'CONFIG_ACK',
    }
    return names.get(msg_type, f'UNKNOWN_{msg_type:02x}')


def decode_status_packet(hex_data: str) -> dict:
    """Decode a status packet (type 0x01) and return all relevant fields."""
    data = bytes.fromhex(hex_data)
    if len(data) < 62:
        return {'error': 'Packet too short'}

    airflow_map = {38: 131, 104: 164, 194: 201}

    return {
        'device_id': struct.unpack('<I', data[4:8])[0],
        # Known sensor fields
        'remote_temp': data[8],           # Remote Control temperature
        'remote_humidity_raw': data[5],   # Remote humidity (divide by 2)
        'remote_humidity': data[5] / 2,
        'probe1_temp': data[35],          # Probe 1 temperature
        'probe2_temp': data[42],          # Probe 2 temperature
        'sensor_selector': data[34],      # 0=Probe2, 1=Probe1, 2=Remote
        'active_temp': data[32],          # Temperature of selected sensor
        # Settings
        'airflow_indicator': data[47],
        'airflow_m3h': airflow_map.get(data[47], f'?{data[47]}'),
        'preheat_enabled': data[49] != 0,
        'preheat_temp': data[56],
        'summer_limit_enabled': data[50] != 0,
        # Potential humidity fields to investigate
        'byte60': data[60],               # Sometimes humidity related
        'byte60_div2': data[60] / 2,
        # Full byte dump for specific ranges
        'bytes_0_10': [data[i] for i in range(11)],
        'bytes_30_45': [data[i] for i in range(30, 46)],
        'bytes_55_65': [data[i] for i in range(55, min(66, len(data)))],
    }


def decode_history_packet(hex_data: str) -> dict:
    """Decode a history packet (type 0x03)."""
    data = bytes.fromhex(hex_data)
    if len(data) < 20:
        return {'error': 'Packet too short'}

    return {
        'byte6': data[6],
        'byte8': data[8],
        'byte13': data[13],  # Filter % ?
        # Look for filter days (331 = 0x014B), operating days (634 = 0x027A)
        'bytes_4_20': [data[i] for i in range(4, min(21, len(data)))],
        'bytes_4_20_hex': data[4:21].hex(),
        # Search for specific values
        'u16_offsets': {
            f'off{i}': struct.unpack('<H', data[i:i+2])[0]
            for i in range(4, min(len(data)-1, 80))
        }
    }


def decode_settings_packet(hex_data: str) -> dict:
    """Decode a settings packet (type 0x1a)."""
    data = bytes.fromhex(hex_data)
    if len(data) < 12:
        return {'error': 'Packet too short'}

    return {
        'preheat_enabled': data[6] == 0x02,
        'summer_enabled': data[7] == 0x02,
        'preheat_temp': data[8],
        'airflow_b1': data[9],
        'airflow_b2': data[10],
        'checksum': data[11],
    }


def print_summary(packets: dict, output_format: str = 'text'):
    """Print summary of extracted packets."""
    if output_format == 'json':
        print(json.dumps(packets, indent=2))
        return

    print(f"\n{'='*60}")
    print(f"VMI Packet Extraction Summary")
    print(f"{'='*60}")
    print(f"\nTotal packets found: {len(packets['raw_packets'])}")
    print(f"  Writes (commands):  {len(packets['writes'])}")
    print(f"  Notifies (data):    {len(packets['notifies'])}")

    # Count by type
    type_counts = {}
    for pkt in packets['raw_packets']:
        t = pkt['type_name']
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\nPacket types:")
    for t, count in sorted(type_counts.items()):
        print(f"  {t}: {count}")

    # Decode and show status packets
    status_pkts = [p for p in packets['notifies'] if p['type'] == 0x01]
    if status_pkts:
        print(f"\n{'='*60}")
        print(f"STATUS PACKETS ({len(status_pkts)} total)")
        print(f"{'='*60}")

        for i, pkt in enumerate(status_pkts[:5]):  # Show first 5
            decoded = decode_status_packet(pkt['hex'])
            print(f"\nStatus #{i+1}:")
            print(f"  Remote: {decoded['remote_temp']}°C, {decoded['remote_humidity']:.1f}% (raw={decoded['remote_humidity_raw']})")
            print(f"  Probe1: {decoded['probe1_temp']}°C")
            print(f"  Probe2: {decoded['probe2_temp']}°C")
            print(f"  Sensor selector: {decoded['sensor_selector']} ({['Probe2','Probe1','Remote'][decoded['sensor_selector']] if decoded['sensor_selector'] < 3 else '?'})")
            print(f"  Active temp: {decoded['active_temp']}°C")
            print(f"  Airflow: {decoded['airflow_m3h']} m³/h (indicator={decoded['airflow_indicator']})")
            print(f"  Preheat: {'ON' if decoded['preheat_enabled'] else 'OFF'} at {decoded['preheat_temp']}°C")
            print(f"  Summer: {'ON' if decoded['summer_limit_enabled'] else 'OFF'}")
            print(f"  Byte 60: {decoded['byte60']} (÷2 = {decoded['byte60_div2']:.1f})")
            print(f"  Bytes 30-45: {decoded['bytes_30_45']}")

    # Show write commands
    if packets['writes']:
        print(f"\n{'='*60}")
        print(f"COMMAND WRITES ({len(packets['writes'])} total)")
        print(f"{'='*60}")

        for pkt in packets['writes']:
            print(f"\n  {pkt['type_name']}: {pkt['hex']}")
            if pkt['type'] == 0x1a:
                decoded = decode_settings_packet(pkt['hex'])
                print(f"    Preheat: {'ON' if decoded['preheat_enabled'] else 'OFF'} at {decoded['preheat_temp']}°C")
                print(f"    Summer: {'ON' if decoded['summer_enabled'] else 'OFF'}")
                print(f"    Airflow: ({decoded['airflow_b1']}, {decoded['airflow_b2']})")

    # Show history packets
    history_pkts = [p for p in packets['notifies'] if p['type'] == 0x03]
    if history_pkts:
        print(f"\n{'='*60}")
        print(f"HISTORY PACKETS ({len(history_pkts)} total)")
        print(f"{'='*60}")

        for pkt in history_pkts[:2]:
            decoded = decode_history_packet(pkt['hex'])
            print(f"\n  Byte 6: {decoded['byte6']}")
            print(f"  Byte 8: {decoded['byte8']}")
            print(f"  Byte 13: {decoded['byte13']} (filter %?)")
            print(f"  Hex[4:21]: {decoded['bytes_4_20_hex']}")
            # Look for filter days (331) or operating days (634)
            for off, val in decoded['u16_offsets'].items():
                if val in (331, 634, 330, 332, 633, 635):  # Allow ±1
                    print(f"  ** Found {val} at {off} **")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract VMI packets from btsnoop log')
    parser.add_argument('btsnoop_file', help='Path to btsnoop log file')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--status-hex', action='store_true', help='Output all status packet hex')
    args = parser.parse_args()

    records = parse_btsnoop(args.btsnoop_file)
    if not records:
        print("No records found in file", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(records)} HCI records", file=sys.stderr)

    packets = find_vmi_packets(records)

    if args.status_hex:
        # Just output status packets as hex, one per line
        for pkt in packets['notifies']:
            if pkt['type'] == 0x01:
                print(pkt['hex'])
    elif args.json:
        print_summary(packets, 'json')
    else:
        print_summary(packets)


if __name__ == '__main__':
    main()
