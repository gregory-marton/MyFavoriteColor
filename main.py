
from machine import Pin, SoftI2C, PWM, ADC
import machine

#nav switches
switch_down = Pin(10, Pin.IN)
switch_select = Pin(9, Pin.IN)
switch_up= Pin(8, Pin.IN)
def btn_down():
    return not switch_down.value()
def btn_up():
    return not switch_up.value()
def btn_select():
    return not switch_select.value()

def healthcheck_pending():
    """A healthcheck_state.txt marker means either a run is mid-sequence,
    waiting out a deliberate reboot (healthcheck.py's OFFON stage), or
    healthcheck_host.py remote-started one -- either way, boot straight
    back into it regardless of what buttons are held (hands are often busy
    plugging in USB right when this matters)."""
    try:
        open("healthcheck_state.txt").close()
        return True
    except OSError:
        return False

def choose_activity(devices):
    if healthcheck_pending():
        return "healthcheck"
    elif btn_down() and btn_up() and btn_select():
        return "healthcheck"
    elif btn_down() and btn_up():
        return "webconnect"
    elif 0x10 in devices:
        return "myfavcolor"
    return "standalone"

def main():
    import sensors
    s = sensors.SENSORS()
    devices = s.i2c.scan()
    activity = choose_activity(devices)

    if activity == "myfavcolor":
        import myfavcolor
        myfavcolor.main()
    elif activity == "standalone":
        import standalone
        standalone.main()
    elif activity == "webconnect":
        import webconnect
        webconnect.main()
    elif activity == "healthcheck":
        import healthcheck
        healthcheck.main()
    else:
        pass


if __name__ == "__main__":
    main()
