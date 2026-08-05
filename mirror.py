"""Standalone SmartMotor hardware mirror.

This module intentionally owns the device while it is deployed. It does not
import the normal activity, write files, or wait on a host command loop. The
short sleep in :func:`run` gives the MicroPython scheduler and REPL interrupt
path regular opportunities to run.

Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import sys


BUTTONS = (("up", "UP"), ("down", "DOWN"), ("select", "SLCT"))
MIRROR_BUTTON_PINS = {"up": 8, "down": 10, "select": 9}
AXIS_THRESHOLD = 80
PORT_SPREAD_THRESHOLD = 2000


def pot_to_angle(value):
    value = max(0, min(4095, int(value)))
    return int((value * 180 + 2047) // 4095)


def sensor_attached(low_value, high_value):
    return not (int(low_value) < 200 and int(high_value) > 4000)


def port_mode(low_value, high_value):
    return "i2c" if int(high_value) - int(low_value) > PORT_SPREAD_THRESHOLD else "alg"


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
        return "i2c", I2CSensor(i2c)
    except Exception:
        return "alg", None


def delta_symbols(previous, current, threshold=AXIS_THRESHOLD):
    if previous is None or current is None:
        return ""
    dx = int(current[0]) - int(previous[0])
    dy = int(current[1]) - int(previous[1])
    dz = int(current[2]) - int(previous[2])
    symbols = []
    if dx > threshold:
        symbols.append(">")
    elif dx < -threshold:
        symbols.append("<")
    if dy > threshold:
        symbols.append("v")
    elif dy < -threshold:
        symbols.append("^")
    if dz > threshold:
        symbols.append("J")
    elif dz < -threshold:
        symbols.append("L")
    return "".join(symbols)


def screen_lines(power, usb, port_mode, sensor_is_attached, sensor_value,
                 pot, angle, buttons, delta):
    sensor_text = short_number(sensor_value) if sensor_is_attached else "--"
    active = [label for name, label in BUTTONS if int(buttons.get(name, 1)) == 0]
    button_text = "+".join(active) if active else "-"
    return (
        "PWR %s USB %s" % ("ON" if power else "OFF", "ON" if usb else "OFF"),
        "MODE %s SNS%s" % (port_mode, sensor_text),
        "POT%s ANG%s" % (short_number(pot), short_number(angle)),
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
        delta = delta_symbols(previous_accel, accel)
        if accel is not None:
            previous_accel = accel
            _write("@SMIRROR ACCEL %d %d %d\n" % accel)

        lines = screen_lines(
            True, usb, mode, sensor_is_attached, sensor_value,
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
