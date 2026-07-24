
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
import time, ubinascii, random, urandom, math
import servo, icons, sensors
import machine, os, sys
import struct

########
# Students: Play with these first!

NUM_STATES = 7  # Number of distinct states.
EPISODES = 5   # Number of RL episodes to run.
TIMESTEPS = 20  # Maximum steps in each episode.
START_STATE = None # None for random choice or state number, e.g. 0.
STATE_ANGLE_STEP = 0  # Degrees angle between adjacent states. Or 0 to use the pot.

# Q-learning parameters:
ALPHA = 0.1        # How much to trust new information.
GAMMA = 0.95       # Relative importance of the future vs. the present.
EPSILON = 0.9      # How much to explore randomly vs. exploit what we know (at first)
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
DISTANCE_METRIC = "Sine"  # Perceptual or Euclidean, see below.

# Hardware adjustments:
START_ANGLE = 180  # Starting motor position in degrees (state 0).
POT_THRESHOLD = 50  # * 180 degrees / 4096 pot states, so 50 is a touch over 2 degrees.
MOTOR_SETTLE_TIME = 1  # Seconds to wait for motor/sensor to stabilize

def dist_euclidean(c1, c2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

_PERCEPTUAL_WEIGHTS = (0.30, 0.59, 0.11)  # R, G, B
def dist_perceptual_euclidean(c1, c2):
    return math.sqrt(sum(w * (a - b) ** 2 for w, a, b in zip(_PERCEPTUAL_WEIGHTS, c1, c2)))

# Cosine and Sine are magnitude-agnostic, so they only pay attention to hue,
# not to brightness. 1-cosine is quadratically similar when hues are close.
def dist_cosine(c1, c2):
    dot = sum(a * b for a, b in zip(c1, c2))
    mag1 = math.sqrt(sum(a ** 2 for a in c1))
    mag2 = math.sqrt(sum(b ** 2 for b in c2))
    if mag1 == 0 or mag2 == 0:
        return 1.0
    # Cosine similarity is 1.0 for perfect match. Return 1 - sim so 0 is a match
    return 1.0 - (dot / (mag1 * mag2))

# Cosine and Sine are magnitude-agnostic, so they only pay attention to hue,
# not to brightness. Sine is linear where hues are close.
def dist_sine(c1, c2):
    dot = sum(a * b for a, b in zip(c1, c2))
    mag1 = math.sqrt(sum(a ** 2 for a in c1))
    mag2 = math.sqrt(sum(b ** 2 for b in c2))
    if mag1 == 0 or mag2 == 0:
        return 1.0
    # Clamp to avoid floating point errors where sim > 1.0
    sim = min(1.0, dot / (mag1 * mag2))
    # Return the sine of the angle: sqrt(1 - cos^2)
    return math.sqrt(1 - sim**2)


DISTANCE_FUNCS = {
    "Perceptual": dist_perceptual_euclidean,
    "Euclidean": dist_euclidean,
    "Cosine": dist_cosine,
    "Sine": dist_sine,
}

THEORETICAL_MAX_DIST = {
    "Euclidean": 255 * math.sqrt(3),
    "Perceptual": 255.0,   # since weights sum to 1
    "Sine": 1.0,
    "Cosine": 1.0,
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
global last_servo_angle
last_servo_angle = 0

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

def compact_num(n):
    """1-2 digit numbers as-is; 3+ digit numbers to ~1 sig fig with a suffix.
    100s -> 'h' (300 -> '3h'), 1000s -> 'k' (4000 -> '4k'),
    10000s -> 'k' with 2 digits (20327 -> '20k')."""
    sign = "-" if n < 0 else ""
    n = abs(n)

    if n < 100:
        return f"{sign}{n}"
    elif n < 950:
        return f"{sign}{round(n / 100)}h"
    elif n < 950000:
        return f"{sign}{round(n / 1000)}k"
    else:
        return f"{sign}{round(n / 1000000)}m"

last_screen=[]
def screen(text):
    CHRW = 16
    global last_screen
    if text != last_screen:
        print("--\n"+"\n".join(text))
    last_screen = text[:]
    display.fill(0)
    if len(text) > 5: # need to use the top line
        first = text.pop(0)
        display.text(first, 20, 0)
    x = 5
    y = 15
    for line in text:
        while len(line) > CHRW:
            display.text(line[:CHRW], 0, y)
            line = line[CHRW:]
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
        self.actions = ["LEFT", "STAY", "RIGHT"]
        self.qtable = self.initialize_qtable()
    
    def initialize_qtable(self):
        table = {}
        for key, val in enumerate(self.env.states):
            # Optimistic initialization encourages exploration by starting
            # Q values at their maximum possible until we learn different.
            # qvalue = [MAX_REWARD/(1 - GAMMA)] * len(self.actions)

            # Pessimistic initialization encourages early stability:
            qvalue = [0] * len(self.actions)
            
            table[val] = qvalue 
        return table

    def choose_action(self, state):
        k = urandom.uniform(0, 1)
        was_random = False
        if self.epsilon > k:
            was_random = True
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
        return action, was_random

    def learn(self, reward, next_state):
        predict = self.qtable[self.last_state][self.last_action]
        target = reward + self.gamma * max(self.qtable[next_state])
        self.qtable[self.last_state][self.last_action] += self.alpha * (target - predict)
        #print(f'Reward: {reward}, Q-table: {self.qtable}')


# Environment Class
class Environment:
    def __init__(self, distance_metric="Perceptual"):
        self.action_space = ["LEFT", "STAY", "RIGHT"]
        self.favorite_color = None
        self.distance_metric = distance_metric
        self.states = None
        self.colors = None
        self.distances = None
        self.rewards = None
        self.settle_time = MOTOR_SETTLE_TIME
        self.calibrate_white_balance()
        self.capture_favorite_color()
        self.calibrate_states()
        self.compute_rewards()
        self.reset()

    def reset(self):
        self.state = random.choice(range(NUM_STATES)) if START_STATE is None else START_STATE
        global last_servo_angle
        last_servo_angle = move_servo(self.points[self.state])
        return self.state

    def recalibrate_favorite_color(self):
        """Re-run favorite-color capture only. Keeps white balance and
        state calibration (self.points/self.colors) untouched."""
        self.capture_favorite_color()
        self.compute_rewards()
        self.reset()
    
    def calibrate_white_balance(self):
        global last_servo_angle
        sensor.white_balance = (1.0, 1.0, 1.0)
        
        last_pot_value = sens.readpot()
        while not checkbuttons():
            last_pot_value, last_servo_angle = update_motor_with_pot(
                last_pot_value, last_servo_angle)
            r, g, b = sensor.rgb
            screen(["Point at WHITE",
                    f"Angle: {last_servo_angle}",
                    "SELECT=ok"])
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
        global last_servo_angle
        self.favorite_color = (0, 0, 0)
        last_pot_value = sens.readpot()
        while not checkbuttons():
            last_pot_value, last_servo_angle = update_motor_with_pot(
                last_pot_value, last_servo_angle)
            r, g, b = sensor.rgb
            self.favorite_color = (r, g, b)
            screen(["Set FAV color", f"R{r}, G{g}, B{b}",
                    f"Angle: {last_servo_angle}", "SELECT=ok"])
            time.sleep(0.05)
        while checkbuttons(): # debounce: wait for release
            time.sleep(0.05)
    
    def calibrate_states(self):
        """Calibrate each state and its color. Manually if STATE_ANGLE_STEP is zero."""
        self.points = []
        self.colors = []
        self.rewards = []
        self.states = list(range(NUM_STATES))
        pot_mode = STATE_ANGLE_STEP == 0
        global last_servo_angle
        last_servo_angle = move_servo(START_ANGLE)
        for state in range(NUM_STATES):
            rgb = None
            reward = None
            if pot_mode:
                last_pot_value = sens.readpot()
                while not checkbuttons():
                    last_pot_value, last_servo_angle = update_motor_with_pot(
                        last_pot_value, last_servo_angle)
                    rgb = sensor.rgb
                    reward = round(MAX_REWARD * (1 - self.distance(rgb)))
                    screen([f"{state=} @{last_servo_angle}",
                            f"R{rgb[0]} G{rgb[1]}, B{rgb[2]}",
                            f"{reward=}"])
            else:
                if self.settle_time > 0:
                    last_servo_angle = move_servo(last_servo_angle - STATE_ANGLE_STEP)
                    time.sleep(self.settle_time)
                rgb = sensor.rgb
                reward = round(MAX_REWARD * (1 - self.distance(rgb)))
                
            self.points.append(last_servo_angle)
            self.colors.append(rgb)
            self.rewards.append(reward)
            screen([f"Saved S{state} @{last_servo_angle}",
                    f"R{rgb[0]} G{rgb[1]}, B{rgb[2]}",
                    f"{reward=}"])
            time.sleep(0.5)
        if 0.1 > (max(self.points) - min(self.points)):
            # For playing with large values of EPISODES and TIMESTEPS
            # without waiting for the servo or causing it significant wear:
            # Take the arm off the SmartMotor, point it by hand during
            # calibration, at no time touch the pot. We're saving the
            # color values during calibration and reusing them, so no need
            # for actual arm movement during training.
            self.settle_time = 0
        if EPISODES * TIMESTEPS > 180: # Would take >3m.
            self.settle_time = 0
            
    def compute_rewards(self):
        """Recompute self.rewards from already-calibrated self.colors,
        against the current self.favorite_color."""
        distances = [self.distance(c) for c in self.colors]
        max_d = max(distances) if distances and max(distances) > 0 else 1
        self.rewards = [round(MAX_REWARD * (1 - self.distance(c) / max_d))
                            for c in self.colors]
        
    def distance(self, color):
        PEAKINESS = 1  # <1 is peaky so fav color is sharper, >1 flattens
        d = (DISTANCE_FUNCS[self.distance_metric](self.favorite_color, color)
             / THEORETICAL_MAX_DIST[self.distance_metric])
        return d ** PEAKINESS

    def step(self, action):
        if action == self.action_space[0]:  # LEFT
            self.state = max(0, self.state - 1)
        elif action == self.action_space[1]: # STAY
            pass # keep the current state.
        elif action == self.action_space[2]:  # RIGHT
            self.state = min(len(self.points)-1, self.state + 1)
        new_angle = self.points[self.state]
        if self.settle_time > 0:
            move_servo(new_angle)
            time.sleep(self.settle_time)
        reward = self.rewards[self.state]
        return self.state, reward

def learn(env):
    agent = QLearningAgent(env)
    rewards_history = []
    timesteps = []
    rewards_string = ",".join(map(lambda r: str(round(r)),env.rewards))
    screen(["Rewards=", rewards_string,
            "Press to start"," training."])
    waitforbutton()
    policy = "" # keep the last-built policy string
    total_reward_by_state = [0] * NUM_STATES
    for episode in range(EPISODES):
        env.reset()
        EPSILON_FLOOR = 0.1
        agent.epsilon = max(EPSILON_FLOOR, EPSILON * (1 - 1.*episode/EPISODES))
        total_episode_reward = 0
        max_episode_time = 0
        state_rewards = {s: [] for s in range(NUM_STATES)}
        state_rewards[env.state].append(env.rewards[env.state])
        
        for e_t in range(TIMESTEPS):
            max_episode_time = e_t
            state = env.state
            q_map = [f"{a[0]}{compact_num(int(agent.qtable[state][i]))}"
                         for i, a in enumerate(env.action_space)]
            action, was_random = agent.choose_action(state)
            action_str = action
            if was_random:
                action_str += "*"
            new_state, reward = env.step(action)
            state_rewards[new_state].append(reward)
            total_reward_by_state[new_state] += reward
            update = f"Next:{new_state} r={reward}"
            screen([f"E={episode} T={e_t} e={agent.epsilon:.2f}",
                    f"S={state} R={env.rewards[state]}",
                    " ".join(q_map),
                    f"Chosen: {action_str}",
                    update])
            agent.learn(reward, new_state)
            total_episode_reward += reward

        rewards_history.append(total_episode_reward)
        timesteps.append(max_episode_time)

        # Build Q-table policy string
        policy = ""
        for s in range(NUM_STATES):
            left_q = agent.qtable[s][0]
            stay_q = agent.qtable[s][1]
            right_q = agent.qtable[s][2]
            if left_q > stay_q and left_q > right_q:
                policy += "<"
            elif stay_q > left_q and stay_q > right_q:
                policy += "v"
            elif right_q > left_q and right_q > stay_q:
                policy += ">"
            elif left_q == stay_q and stay_q == right_q:
                policy += "o"
            elif left_q == stay_q:
                policy += "["
            elif right_q == stay_q:
                policy += "]"
            elif left_q == right_q:
                policy += "X"
            else:
                policy += "-"  # Equal (unexplored)

        # Build average rewards string
        rwds_per_state = []
        for s in range(NUM_STATES):
            if state_rewards[s]:
                rwds_per_state.append(compact_num(sum(state_rewards[s])))
            else:
                rwds_per_state.append("_")
        rewards_map = "R=" + ",".join(rwds_per_state)
        screen([f"E{episode} St={max_episode_time} R={compact_num(total_episode_reward)}",
                f"Rewards: {rewards_map}",
                f"Policy: {policy}",
                "SELECT=next"])
        waitforbutton()

    # Display grand total reward at the end of training
    screen([f"End! Score={compact_num(sum(rewards_history))}",
            f"{list(map(compact_num, rewards_history))}".replace(" ", ""),
                policy, rewards_string])
    tastiest = max(enumerate(total_reward_by_state), key=lambda x: x[1])[0]
    move_servo(env.points[tastiest])
    time.sleep(5)
    env.recalibrate_favorite_color()
    learn(env)

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
            screen(["Auto-run aborted by user. Exiting to REPL."])
            sys.exit()
        time.sleep(0.05)
        
    display.welcomemessage()
    
    env = Environment(DISTANCE_METRIC)
    learn(env)
    
# Initialize timer objects globally (uninitialized)
batt = Timer(1)

if __name__ == "__main__":
    main()

