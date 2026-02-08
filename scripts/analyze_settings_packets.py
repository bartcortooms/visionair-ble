#!/usr/bin/env python3
"""Extract all SETTINGS (0x1a) packets from a btsnoop log with timestamps.

Prints raw hex bytes and decoded fields for each SETTINGS packet,
for investigating whether bytes 5-10 carry clock sync data or config data.
"""

import sys
from pathlib import Path

# Add parent paths so we can import from the capture scripts
sys.path.insert(0, str(Path(__file__).parent / "capture"))

from extract_packets import parse_btsnoop, find_vmi_packets


def main():
    btsnoop_file = sys.argv[1] if len(sys.argv) > 1 else None
    if not btsnoop_file:
        print("Usage: python scripts/analyze_settings_packets.py <btsnoop.log>", file=sys.stderr)
        sys.exit(1)

    records = parse_btsnoop(btsnoop_file)
    if not records:
        print("No records found", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {len(records)} HCI records", file=sys.stderr)

    packets = find_vmi_packets(records)

    # Filter to SETTINGS packets only
    settings_pkts = [p for p in packets['raw_packets'] if p['type'] == 0x1a]

    print(f"Found {len(settings_pkts)} SETTINGS packets\n")

    # Header
    print(f"{'#':>3}  {'Timestamp':>26}  {'Full Hex':24}  "
          f"{'B3':>3} {'B4':>3} {'B5':>4} {'B6':>3} {'B7':>3} {'B8':>3} {'B9':>4} {'B10':>4}  "
          f"{'Decoded':40}")
    print("-" * 140)

    # Known airflow byte pairs
    airflow_names = {
        (0x19, 0x0A): "LOW",
        (0x28, 0x15): "MEDIUM",
        (0x07, 0x30): "HIGH",
    }

    for i, pkt in enumerate(settings_pkts):
        data = bytes.fromhex(pkt['hex'])
        ts = pkt['timestamp']

        if len(data) < 12:
            print(f"{i+1:3}  {ts:>26}  {pkt['hex']:24}  (too short)")
            continue

        # Bytes after magic (a5b6):
        # [2]=type, [3]=?, [4]=?, [5]=0x1a, [6]=const, [7]=summer/mode,
        # [8]=preheat_temp, [9]=airflow_b1, [10]=airflow_b2, [11]=checksum
        b3 = data[3]
        b4 = data[4]
        b5 = data[5]
        b6 = data[6]
        b7 = data[7]
        b8 = data[8]
        b9 = data[9]
        b10 = data[10]
        checksum = data[11]

        # Decode
        airflow_pair = (b9, b10)
        airflow_name = airflow_names.get(airflow_pair, f"?({b9:#04x},{b10:#04x})")

        summer = "SUM_ON" if b7 == 0x02 else ("SUM_OFF" if b7 == 0x00 else f"mode={b7:#04x}")
        preheat = f"pre={b8}°C"

        decoded = f"{summer}, {preheat}, airflow={airflow_name}"

        # Also show if bytes 7-10 could be clock data (day, hour, min, sec)
        clock_interp = f"  [clock? day={b7} h={b8} m={b9} s={b10}]"

        print(f"{i+1:3}  {ts:>26}  {pkt['hex']:24}  "
              f"{b3:3d} {b4:3d} {b5:#04x} {b6:3d} {b7:3d} {b8:3d} {b9:#04x} {b10:#04x}  "
              f"{decoded}{clock_interp}")

    # Also show SETTINGS_ACK packets (0x23) for context
    ack_pkts = [p for p in packets['raw_packets'] if p['type'] == 0x23]
    if ack_pkts:
        print(f"\n\nSETTINGS_ACK packets (0x23): {len(ack_pkts)}")
        for i, pkt in enumerate(ack_pkts[:10]):
            print(f"  {i+1:3}  {pkt['timestamp']:>26}  {pkt['hex'][:40]}...")

    # Also show REQUEST packets for context (especially 0x18 mode changes)
    req_pkts = [p for p in packets['raw_packets'] if p['type'] == 0x10]
    if req_pkts:
        print(f"\n\nREQUEST packets (0x10): {len(req_pkts)}")
        for i, pkt in enumerate(req_pkts):
            data = bytes.fromhex(pkt['hex'])
            if len(data) >= 6:
                param = data[5]
                param_names = {
                    0x03: "DEVICE_STATE", 0x06: "FULL_DATA", 0x07: "PROBE_SENSORS",
                    0x18: "MODE_SELECT", 0x19: "BOOST", 0x1A: "HOLIDAY",
                    0x1D: "SCHEDULE_TOGGLE", 0x2F: "PREHEAT",
                    0x26: "SCHEDULE_QUERY", 0x27: "SCHEDULE_CONFIG", 0x2C: "UNKNOWN_2C",
                }
                param_name = param_names.get(param, f"UNKNOWN_{param:#04x}")
                value = data[6] if len(data) > 6 else None
                print(f"  {i+1:3}  {pkt['timestamp']:>26}  param={param_name}({param:#04x})"
                      f"  value={value}  hex={pkt['hex']}")


if __name__ == '__main__':
    main()
