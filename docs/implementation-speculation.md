# Implementation Speculation

> **Disclaimer:** This document contains educated guesses about how the VisionAir firmware was implemented, based on protocol analysis and publicly available Cypress/Infineon documentation. This is speculative and intended to aid future reverse engineering efforts.

## Summary

The VisionAir BLE protocol appears to be built on top of a **Cypress PSoC 4 BLE demo project**, specifically the "Day003 Custom Profile CapSense RGB LED" example from Cypress's "100 Projects in 100 Days" series.

## Evidence

### 1. Identical GATT Handles

The VisionAir device uses the exact same characteristic handles as the Day003 example:

| Handle | Day003 Purpose | VisionAir Purpose |
|--------|----------------|-------------------|
| 0x000e | CapSense Slider (Notify) | Status notifications |
| 0x0013 | RGB LED (Write) | Commands |
| 0x000f | CapSense CCCD | Notification enable |

Source: [BLEApplications.h](https://github.com/Infineon/PSoC-4-BLE/blob/master/100_Projects_in_100_Days/Day003_Custom_Profile_CapSense_RGB_LED/Custom%20Profile/Custom%20Profile.cydsn/BLEApplications.h)

### 2. Cypress Custom UUID Pattern

The UUIDs follow Cypress's custom UUID format:

```
0003xxxx-0000-1000-8000-00805f9b0131
     ^^^^
     Service-specific identifier
```

Known Cypress service UUIDs in this format:
- `0003CBBB-...` — RGB LED Service
- `0003CAB5-...` — CapSense Service (our Data Service)
- `0003CBB1-...` — RGB LED Characteristic (our Command characteristic)
- `0003CAA2-...` — CapSense Characteristic (our Notify characteristic)

These are the exact UUIDs used by VisionAir.

### 3. Protocol Characteristics Suggest C Struct Serialization

- **Fixed 182-byte packets** — Suggests `sizeof(struct)` with generous buffer
- **Little-endian multi-byte values** — Matches ARM Cortex-M0 (PSoC) native byte order
- **Fields at fixed offsets** — No TLV, no length prefixes, just raw struct layout
- **No modern serialization** — Not protobuf, msgpack, CBOR, or any self-describing format

Likely implementation:
```c
#pragma pack(1)
struct status_packet {
    uint8_t type;
    uint8_t reserved;
    // ... fields at documented offsets
};

// Send status
memcpy(ble_buffer, &status, sizeof(status));
CyBle_GattsNotification(connHandle, &notificationData);
```

### 4. Magic Bytes + XOR Checksum = UART Heritage

The `0xa5 0xb6` magic prefix and XOR checksum are classic **serial protocol framing** patterns:

- Magic bytes: Used to find packet boundaries in byte streams
- XOR checksum: Simplest possible integrity check

BLE GATT doesn't need this — packets are already framed by the protocol. Including it anyway suggests:
1. The protocol was originally designed for UART communication
2. It was later wrapped in BLE with minimal changes
3. Or the developers were unfamiliar with BLE best practices

## Implications for Reverse Engineering

### What This Tells Us

1. **The codebase is likely based on PSoC Creator IDE** with the BLE component configured via GUI
2. **No custom protocol library** — Just raw byte manipulation
3. **Protocol evolved organically** — Fields added where they fit, not designed upfront
4. **UART debugging may exist** — If they had UART protocol, there might be debug commands

### Where to Look for Answers

1. **Cypress AN91162** — "Creating a BLE Custom Profile" application note describes exactly this pattern
2. **PSoC-4-BLE GitHub repo** — The Day003 project structure likely matches VisionAir's
3. **BLE_gatt.c generated file** — Contains UUID definitions in `cyBle_attUuid128[][16u]` array
4. **Firmware updates** — If the device supports OTA, the update format might reveal more

### Open Questions

- Does the device expose UART for debugging/configuration?
- Is there an installer/factory mode accessible via BLE?
- What differentiates Holiday/Night Vent/Fixed Air Flow commands? (May be state machine on device)

## Resources

- [Infineon PSoC-4-BLE GitHub](https://github.com/Infineon/PSoC-4-BLE)
- [Day003 Custom Profile Example](https://github.com/Infineon/PSoC-4-BLE/tree/master/100_Projects_in_100_Days/Day003_Custom_Profile_CapSense_RGB_LED)
- [AN91162 - Creating a BLE Custom Profile](https://www.infineon.com/dgdl/Infineon-AN91162_Creating_a_BLE_Custom_Profile-ApplicationNotes-v05_00-EN.pdf)
- [Cypress PSoC 6 BLE Middleware API Reference](https://infineon.github.io/bless/ble_api_reference_manual/html/index.html)
- [IoT Expert PSoC4 BLE Custom Profile Tutorial](https://iotexpert.com/psoc4-ble-central-custom-profile-wled-capsense/)
