# Fake icons module for testing

# Represents icon frames for screen navigation in the legacy code
# It's a list of lists of frames. Here we provide 5 dummy frames for screens.
iconFrames = [
    [None, None, None],
    [None, None, None],
    [None, None, None],
    [None, None, None],
    [None, None, None]
]

class SSD1306_SMART:
    def __init__(self, w, h, i2c, switch_up):
        self.w = w
        self.h = h
        self.i2c = i2c
        self.switch_up = switch_up
        self.buffer = []       # stores (text, x, y, color)
        self.messages = []     # stores showmessage calls
        self.history = []      # stores all drawn text
        self.battery_charge = None
        self.cleared = False

    def welcomemessage(self):
        self.messages.append("welcome")

    def showmessage(self, msg):
        self.messages.append(msg)

    def fill(self, color):
        self.buffer = []
        self.cleared = (color == 0)

    def fill_rect(self, x, y, w, h, color):
        # Remove any text that falls within this rectangle to simulate visual clear/overwrite
        self.buffer = [
            t for t in self.buffer
            if not (x <= t[1] < x + w and y <= t[2] < y + h)
        ]

    def text(self, text, x, y, color=1):
        self.buffer.append((text, x, y, color))
        self.history.append(text)

    def show(self):
        pass

    def showbattery(self, charge):
        self.battery_charge = charge
