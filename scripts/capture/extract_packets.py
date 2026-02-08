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
    """Find all VMI packets in the records with timestamps.

    Returns dict with:
    - writes: list of command writes to 0x0013
    - notifies: list of notifications from 0x000e
    - raw_packets: all a5b6 packets found
    """
    result = {
        'writes': [],
        'notifies': [],
        'raw_packets': []
    }

    # Build index: for each byte position in concatenated data, track which record it came from
    byte_to_record = []
    all_data_parts = []
    for rec_idx, rec in enumerate(records):
        for _ in rec['data']:
            byte_to_record.append(rec_idx)
        all_data_parts.append(rec['data'])

    all_data = b''.join(all_data_parts)

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
        if msg_type in (0x01, 0x02, 0x03, 0x23, 0x46, 0x47, 0x50):  # 182-byte notifications
            pkt_len = 182
        elif msg_type == 0x10:  # Query
            pkt_len = 11
        elif msg_type == 0x1a:  # Settings
            pkt_len = 12
        elif msg_type == 0x40:  # Schedule Config Write
            pkt_len = 55
        else:
            pkt_len = min(20, len(all_data) - idx)

        if idx + pkt_len <= len(all_data):
            pkt_data = all_data[idx:idx + pkt_len]
            pkt_num += 1

            # Get timestamp from the record this packet started in
            rec_idx = byte_to_record[idx] if idx < len(byte_to_record) else 0
            # btsnoop timestamp: microseconds since 0000-01-01, convert to datetime
            ts_raw = records[rec_idx]['timestamp']
            # btsnoop epoch is 0000-01-01, offset to unix epoch
            ts_unix = (ts_raw - 0x00dcddb30f2f8000) / 1000000.0
            try:
                ts_dt = datetime.fromtimestamp(ts_unix)
                ts_iso = ts_dt.isoformat()
            except (ValueError, OSError):
                ts_iso = f"raw:{ts_raw}"

            pkt_info = {
                'num': pkt_num,
                'type': msg_type,
                'type_name': get_type_name(msg_type),
                'hex': pkt_data.hex(),
                'len': len(pkt_data),
                'timestamp': ts_iso,
                'timestamp_raw': ts_raw,
            }

            result['raw_packets'].append(pkt_info)

            # Classify as write or notify based on type
            if msg_type in (0x10, 0x1a, 0x40):  # Commands
                result['writes'].append(pkt_info)
            else:  # Notifications (0x01, 0x02, 0x03, 0x23, 0x46, 0x47, 0x50)
                result['notifies'].append(pkt_info)

        pos = idx + 1

    return result


def parse_checkpoints(filepath: str) -> list:
    """Parse checkpoints.txt file into list of checkpoint dicts."""
    checkpoints = []
    current = None

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('[checkpoint_'):
                if current:
                    checkpoints.append(current)
                current = {'id': line[1:-1]}
            elif '=' in line and current is not None:
                key, val = line.split('=', 1)
                current[key] = val

    if current:
        checkpoints.append(current)

    return checkpoints


def find_packets_near_checkpoint(packets: list, checkpoint_ts: str, window_seconds: int = 10) -> list:
    """Find packets within window_seconds of a checkpoint timestamp."""
    try:
        # Parse ISO timestamp
        cp_dt = datetime.fromisoformat(checkpoint_ts)
        if cp_dt.tzinfo is not None:
            cp_dt = cp_dt.replace(tzinfo=None)
    except ValueError:
        return []

    matching = []
    for pkt in packets:
        try:
            pkt_dt = datetime.fromisoformat(pkt['timestamp'])
            if pkt_dt.tzinfo is not None:
                pkt_dt = pkt_dt.replace(tzinfo=None)
            diff = abs((pkt_dt - cp_dt).total_seconds())
            if diff <= window_seconds:
                matching.append((pkt, diff))
        except (ValueError, KeyError):
            continue

    # Sort by time difference (closest first)
    matching.sort(key=lambda x: x[1])
    return [m[0] for m in matching]


def get_type_name(msg_type: int) -> str:
    """Get human-readable name for message type."""
    names = {
        0x01: 'DEVICE_STATE',
        0x02: 'SCHEDULE',
        0x03: 'PROBE_SENSORS',
        0x10: 'REQUEST',
        0x1a: 'SETTINGS',
        0x23: 'SETTINGS_ACK',
        0x40: 'SCHEDULE_WRITE',
        0x46: 'SCHEDULE_CONFIG',
        0x47: 'SCHEDULE_QUERY',
        0x50: 'UNKNOWN_50',
    }
    return names.get(msg_type, f'UNKNOWN_{msg_type:02x}')


