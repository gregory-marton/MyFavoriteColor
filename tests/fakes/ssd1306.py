class SSD1306_I2C:
    def __init__(self, width, height, i2c):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.history = []

    def fill(self, color):
        self.history.append(("fill", color))

    def text(self, text, x, y, color=1):
        self.history.append(("text", text, x, y, color))

    def show(self):
        self.history.append("show")
