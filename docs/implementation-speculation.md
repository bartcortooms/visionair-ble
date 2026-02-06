# Implementation Speculation

> **Disclaimer:** This document contains educated guesses about how the VisionAir firmware was implemented, based on protocol analysis and publicly available Cypress/Infineon documentation. This is speculative and intended to aid future reverse engineering efforts.

## Summary

The VisionAir BLE protocol appears to be built on top of a **Cypress PSoC 4 BLE demo project**, specifically the "Day003 Custom Profile CapSense RGB LED" example from Cypress's "100 Projects in 100 Days" series.

## Evidence

### 1. Identical GATT Handles and Service Indices

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

Cypress uses `CYBLE_CYPACKED` for packed structs (from Day046 Cycling Sensor example):

```c
CYBLE_CYPACKED typedef struct
{
    uint16 flags;                       /* Mandatory */
    int16 instantaneousPower;           /* Mandatory */
    uint32 accumulatedTorque;           /* Send only low 2 bytes */
    // ...
}CYBLE_CYPACKED_ATTR CYBLE_CPS_POWER_MEASURE_T;
```

VisionAir likely uses similar packed structs:
```c
CYBLE_CYPACKED typedef struct
{
    uint8_t type;           // 0x01 for status
    uint8_t reserved;
    uint8_t humidity;       // byte 4: remote humidity %
    uint8_t unknown[3];     // bytes 5-7: constant per device
    // ... 182 bytes total
}CYBLE_CYPACKED_ATTR VISIONAIR_STATUS_T;

// Send notification
CyBle_GattsNotification(cyBle_connHandle, &notificationData);
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

### 5. RTC Implementation (superseded legacy hypothesis)

Early captures suggested special-mode commands (byte7=0x04 SETTINGS packets) might
include HH:MM:SS values. This hypothesis has been **superseded**: controlled captures
(2026) show Holiday control uses `REQUEST 0x1a` value packets, not time-encoded
SETTINGS packets.

The PSoC BLE RTC example (Day033) provides general background on how the device
may keep time internally:

- PSoC uses **Watchdog Timer** for 1-second interrupts to maintain time
- The `CYBLE_CTS_CURRENT_TIME_T` struct stores hours, minutes, seconds
- Time sync from app is common because low-power devices lack battery-backed RTC

This is retained as reference for understanding the device's timekeeping, not as
an explanation of the Holiday/special-mode command protocol.

### 6. BLE Event Handler Pattern

The Day003 code shows the exact pattern VisionAir uses:

```c
void CustomEventHandler(uint32 event, void * eventParam)
{
    CYBLE_GATTS_WRITE_REQ_PARAM_T *wrReqParam;

    switch(event)
    {
        case CYBLE_EVT_GATTS_WRITE_REQ:
            wrReqParam = (CYBLE_GATTS_WRITE_REQ_PARAM_T *) eventParam;

            // Match attribute handle to determine which characteristic
            if(wrReqParam->handleValPair.attrHandle ==
               cyBle_customs[SERVICE_INDEX].customServiceInfo[CHAR_INDEX].customServiceCharHandle)
            {
                // Extract data and act on it
                data[0] = wrReqParam->handleValPair.value.val[0];
                // ...
            }

            // Send write response
            CyBle_GattsWriteRsp(cyBle_connHandle);
            break;
    }
}
```

VisionAir's command processing likely follows this exact structure — matching handle 0x0013 and parsing the command bytes.

## Open Questions

- Does the device expose UART for debugging/configuration?
- Is there an installer/factory mode accessible via BLE?
- What differentiates Holiday/Night Vent/Fixed Air Flow commands in current firmware path? (May be state machine on device)
- Is there a bootloader for OTA updates? (PSoC supports this)

### 7. Temperature Measurement Pattern

Day005 Health Thermometer shows how PSoC measures temperature:

```c
// Measure thermistor resistance with offset removal
thermistorResistance = Thermistor_GetResistance(
    (referenceVoltage - offsetVoltage),
    (thermistorVoltage - offsetVoltage));

// Convert to temperature (returns value * 100 for precision)
temperature = Thermistor_GetTemperature(thermistorResistance);
temperature = temperature / 100;  // Remove decimal places
```

VisionAir's whole-degree temperature readings (Probe 1, Probe 2, Remote) likely use similar ADC-based thermistor measurement, stored as uint8 (0-255°C range, only positive temps needed for HVAC).

## Summary of VisionAir Implementation Model

Based on PSoC-4-BLE code analysis:

1. **Based on Day003 Custom Profile** — Identical handles (0x000e, 0x0013, 0x000f)
2. **Struct serialization** — `CYBLE_CYPACKED` structs sent via `CyBle_GattsNotification()`
3. **Event-driven command processing** — `CustomEventHandler()` matches attribute handles
4. **WDT-based timekeeping** — Potentially relevant if timestamp-based mode commands are used
5. **Thermistor ADC measurement** — Standard PSoC pattern for temperature probes
6. **UART heritage** — Magic bytes + XOR checksum from pre-BLE serial protocol

## Resources

- [Infineon PSoC-4-BLE GitHub](https://github.com/Infineon/PSoC-4-BLE)
- [Day003 Custom Profile Example](https://github.com/Infineon/PSoC-4-BLE/tree/master/100_Projects_in_100_Days/Day003_Custom_Profile_CapSense_RGB_LED)
- [Day005 Health Thermometer](https://github.com/Infineon/PSoC-4-BLE/tree/master/100_Projects_in_100_Days/Day005_Health_Thermometer)
- [Day033 BLE RTC](https://github.com/Infineon/PSoC-4-BLE/tree/master/100_Projects_in_100_Days/Day033_BLE_RTC)
- [Day046 Cycling Sensor](https://github.com/Infineon/PSoC-4-BLE/tree/master/100_Projects_in_100_Days/Day046_Cycling_Sensor) (packed struct example)
- [AN91162 - Creating a BLE Custom Profile](https://www.infineon.com/dgdl/Infineon-AN91162_Creating_a_BLE_Custom_Profile-ApplicationNotes-v05_00-EN.pdf)
- [Cypress PSoC 6 BLE Middleware API Reference](https://infineon.github.io/bless/ble_api_reference_manual/html/index.html)
- [IoT Expert PSoC4 BLE Custom Profile Tutorial](https://iotexpert.com/psoc4-ble-central-custom-profile-wled-capsense/)
