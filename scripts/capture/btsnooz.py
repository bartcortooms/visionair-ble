#!/usr/bin/env python
"""
This script extracts btsnooz content from bugreports and generates
a valid btsnoop log file which can be viewed using standard tools
like Wireshark.

btsnooz is a custom format designed to be included in bugreports.
It can be described as:

base64 {
  file_header
  deflate {
    repeated {
      record_header
      record_data
    }
  }
}

where the file_header and record_header are modified versions of
the btsnoop headers.
"""
import base64
import fileinput
import struct
import sys
import zlib

TYPE_IN_EVT = 0x10
TYPE_IN_ACL = 0x11
TYPE_IN_SCO = 0x12
TYPE_IN_ISO = 0x17
TYPE_OUT_CMD = 0x20
TYPE_OUT_ACL = 0x21
TYPE_OUT_SCO = 0x22
TYPE_OUT_ISO = 0x2d


def type_to_direction(type):
    if type in [TYPE_IN_EVT, TYPE_IN_ACL, TYPE_IN_SCO, TYPE_IN_ISO]:
        return 1
    return 0


def type_to_hci(type):
    if type == TYPE_OUT_CMD:
        return '\x01'
    if type == TYPE_IN_ACL or type == TYPE_OUT_ACL:
        return '\x02'
    if type == TYPE_IN_SCO or type == TYPE_OUT_SCO:
        return '\x03'
    if type == TYPE_IN_EVT:
        return '\x04'
    if type == TYPE_IN_ISO or type == TYPE_OUT_ISO:
        return '\x05'
    raise RuntimeError("type_to_hci: unknown type (0x{:02x})".format(type))


def decode_snooz(snooz, output_file):
    """Decode btsnooz data and write to output file."""
    version, last_timestamp_ms = struct.unpack_from('=bQ', snooz)
    if version != 1 and version != 2:
        sys.stderr.write('Unsupported btsnooz version: %s\n' % version)
        exit(1)

    decompressed = zlib.decompress(snooz[9:])

    # Write btsnoop header
    output_file.write(b'btsnoop\x00\x00\x00\x00\x01\x00\x00\x03\xea')

    if version == 1:
        decode_snooz_v1(decompressed, last_timestamp_ms, output_file)
    elif version == 2:
        decode_snooz_v2(decompressed, last_timestamp_ms, output_file)


def decode_snooz_v1(decompressed, last_timestamp_ms, fp):
    first_timestamp_ms = last_timestamp_ms + 0x00dcddb30f2f8000

    # First pass to calculate timestamps
    offset = 0
    while offset < len(decompressed):
        length, delta_time_ms, type = struct.unpack_from('=HIb', decompressed, offset)
        offset += 7 + length - 1
        first_timestamp_ms -= delta_time_ms

    # Second pass to write packets
    offset = 0
    while offset < len(decompressed):
        length, delta_time_ms, type = struct.unpack_from('=HIb', decompressed, offset)
        first_timestamp_ms += delta_time_ms
        offset += 7

        fp.write(struct.pack('>II', length, length))
        fp.write(struct.pack('>II', type_to_direction(type), 0))
        fp.write(struct.pack('>II', (first_timestamp_ms >> 32), (first_timestamp_ms & 0xFFFFFFFF)))
        fp.write(type_to_hci(type).encode("latin-1"))
        fp.write(decompressed[offset:offset + length - 1])
        offset += length - 1


def decode_snooz_v2(decompressed, last_timestamp_ms, fp):
    first_timestamp_ms = last_timestamp_ms + 0x00dcddb30f2f8000

    # First pass
    offset = 0
    while offset < len(decompressed):
        length, packet_length, delta_time_ms, snooz_type = struct.unpack_from('=HHIb', decompressed, offset)
        offset += 9 + length - 1
        first_timestamp_ms -= delta_time_ms

    # Second pass
    offset = 0
    while offset < len(decompressed):
        length, packet_length, delta_time_ms, snooz_type = struct.unpack_from('=HHIb', decompressed, offset)
        first_timestamp_ms += delta_time_ms
        offset += 9

        fp.write(struct.pack('>II', packet_length, length))
        fp.write(struct.pack('>II', type_to_direction(snooz_type), 0))
        fp.write(struct.pack('>II', (first_timestamp_ms >> 32), (first_timestamp_ms & 0xFFFFFFFF)))
        fp.write(type_to_hci(snooz_type).encode("latin-1"))
        fp.write(decompressed[offset:offset + length - 1])
        offset += length - 1


def decode_from_file(btsnooz_file, output_path):
    """Decode a raw btsnooz_hci.log file directly."""
    with open(btsnooz_file, 'rb') as f:
        snooz_data = f.read()

    with open(output_path, 'wb') as fp:
        decode_snooz(snooz_data, fp)

    print(f"Decoded btsnoop log written to: {output_path}")


def decode_from_bugreport(bugreport_path, output_path):
    """Extract btsnooz from bugreport text file."""
    found = False
    base64_string = ""

    with open(bugreport_path, 'r', encoding='latin-1') as f:
        for line in f:
            if found:
                if '--- END:BTSNOOP_LOG_SUMMARY' in line:
                    snooz_data = base64.standard_b64decode(base64_string)
                    with open(output_path, 'wb') as fp:
                        decode_snooz(snooz_data, fp)
                    print(f"Decoded btsnoop log written to: {output_path}")
                    return True
                base64_string += line.strip()
            if '--- BEGIN:BTSNOOP_LOG_SUMMARY' in line:
                found = True

    if not found:
        sys.stderr.write('No BTSNOOP_LOG_SUMMARY section found in bugreport.\n')
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  {sys.argv[0]} <btsnooz_hci.log>              - Decode raw btsnooz file")
        print(f"  {sys.argv[0]} <bugreport.txt>               - Extract from bugreport")
        print(f"  {sys.argv[0]} <input> <output.log>          - Specify output file")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "btsnoop_decoded.log"

    # Check if it's a raw btsnooz file or a bugreport
    with open(input_file, 'rb') as f:
        header = f.read(20)

    # btsnooz files start with version byte (1 or 2) followed by timestamp
    # bugreport text files start with text
    if header[0] in [1, 2] and not header[:4].isalpha():
        print(f"Detected raw btsnooz file (version {header[0]})")
        decode_from_file(input_file, output_file)
    else:
        print("Attempting to parse as bugreport text file...")
        decode_from_bugreport(input_file, output_file)


if __name__ == '__main__':
    main()
