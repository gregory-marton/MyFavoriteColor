import time

class MockState:
    def __init__(self):
        self.pins = {}       # pin_id -> value (0 or 1)
        self.pin_queues = {} # pin_id -> list of values (0 or 1)
        self.adc = {}        # pin_id -> value (int)
        self.pwm = {}        # pin_id -> duty (int)
        self.timers = {}     # timer_id -> (period, mode, callback)
        self.i2c_devices = [0x10] # VEML6040 address by default
        self.i2c_mem = {}    # (addr, memaddr) -> bytes

state = MockState()

def reset_mock_state():
    global state
    state = MockState()

class Pin:
    IN = "IN"
    OUT = "OUT"
    
    def __init__(self, id, mode=IN, pull=-1, value=None):
        self.id = id
        self.mode = mode
        if value is not None:
            state.pins[self.id] = value
        elif self.id not in state.pins:
            state.pins[self.id] = 1 # default to high (since switches are pull-up / active low)

    def value(self, val=None):
        if val is not None:
            state.pins[self.id] = val
        if self.id in state.pin_queues and state.pin_queues[self.id]:
            return state.pin_queues[self.id].pop(0)
        return state.pins.get(self.id, 1)

    def __call__(self, val=None):
        return self.value(val)

class SoftI2C:
    def __init__(self, scl, sda, freq=400000):
        self.scl = scl
        self.sda = sda
        self.freq = freq

    def scan(self):
        return state.i2c_devices

    def readfrom_mem(self, addr, memaddr, nbytes):
        # Default mock responses for VEML6040 registers if not explicitly set
        if addr == 0x10:
            # 0x08 = R, 0x09 = G, 0x0A = B, 0x0B = W
            # Let's return some default values if not configured in state.i2c_mem
            if (addr, memaddr) not in state.i2c_mem:
                if memaddr == 0x08: # R
                    return b'\x00\x04' # 1024 (1024 >> 6 = 16)
                elif memaddr == 0x09: # G
                    return b'\x00\x08' # 2048 (2048 >> 6 = 32)
                elif memaddr == 0x0A: # B
                    return b'\x00\x0c' # 3072 (3072 >> 6 = 48)
                elif memaddr == 0x0B: # W
                    return b'\x00\x10' # 4096 (4096 >> 6 = 64)
                else:
                    return b'\x00\x00'
        return state.i2c_mem.get((addr, memaddr), b'\x00' * nbytes)

    def writeto_mem(self, addr, memaddr, buf):
        state.i2c_mem[(addr, memaddr)] = buf

class I2C(SoftI2C):
    pass

class ADC:
    ATTN_11DB = "11DB"
    
    def __init__(self, pin):
        self.pin = pin

    def atten(self, level):
        pass

    def read(self):
        pin_id = self.pin.id if hasattr(self.pin, "id") else self.pin
        return state.adc.get(pin_id, 2048) # default to mid-range pot / sensor reading

class PWM:
    def __init__(self, pin, freq=50, duty=0):
        self.pin = pin
        self.freq = freq
        self.duty_val = duty
        pin_id = self.pin.id if hasattr(self.pin, "id") else self.pin
        state.pwm[pin_id] = duty

    def duty(self, val=None):
        if val is not None:
            self.duty_val = val
            pin_id = self.pin.id if hasattr(self.pin, "id") else self.pin
            state.pwm[pin_id] = val
        return self.duty_val

class Timer:
    ONE_SHOT = 0
    PERIODIC = 1
    
    def __init__(self, id):
        self.id = id

    def init(self, period=1000, mode=PERIODIC, callback=None):
        state.timers[self.id] = (period, mode, callback)

    def deinit(self):
        if self.id in state.timers:
            del state.timers[self.id]

def unique_id():
    return b'\x12\x34\x56\x78'
