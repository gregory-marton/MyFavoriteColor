"""Standalone SmartMotor hardware mirror.

This module intentionally owns the device while it is deployed. It does not
import the normal activity, write files, or wait on a host command loop. The
short sleep in :func:`run` gives the MicroPython scheduler and REPL interrupt
path regular opportunities to run.

Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import sys


BUTTONS = (("up", "UP"), ("down", "DN"), ("select", "SCT"))
MIRROR_BUTTON_PINS = {"up": 8, "down": 10, "select": 9}
# ADXL345 is configured for +/-2 g at 256 raw counts per g: 1024 counts
# spans the full possible change. These are fixed presentation thresholds,
# deliberately independent of a per-device noise calibration.
AXIS_FULL_SCALE = 1024
DELTA_ENTER = AXIS_FULL_SCALE * 0.011
DELTA_EXIT = AXIS_FULL_SCALE * 0.009
PORT_SPREAD_THRESHOLD = 2000


def pot_to_angle(value):
    value = max(0, min(4095, int(value)))
    return int((value * 180 + 2047) // 4095)


def sensor_attached(low_value, high_value):
    return not (int(low_value) < 200 and int(high_value) > 4000)


def port_mode(low_value, high_value):
    # Both 4 chars, so the MODE field on screen doesn't shift width when it
    # flips between the two.
    return "i2c " if int(high_value) - int(low_value) > PORT_SPREAD_THRESHOLD else "anlg"


def short_number(value):
    """Format a numeric OLED value to two significant digits."""
    value = float(value)
    magnitude = abs(value)
    if magnitude >= 1000:
        scaled = value / 1000.0
        return ("%.0fk" if abs(scaled) >= 10 else "%.1fk") % scaled
    return "%.2g" % value


class I2CSensor:
    """Minimal VEML6040 reader used only by mirror mode."""

    ADDRESS = 0x10

    def __init__(self, i2c):
        if self.ADDRESS not in i2c.scan():
            raise OSError("VEML6040 not found")
        self.i2c = i2c
        # Enable the sensor with the default integration time.
        i2c.writeto_mem(self.ADDRESS, 0x00, b"\x00\x00")

    def read_rgbw(self):
        values = []
        for register in (0x08, 0x09, 0x0A, 0x0B):
            data = self.i2c.readfrom_mem(self.ADDRESS, register, 2)
            values.append(int(data[0]) | (int(data[1]) << 8))
        return tuple(values)


def initialize_i2c_sensor(i2c, fallback_mode):
    try:
        if 0x10 not in i2c.scan():
            return fallback_mode, None
        return "i2c ", I2CSensor(i2c)
    except Exception:
        return "anlg", None


def delta_display(previous, current, previous_states=None):
    """Return independent X/Y/Z delta glyphs and their hysteresis states."""
    if previous is None or current is None:
        return "X  Y  Z ", (" ", " ", " ")
    if previous_states is None:
        previous_states = (" ", " ", " ")
    states = []
    for old, new, prior in zip(previous, current, previous_states):
        delta = int(new) - int(old)
        if delta == 0:
            state = " "
        else:
            direction = "^" if delta > 0 else "v"
            magnitude = abs(delta)
            if magnitude >= DELTA_ENTER:
                state = direction
            elif prior == direction and magnitude >= DELTA_EXIT:
                state = direction
            else:
                state = "~"
        states.append(state)
    states = tuple(states)
    return "X%s Y%s Z%s" % states, states


def delta_symbols(previous, current):
    return delta_display(previous, current)[0]


def screen_lines(battery_v, usb, port_mode, sensor_is_attached, sensor_value,
                 pot, angle, buttons, delta):
    sensor_text = short_number(sensor_value) if sensor_is_attached else "--"
    # Always shows all three, not just the pressed ones -- a steady "UP-
    # DN- SCT-" is itself useful information (confirms the line is live),
    # where a bare "-" reads the same whether nothing's pressed or nothing's
    # being read at all.
    button_text = " ".join(
        "%s%s" % (label, "+" if int(buttons.get(name, 1)) == 0 else "-")
        for name, label in BUTTONS
    )
    battery_text = "%sV" % short_number(battery_v) if battery_v is not None else "?V"
    # Fixed-width so the line doesn't reflow as the values change: pot
    # (0..4095) collapsed to its leading two significant digits (00..41),
    # angle (0..180) zero-padded to three digits.
    pot_text = "%02d" % int(round(pot / 100.0))
    angle_text = "%03d" % int(round(angle))
    return (
        "%s USB%s" % (battery_text, "+" if usb else "x"),
        "MODE %s SNS%s" % (port_mode, sensor_text),
        "POT %s ANG%s" % (pot_text, angle_text),
        "BTN %s" % button_text,
        "MOVE %s" % (delta or "-"),
    )


def _write(text):
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except Exception:
        pass


def _emit_frame(display, sequence):
    try:
        import ubinascii
    except ImportError:
        import binascii as ubinascii
    encoded = ubinascii.b2a_base64(bytes(display.buffer)).decode("ascii").strip()
    _write("@SMIRROR FRAME %d %d %d %s\n" % (
        sequence, display.width, display.height, encoded,
    ))


def _emit_status(power, usb, mode, sensor_is_attached, sensor_value,
                 pot, angle, buttons, delta, rgbw=None):
    rgbw = rgbw or (-1, -1, -1, -1)
    _write(
        "@SMIRROR STATUS power=%d usb=%d mode=%s sensor=%d "
        "sensor_value=%d sensor_r=%d sensor_g=%d sensor_b=%d sensor_w=%d "
        "pot=%d angle=%d up=%d down=%d select=%d delta=%s\n"
        % (
            int(power), int(usb), mode, int(sensor_is_attached),
            int(sensor_value) if sensor_is_attached else -1,
            int(rgbw[0]), int(rgbw[1]), int(rgbw[2]), int(rgbw[3]),
            int(pot), int(angle), int(buttons.get("up", 1)),
            int(buttons.get("down", 1)), int(buttons.get("select", 1)),
            delta or "-",
        )
    )


def _probe_sensor():
    from machine import ADC, Pin

    digital = Pin(5, Pin.OUT)
    digital.value(0)
    low = ADC(Pin(5)).read()
    digital = Pin(5, Pin.OUT)
    digital.value(1)
    high = ADC(Pin(5)).read()
    attached = sensor_attached(low, high)
    if not attached:
        return False, None, low, high
    sensor = ADC(Pin(5))
    try:
        sensor.atten(ADC.ATTN_11DB)
    except Exception:
        pass
    return True, sensor, low, high


def run(period_ms=250):
    """Run the only device activity until interrupted back to the REPL."""
    import time
    from machine import ADC, Pin, SoftI2C
    import adxl345
    import servo
    import ssd1306

    i2c = SoftI2C(scl=Pin(7), sda=Pin(6))
    display = None
    accelerometer = None
    try:
        display = ssd1306.SSD1306_I2C(128, 64, i2c)
    except Exception:
        pass
    try:
        accelerometer = adxl345.ADXL345(i2c)
    except Exception:
        pass

    pot_adc = ADC(Pin(3))
    try:
        pot_adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass
    battery_adc = ADC(Pin(4))
    try:
        battery_adc.atten(ADC.ATTN_11DB)
    except Exception:
        pass
    motor = servo.Servo(Pin(2))
    sensor_is_attached, sensor_adc, low, high = _probe_sensor()
    i2c_sensor = None
    buttons = {
        name: Pin(pin, Pin.IN, Pin.PULL_UP)
        for name, pin in MIRROR_BUTTON_PINS.items()
    }
    usb = hasattr(sys, "stdin") and hasattr(sys, "stdout")
    mode, i2c_sensor = initialize_i2c_sensor(i2c, port_mode(low, high))
    sensor_is_attached = i2c_sensor is not None or sensor_is_attached
    previous_accel = None
    delta_states = (" ", " ", " ")
    sequence = 0
    _write("@SMIRROR READY 1\n")

    while True:
        pot = pot_adc.read()
        angle = pot_to_angle(pot)
        motor.write_angle(angle)
        button_values = {name: pin.value() for name, pin in buttons.items()}
        rgbw = i2c_sensor.read_rgbw() if i2c_sensor is not None else None
        sensor_value = rgbw[3] if rgbw is not None else (
            sensor_adc.read() if sensor_adc is not None else -1
        )

        accel = None
        if accelerometer is not None:
            try:
                accel = accelerometer.read()
            except Exception:
                accel = None
        delta, delta_states = delta_display(previous_accel, accel, delta_states)
        if accel is not None:
            previous_accel = accel
            _write("@SMIRROR ACCEL %d %d %d\n" % accel)

        try:
            battery_v = battery_adc.read_uv() / 1e6
        except Exception:
            battery_v = None
        lines = screen_lines(
            battery_v, usb, mode, sensor_is_attached, sensor_value,
            pot, angle, button_values, delta,
        )
        if display is not None:
            display.fill(0)
            for row, line in enumerate(lines):
                display.text(line[:16], 0, row * 12, 1)
            display.show()
            sequence += 1
            _emit_frame(display, sequence)

        _emit_status(
            True, usb, mode, sensor_is_attached, sensor_value,
            pot, angle, button_values, delta,
        )
        time.sleep_ms(period_ms)


if __name__ == "__main__":
    run()