def decode_device_state_packet(hex_data: str) -> dict:
    """Decode a device state packet (type 0x01) and return all relevant fields."""
    data = bytes.fromhex(hex_data)
    if len(data) < 62:
        return {'error': 'Packet too short'}

    airflow_map = {38: 131, 104: 164, 194: 201}

    return {
        'device_id': int.from_bytes(data[5:8], 'little'),  # Bytes 5-7, constant per device
        # Known sensor fields
        'mode_selector': data[34],        # 0=LOW, 1=MEDIUM, 2=HIGH
        'unknown_32': data[32],           # Changes with mode (0x18), purpose unknown
        'remote_humidity': data[4],       # Byte 4: Remote humidity (direct %)
        'probe1_temp': data[32] if data[34] == 1 else data[35],  # byte 35 may be stale
        'probe2_temp': data[32] if data[34] == 0 else data[42],  # byte 42 may be stale
        # Settings
        'airflow_indicator': data[47],
        'airflow_m3h': airflow_map.get(data[47], f'?{data[47]}'),
        'preheat_enabled': data[53] != 0,
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


def decode_probe_sensors_packet(hex_data: str) -> dict:
    """Decode a probe sensors packet (type 0x03)."""
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
        'byte6': data[6],  # Always 0x02 in captures (not preheat toggle)
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

    # Decode and show device state packets
    device_state_pkts = [p for p in packets['notifies'] if p['type'] == 0x01]
    if device_state_pkts:
        print(f"\n{'='*60}")
        print(f"DEVICE STATE PACKETS ({len(device_state_pkts)} total)")
        print(f"{'='*60}")

        for i, pkt in enumerate(device_state_pkts[:5]):  # Show first 5
            decoded = decode_device_state_packet(pkt['hex'])
            print(f"\nDevice State #{i+1}:")
            print(f"  Remote humidity: {decoded['remote_humidity']}%")
            print(f"  Probe1: {decoded['probe1_temp']}°C")
            print(f"  Probe2: {decoded['probe2_temp']}°C")
            print(f"  Mode selector: {decoded['mode_selector']} ({['LOW','MEDIUM','HIGH'][decoded['mode_selector']] if decoded['mode_selector'] < 3 else '?'})")
            print(f"  Unknown B32: {decoded['unknown_32']}")
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
                print(f"    Preheat temp: {decoded['preheat_temp']}°C")
                print(f"    Summer: {'ON' if decoded['summer_enabled'] else 'OFF'}")
                print(f"    Airflow: ({decoded['airflow_b1']}, {decoded['airflow_b2']})")

    # Show probe sensor packets
    probe_pkts = [p for p in packets['notifies'] if p['type'] == 0x03]
    if probe_pkts:
        print(f"\n{'='*60}")
        print(f"PROBE SENSOR PACKETS ({len(probe_pkts)} total)")
        print(f"{'='*60}")

        for pkt in probe_pkts[:2]:
            decoded = decode_probe_sensors_packet(pkt['hex'])
            print(f"\n  Byte 6: {decoded['byte6']}")
            print(f"  Byte 8: {decoded['byte8']}")
            print(f"  Byte 13: {decoded['byte13']} (filter %?)")
            print(f"  Hex[4:21]: {decoded['bytes_4_20_hex']}")
            # Look for filter days (331) or operating days (634)
            for off, val in decoded['u16_offsets'].items():
                if val in (331, 634, 330, 332, 633, 635):  # Allow ±1
                    print(f"  ** Found {val} at {off} **")


def print_checkpoint_correlation(packets: dict, checkpoints: list, window: int = 10):
    """Print packets correlated with each checkpoint."""
    print(f"\n{'='*60}")
    print(f"CHECKPOINT CORRELATION (window: ±{window}s)")
    print(f"{'='*60}")

    for cp in checkpoints:
        print(f"\n--- {cp['id']} ---")
        print(f"Timestamp: {cp.get('timestamp', '?')}")

        # Show recorded app values
        for key in ['remote_temp', 'remote_humidity', 'probe1_temp', 'probe1_humidity', 'probe2_temp', 'airflow']:
            if cp.get(key):
                print(f"  App {key}: {cp[key]}")

        if cp.get('notes'):
            print(f"  Notes: {cp['notes']}")

        # Find nearby packets
        ts = cp.get('timestamp')
        if not ts:
            print("  (no timestamp)")
            continue

        nearby = find_packets_near_checkpoint(packets['raw_packets'], ts, window)
        device_state_nearby = [p for p in nearby if p['type'] == 0x01]

        if not device_state_nearby:
            print(f"  No DEVICE_STATE packets within ±{window}s")
            continue

        print(f"  Found {len(device_state_nearby)} DEVICE_STATE packets nearby:")
        for pkt in device_state_nearby[:3]:  # Show up to 3
            decoded = decode_device_state_packet(pkt['hex'])
            print(f"    [{pkt['timestamp']}]")
            print(f"      Byte 4: {decoded.get('bytes_0_10', [0]*5)[4]} (current 'humidity')")
            print(f"      Byte 60: {decoded['byte60']} (÷2 = {decoded['byte60_div2']:.1f}%)")
            print(f"      Probe1 temp: {decoded['probe1_temp']}°C")
            print(f"      Mode: {decoded['mode_selector']}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Extract VMI packets from btsnoop log')
    parser.add_argument('btsnoop_file', help='Path to btsnoop log file')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--status-hex', action='store_true', help='Output all status packet hex')
    parser.add_argument('--checkpoints', help='Path to checkpoints.txt for correlation')
    parser.add_argument('--window', type=int, default=10, help='Checkpoint correlation window in seconds (default: 10)')
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

    # If checkpoints provided, show correlation
    if args.checkpoints:
        checkpoints = parse_checkpoints(args.checkpoints)
        if checkpoints:
            print_checkpoint_correlation(packets, checkpoints, args.window)
        else:
            print("\nNo checkpoints found in file", file=sys.stderr)


if __name__ == '__main__':
    main()
