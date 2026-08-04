# Co-authored-by: GPT-5, Aug 2026

from machine import Pin,I2C
import math
import time

device = const(0x53)
regAddress = const(0x32)
TO_READ = 6
buff = bytearray(6)

class ADXL345:
    def __init__(self,i2c,addr=device):
        self.addr = addr
        self.i2c = i2c
        b = bytearray(1)
        b[0] = 0
        self.i2c.writeto_mem(self.addr,0x2d,b)
        b[0] = 16
        self.i2c.writeto_mem(self.addr,0x2d,b)
        b[0] = 8
        self.i2c.writeto_mem(self.addr,0x2d,b)

    @property
    def xValue(self):
        buff = self.i2c.readfrom_mem(self.addr,regAddress,TO_READ)
        x = (int(buff[1]) << 8) | buff[0]
        if x > 32767:
            x -= 65536
        return x
   
    @property
    def yValue(self):
        buff = self.i2c.readfrom_mem(self.addr,regAddress,TO_READ)
        y = (int(buff[3]) << 8) | buff[2]
        if y > 32767:
            y -= 65536
        return y
     
    @property   
    def zValue(self): 
        buff = self.i2c.readfrom_mem(self.addr,regAddress,TO_READ)
        z = (int(buff[5]) << 8) | buff[4]
        if z > 32767:
            z -= 65536
        return z

    def read(self):
        """Read all three axes from one coherent six-byte sample."""
        data = self.i2c.readfrom_mem(self.addr, regAddress, TO_READ)
        values = []
        for offset in (0, 2, 4):
            value = (int(data[offset + 1]) << 8) | data[offset]
            if value > 32767:
                value -= 65536
            values.append(value)
        try:
            import smirror
            smirror.emit_accel(values[0], values[1], values[2])
        except Exception:
            pass
        return tuple(values)
           
    def RP_calculate(self,x,y,z):
        roll = math.atan2(y , z) * 57.3
        pitch = math.atan2((- x) , math.sqrt(y * y + z * z)) * 57.3
        return roll,pitch
 
