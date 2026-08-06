
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

def choose_activity(devices):
    if btn_down() and btn_up() and btn_select():
        return "mirror"
    elif btn_down() and btn_select():
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
    elif activity == "mirror":
        import mirror
        mirror.main()
    else:
        pass


if __name__ == "__main__":
    main()
