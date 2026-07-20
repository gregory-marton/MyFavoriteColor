
"""
File: standalone.py
Authors: Chris Rogers, Milan Dahal, Tanushree Burman
Modified By: Adin Lamport, Amanda-Lexine Sunga, Amanda Yan (Aug 2024)
             Ryan McLean, Milan Dahal (Jul 2025)
             Gregory Marton and Pinjie Lyu (w/Claude+Gemini) (Jul 2026) 
               to add "favorite color" calibration.
Purpose: MicroPython program to run Reinforcement Learning activity onto Smart Motors using Grove I2C color sensor v3
*** For Engineering with Artificial Intelligence Pre-College Program at Tufts University ***
"""

from machine import Pin, Timer, unique_id
from files import *
import time, ubinascii, urandom, math
import servo, icons, sensors
import machine, os, sys
import struct

########
# Students: Play with these first!

NUM_STATES = 7  # Number of distinct states.
EPISODES = 5   # Number of RL episodes to run.
TIMESTEPS = 15  # Maximum steps in each episode.
STATE_ANGLE_STEP = 0  # Degrees angle between adjacent states. Or 0 to use the pot.

# Q-learning parameters:
ALPHA = 0.1        # How much to trust new information.
GAMMA = 0.9        # Relative importance of the future vs. the present.
EPSILON = 0.1      # How much to explore randomly vs. exploit what we know.
MAX_REWARD = 100   # Maximum reward for exact color match

# Sensor settings:
IT_40MS   = (0b000 << 4)
IT_80MS   = (0b001 << 4)
IT_160MS  = (0b010 << 4)
IT_320MS  = (0b011 << 4)
IT_640MS  = (0b100 << 4)
IT_1280MS = (0b101 << 4)
COLOR_INTEGRATION_TIME = IT_640MS  # Enough time for the sensor to gather light.
# With 320 milliseconds or less, the R,G,B values tend to be much smaller than 
# the saturation values of 255,255,255.
WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)  # Our sensor doesn't detect blue well.
DISTANCE_METRIC = "Perceptual"  # Perceptual or Euclidean, see below.

# Hardware adjustments:
START_ANGLE = 180  # Starting motor position in degrees (state 0).
POT_THRESHOLD = 50  # * 180 degrees / 4096 pot states, so 50 is a touch over 2 degrees.
MOTOR_SETTLE_TIME = 2.0  # Seconds to wait for motor/sensor to stabilize

