# Physical Verification with Vibration Monitoring

BLE protocol reverse engineering often requires verifying that a command has a **physical effect** on the device, not just a change in BLE state bytes. The VisionAir protocol has cases where BLE-visible state changes (mode bytes, indicator values) do not correspond to physical changes (fan motor speed). A vibration sensor mounted on the device provides an automated, authoritative way to detect physical fan speed changes without human observation.

## Hardware Setup

An M5StickC Plus2 (ESP32 with built-in MPU6886 accelerometer) is taped directly to the VMI housing. It runs ESPHome firmware with a custom `vibration_sensor` component that:

1. Reads the accelerometer at high speed (~500 samples)
2. Computes the standard deviation of the acceleration magnitude
3. Publishes a single "vibration level" value (m/s²) once per second

The standard deviation captures the AC component of vibration — the oscillation caused by the fan motor — while rejecting the DC component (gravity). Higher fan speed produces stronger vibration, which shows up as a higher std dev.

### ESPHome Configuration

The ESPHome config and custom component are in the `~/esphome/` directory (not part of this repo). The key pieces:

- **Sensor**: `mpu6886` accelerometer on I2C (SDA=GPIO21, SCL=GPIO22)
- **Custom component**: Reads 500 accelerometer samples per update, computes std dev of acceleration magnitude
- **API**: Accessible over WiFi via the ESPHome native API

The device also has a built-in SPM1423 PDM microphone exposed as a sound level sensor, but it is too insensitive to detect fan speed changes (see [Sensor Comparison](#sensor-comparison) below).

### Querying from Scripts

```bash
# Single vibration reading
uv run python scripts/sound_monitor.py --vibration
# Output: 0.0350

# All sensors
uv run python scripts/sound_monitor.py
# Output:
# Vibration: 0.0350 m/s²
# Sound RMS: -48.1 dB
# Sound Peak: -43.6 dB

# Stream readings (for monitoring transitions)
uv run python scripts/sound_monitor.py --stream 30
```

As a library in experiment scripts:

```python
from scripts.sound_monitor import read_vibration, read_sensors

level = await read_vibration()  # returns float, e.g. 0.035
sensors = await read_sensors()  # returns SensorReading dataclass
```

## Vibration Levels by Fan Speed

Measured with the sensor taped to the VMI housing:

| Fan speed | Vibration (m/s²) | Range | Relative to LOW |
|-----------|------------------|-------|-----------------|
| LOW | ~0.035 | 0.030 – 0.039 | — |
| HIGH | ~0.048 | 0.044 – 0.053 | +37% |
| MAX (boost) | ~0.069 | 0.060 – 0.077 | +97% |

MAX is clearly distinguishable from LOW/HIGH with a single reading. HIGH vs LOW requires a **rolling average over 20-30 seconds** to reliably separate, since individual readings can overlap.

## Fan Speed Ramp Behavior

The fan motor does not change speed instantaneously. The ramp-up and ramp-down times are asymmetric:

### Ramp-up (increasing speed)

| Transition | Time to plateau |
|-----------|-----------------|
| LOW → HIGH | ~20 seconds, with a secondary settling phase over ~2 minutes |
| LOW → MAX | ~20 seconds |

HIGH mode shows a two-phase ramp: an initial jump to ~0.043, then a gradual climb to the settled value of ~0.048 over about 2 minutes.

### Ramp-down (decreasing speed)

| Transition | Time to baseline |
|-----------|------------------|
| MAX → LOW | ~4 minutes |
| HIGH → LOW | ~1.5 minutes |

The ramp-down has a long tail that is inaudible but clearly visible in vibration data. A human listener perceives the speed change completing in 15-20 seconds, but the motor continues decelerating for much longer.

### Implications for Testing

- **After switching to a higher speed**: wait **30 seconds** before reading vibration (fast ramp-up)
- **After switching to a lower speed**: wait **4 minutes** before taking a baseline reading (slow ramp-down)
- **Comparing before/after a command**: take a 30-second rolling average, not a single reading
- **A/B/A/B experiments**: allow enough settling time between phases, especially for downward transitions

## Sensor Comparison

| Sensor | Detects fan speed? | Signal quality | Notes |
|--------|-------------------|----------------|-------|
| Accelerometer (MPU6886, on housing) | **Yes** | Good for MAX, marginal for HIGH | Std dev of 500 fast samples. Best physical indicator available. |
| Microphone (SPM1423, on housing) | No | No signal | Built-in MEMS mic is too insensitive for low-frequency fan noise through the housing. |
| Microphone (SPM1423, near vent) | Marginal | ~1 dB shift | Detects airflow noise at the vent opening, but the signal is weak and noisy. |
| BLE DEVICE_STATE bytes | No (for physical speed) | N/A | Bytes 32/34/47/48/60 change with mode commands but do not reflect physical motor speed. |
| Power monitoring (Shelly EM) | No | No signal | Household load noise drowns out the VMI's power delta. |

## Use in Reverse Engineering

### Verifying commands change physical fan speed

When investigating whether a BLE command actually changes the fan motor speed (as opposed to just changing state bytes):

1. Read vibration baseline (30-second average)
2. Send the BLE command
3. Wait 30 seconds (for ramp-up) or 4 minutes (if expecting ramp-down)
4. Read vibration again (30-second average)
5. Compare: a shift from ~0.035 to ~0.069 confirms MAX activation; ~0.035 to ~0.048 confirms HIGH

### Monitoring transitions during capture sessions

Stream vibration readings alongside BLE commands to correlate physical changes with protocol events:

```python
# In an experiment script
from scripts.sound_monitor import read_vibration

baseline = await read_vibration()
# ... send BLE command ...
await asyncio.sleep(30)
after = await read_vibration()

speed_changed = abs(after - baseline) > 0.005  # threshold for detecting change
```

### Distinguishing BLE-state-only changes from physical changes

This is the primary use case. Some commands (e.g., REQUEST param 0x18) change BLE-visible mode bytes without affecting the physical fan speed. The vibration sensor provides ground truth: if the vibration level doesn't change after a command, the command did not change the motor speed, regardless of what the BLE state bytes show.