def dist_euclidean(c1, c2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

_PERCEPTUAL_WEIGHTS = (0.30, 0.59, 0.11)  # R, G, B
def dist_perceptual(c1, c2):
    return math.sqrt(sum(w * (a - b) ** 2 for w, a, b in zip(_PERCEPTUAL_WEIGHTS, c1, c2)))

DISTANCE_FUNCS = {
    "Perceptual": dist_perceptual,
    "Euclidean": dist_euclidean,
}

class VEML6040:    
    """VEML6040 RGBW Color Sensor Driver"""
    # VEML6040 I2C Peripheral Address and Registers
    VEML6040_I2C_ADDR = 0x10
    _VEML6040_REG_CONF    = 0x00
    _VEML6040_REG_R_DATA  = 0x08
    _VEML6040_REG_G_DATA  = 0x09
    _VEML6040_REG_B_DATA  = 0x0A
    _VEML6040_REG_W_DATA  = 0x0B

    # Configuration settings
    _SD_MASK   = 0x01
    _AF_MASK   = 0x02
    _TRIG_MASK = 0x04
    _IT_MASK   = 0x70

    def __init__(self, i2c, address=VEML6040_I2C_ADDR, integration_time=IT_160MS,
                 white_balance=(1.0, 1.0, 1.0)):
        self.i2c = i2c
        self.address = address
        self._current_conf = 0x0000
        self.white_balance = white_balance
        
        # Check if device is present
        devices = self.i2c.scan()
        if self.address not in devices:
            raise RuntimeError(f"VEML6040 sensor not found at address 0x{self.address:02X}")

        # Initialize sensor
        self.enable_sensor()
        self.set_integration_time(integration_time)
        self.set_auto_mode()
        time.sleep(0.2)

    def _read_word(self, register):
        try:
            data = self.i2c.readfrom_mem(self.address, register, 2)
            return struct.unpack('<H', data)[0]
        except OSError as e:
            print(f"Error reading from register 0x{register:02X}: {e}")
            raise

    def _write_word(self, register, value):
        try:
            data = struct.pack('<H', value)
            self.i2c.writeto_mem(self.address, register, data)
        except OSError as e:
            print(f"Error writing to register 0x{register:02X}: {e}")
            raise

    def set_integration_time(self, it_value):
        self._current_conf = (self._current_conf & ~self._IT_MASK) | (it_value & self._IT_MASK)
        self._write_word(VEML6040._VEML6040_REG_CONF, self._current_conf)

    def enable_sensor(self):
        self._current_conf &= (~self._SD_MASK)
        self._write_word(VEML6040._VEML6040_REG_CONF, self._current_conf)

    def set_auto_mode(self):
        self._current_conf &= (~self._AF_MASK)
        self._write_word(VEML6040._VEML6040_REG_CONF, self._current_conf)

    def read_rgbw(self):
        red = self._read_word(VEML6040._VEML6040_REG_R_DATA)
        green = self._read_word(VEML6040._VEML6040_REG_G_DATA)
        blue = self._read_word(VEML6040._VEML6040_REG_B_DATA)
        white = self._read_word(VEML6040._VEML6040_REG_W_DATA)
        return (red, green, blue, white)

    @property
    def rgb(self):
        """Read RGB values, normalize to 0-255, and apply white balance"""
        r, g, b, w = self.read_rgbw()
        r = min(255, r >> 6)
        g = min(255, g >> 6)
        b = min(255, b >> 6)
        wr, wg, wb = self.white_balance
        r = min(255, round(r * wr))
        g = min(255, round(g * wg))
        b = min(255, round(b * wb))
        return r, g, b

# Initialize sensor object
sens = sensors.SENSORS()

# Generate a unique ID for the device
ID = ubinascii.hexlify(machine.unique_id()).decode()

# Main loop flags
clearscreen = False

# Define servo, switches, and display
s = servo.Servo(Pin(2))
switch_down = Pin(8, Pin.IN)
switch_select = Pin(9, Pin.IN)
switch_up = Pin(10, Pin.IN)

# I2C interface and display
i2c = sensors.i2c
display = icons.SSD1306_SMART(128, 64, i2c, switch_up)
    

# Initialize VEML6040 sensor
try:
    sensor = VEML6040(i2c, integration_time=COLOR_INTEGRATION_TIME,
                       white_balance=WHITE_BALANCE_RGB)
    print("VEML6040 sensor initialized successfully!")
except Exception as e:
    print(f"Failed to initialize VEML6040: {e}")
    display.showmessage(f"Sensor Error! \n{e}")
    time.sleep(5) # Let the user actually see the error.
    raise

def displaybatt(p):
    batterycharge = sens.readbattery()
    display.showbattery(batterycharge)
    return batterycharge

def move_servo(angle):
    s.write_angle(angle)
    return angle

def update_motor_with_pot(last_pot_value, last_servo_angle):
    pot_value = sens.readpot()  # Returns 0-4095 (12-bit ADC)
    new_angle = last_servo_angle
    
    if abs(pot_value - last_pot_value) > POT_THRESHOLD:
        # Map potentiometer value to 0-180 degrees
        # ADC is 12-bit: 0-4095 corresponds to 0-3.3V
        new_angle = int((1 - (pot_value / 4095.0)) * START_ANGLE)
        new_angle = max(0, min(START_ANGLE, new_angle))  # Ensure within bounds
        new_angle = move_servo(new_angle)
    return pot_value, new_angle

def checkbuttons():
    if not switch_up.value():
        return "up"
    if not switch_down.value():
        return "down"
    if not switch_select.value():
        return "select"
    return None

def waitforbutton():
    chosen = None
    while not chosen:
        pressed = checkbuttons()
        while not pressed:
            time.sleep(0.05)
            pressed = checkbuttons()

        chosen = pressed
        while checkbuttons():
            time.sleep(0.05)
    return chosen

def screen(text):
    print("--\n"+"\n".join(text))
    display.fill(0)
    if len(text) > 5: # need to use the top line
        first = text.pop(0)
        display.text(first, 20, 0)
    x = 5
    y = 15
    for line in text:
        if len(line) > 16:
            display.text(line[:16], 0, y)
            line = line[17:]
            y += 10
        display.text(line, x, y)
        y += 10
    display.show()

# Q-Learning Agent Class
class QLearningAgent:
    def __init__(self, env, alpha=ALPHA, gamma=GAMMA, epsilon=EPSILON):
        self.env = env
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.qtable = self.initialize_qtable()
        self.actions = ["LEFT", "RIGHT"]
    
    def initialize_qtable(self):
        table = {}
        for key, val in enumerate(self.env.states):
            qvalue = [0] * 2
            table[val] = qvalue 
        return table

    def choose_action(self, state):
        k = urandom.uniform(0, 1)
        
        if self.epsilon > k:
            print("Random action chosen")
            action = urandom.choice(self.actions)
        else:
            actions = self.qtable[state]
            max_val = max(actions)
            indices = []
            for ind, val in enumerate(actions):
                if(val == max_val):
                    indices.append(ind)
            
            action = self.actions[urandom.choice(indices)]

        self.last_state = state
        self.last_action = self.actions.index(action)
        return action

    def learn(self, reward, next_state):
        predict = self.qtable[self.last_state][self.last_action]
        target = reward + self.gamma * max(self.qtable[next_state])
        self.qtable[self.last_state][self.last_action] += self.alpha * (target - predict)
        print(f'Reward: {reward}, Q-table: {self.qtable}')


# Environment Class
class Environment:
    def __init__(self, distance_metric="Perceptual"):
        self.action_space = ["LEFT", "RIGHT"]
        self.favorite_color = None
        self.distance_metric = distance_metric
        self.states = None
        self.colors = None
        self.distances = None
        self.rewards = None
        self.reset()
        self.calibrate_white_balance()
        self.capture_favorite_color()
        self.calibrate_states()

    def reset(self):
        self.state = 0
        self.angle = move_servo(START_ANGLE)
        return self.state

    def calibrate_white_balance(self):
        sensor.white_balance = (1.0, 1.0, 1.0)
        
        last_pot_value = sens.readpot()
        servo_angle = START_ANGLE
        while not checkbuttons():
            last_pot_value, servo_angle = update_motor_with_pot(
                last_pot_value, servo_angle)
            r, g, b = sensor.rgb
            screen(["Point at WHITE", "SELECT=ok"])
            time.sleep(0.05)
            
        while checkbuttons():
            time.sleep(0.05)
            
        r, g, b = sensor.rgb
        wr = 255.0 / max(1, r)
        wg = 255.0 / max(1, g)
        wb = 255.0 / max(1, b)
        
        sensor.white_balance = (wr, wg, wb)
        
        screen(["White Balance", "Saved!", f"R x{wr:.1f}", f"G x{wg:.1f}", f"B x{wb:.1f}"])
        time.sleep(1)

    
    def capture_favorite_color(self):
        """Point the sensor at any real-world object and press SELECT to lock in
        its color as the 'favorite color' that all rewards will be measured
        against. This is the very first step, before any state calibration.

        The potentiometer drives the servo live here (same absolute
        pot-to-angle mapping as pot mode in calibrate_states()), so the arm can
        be aimed at a specific spot -- e.g. a mark on a sheet of paper the
        device is mounted over -- before locking in the color underneath it.
        """
        self.favorite_color = (0, 0, 0)
        last_pot_value = sens.readpot()
        servo_angle = START_ANGLE
        while not checkbuttons():
            last_pot_value, servo_angle = update_motor_with_pot(
                last_pot_value, servo_angle)
            r, g, b = sensor.rgb
            self.favorite_color = (r, g, b)
            screen(["Set FAV color", f"R{r}, G{g}, B{b}", "", "SELECT=ok"])
            time.sleep(0.05)

    def calibrate_states(self):
        """Calibrate each state and its color. Manually if STATE_ANGLE_STEP is zero."""
        self.points = []
        self.colors = []
        self.rewards = []
        self.states = list(range(NUM_STATES))
        pot_mode = STATE_ANGLE_STEP == 0
        servo_angle = move_servo(START_ANGLE)
        screen(["Turn pot LEFT",
                "(c'ter-clock'w)",
                "Sensor on LEFT-",
                "-most color",
                "Then press sthg"])
        waitforbutton()

        for state in range(NUM_STATES):
            rgb = None
            if pot_mode:
                update_counter = 0
                last_pot_value = sens.readpot()
                while not checkbuttons():
                    last_pot_value, servo_angle = update_motor_with_pot(
                        last_pot_value, servo_angle)
                    rgb = sensor.rgb
                    d, reward = self.reward(rgb)
                    screen([f"{state=} @{servo_angle}",
                            f"R{rgb[0]} G{rgb[1]}, B{rgb[2]}",
                            f"{reward=}"])
            else:
                servo_angle = move_servo(servo_angle - STATE_ANGLE_STEP)
                time.sleep(MOTOR_SETTLE_TIME)
                rgb = sensor.rgb
                d, reward = self.reward(rgb)
                
            self.points.append(servo_angle)
            self.colors.append(rgb)
            self.rewards.append(reward)
            screen([f"Saved S{state} @{servo_angle}",
                    f"R{rgb[0]} G{rgb[1]}, B{rgb[2]}",
                    f"{reward=}"])
            time.sleep(0.5)
        # After all distances are known, recompute rewards to renorm by max_d:
        self.rewards = [self.reward(c)[1] for c in self.colors]

    def distance(self, color):
        return DISTANCE_FUNCS[self.distance_metric](self.favorite_color, color)
    
    def reward(self, color):
        """The current best guess at rewards. Stable after full calibration."""
        distances = [self.distance(c) for c in self.colors]
        max_d = max(distances) if distances and max(distances) > 0 else 1
        d = self.distance(color)
        r = round(MAX_REWARD * (1 - d / max_d))
        return d, r

    def step(self, action):
        if action == self.action_space[0]:  # LEFT
            self.state = max(0, self.state - 1)
        elif action == self.action_space[1]:  # RIGHT
            self.state = min(len(self.points)-1, self.state + 1)
        new_angle = self.points[self.state]
        move_servo(new_angle)
        time.sleep(MOTOR_SETTLE_TIME)
        reward = self.rewards[self.state]
        done = reward == MAX_REWARD
        return self.state, reward, done
        
def main():
    global batt
    batt.deinit()
    batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)
    
    # 2-second startup delay escape hatch
    display.fill(0)
    display.text("Starting in 2s...", 10, 20)
    display.text("Press UP to REPL", 10, 40)
    display.show()
    
    start_time = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start_time) < 2000:
        if not switch_up.value():
            print("Auto-run aborted by user. Exiting to REPL.")
            display.fill(0)
            display.text("Aborted to REPL", 10, 25)
            display.show()
            sys.exit()
        time.sleep(0.05)
        
    display.welcomemessage()
    
    env = Environment(DISTANCE_METRIC)
    agent = QLearningAgent(env)
    rewards_history = []
    timesteps = []
    screen(["Rewards=",
            ",".join(map(lambda r: str(round(r)),env.rewards)),
            "Press to start"," training."])
    waitforbutton()
    for episode in range(EPISODES):
        env.reset()
        total_episode_reward = 0
        max_episode_time = 0
        
        for e_t in range(TIMESTEPS):
            max_episode_time = e_t
            q_map = [f"{a} Q={agent.qtable[env.state][i]}"
                         for i, a in enumerate(env.action_space)]
            action = agent.choose_action(env.state)
            new_state, reward, done = env.step(action)
            update = f"Next state: {new_state} r={reward}"
            if done:
                update = "Goal!"
            screen([f"E={episode} T={e_t}",
                    f"S={env.state} R={env.rewards[env.state]}"] +
                    q_map + [f"Chosen: {action}", update])
            agent.learn(reward, new_state)
            if done:
                total_episode_reward += MAX_REWARD * (TIMESTEPS - e_t)
                time.sleep(1)
                break
            else:
                total_episode_reward += reward

        rewards_history.append(total_episode_reward)
        timesteps.append(max_episode_time)

        screen([f"Episode {episode} done",
                f"Reward: {total_episode_reward}",
                f"Steps: {max_episode_time}",
                "Press to continue."])
        waitforbutton()

    # Display grand total reward at the end of training
    screen(["Training Complete",
            f"Total={sum(rewards_history)}:",
            f"{rewards_history}"])

# Initialize timer objects globally (uninitialized)
batt = Timer(1)

if __name__ == "__main__":
    main()

