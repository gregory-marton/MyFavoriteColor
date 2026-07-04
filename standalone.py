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

from machine import Pin, SoftI2C, Timer, unique_id
from files import *
import time, ubinascii, urandom, math
import servo, icons, sensors
import machine, os, sys
import struct

########
# Students: Play with these first!

NUM_STATES = 7  # Number of distinct states.
START_ANGLE = 180  # Starting motor position in degrees (state 0).
STATE_ANGLE_STEP = 20  # Degrees angle between adjacent states.
MOTOR_SETTLE_TIME = 2.0  # Seconds to wait for motor/sensor to stabilize
EPISODES = 10   # Number of RL episodes to run.
TIMESTEPS = 15  # Number of steps in each episode.

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

def dist_euclidean(c1, c2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

_PERCEPTUAL_WEIGHTS = (0.30, 0.59, 0.11)  # R, G, B
def dist_perceptual(c1, c2):
    return math.sqrt(sum(w * (a - b) ** 2 for w, a, b in zip(_PERCEPTUAL_WEIGHTS, c1, c2)))

DISTANCE_FUNCS = {
    "Perceptual": dist_perceptual,
    "Euclidean": dist_euclidean,
}

def compute_state_rewards(state_colors, favorite_color, distance_fn, max_reward=MAX_REWARD):
    distances = [distance_fn(c, favorite_color) for c in state_colors]
    max_d = max(distances) if max(distances) > 0 else 1
    rewards = [round(max_reward * (1 - d / max_d)) for d in distances]
    return rewards, distances

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

# Get the number of icons for each screen
numberofIcons = [len(icons.iconFrames[i]) for i in range(len(icons.iconFrames))]
highlightedIcon = []
for numberofIcon in numberofIcons:
    highlightedIcon.append([0, numberofIcon])

# Initialize variables
screenID = 1
lastPressed = 0
previousIcon = 0
filenumber = 0
currentlocaltime = 0
oldlocaltime = 0

# Lists to hold measured rgb values and state configuration
points = []
state_colors = []  # Store colors for each state during setup
num_states_configured = 0

# Define all flags
flags = [False, False, False, False, False]
playFlag = False
triggered = False
LOGGING = True
calibration_mode = True  # Start in calibration mode

# Switch states and flags
switch_state_up = False
switch_state_down = False
switch_state_select = False
last_switch_state_up = False
last_switch_state_down = False
last_switch_state_select = False
switched_up = False
switched_down = False
switched_select = False

# Main loop flags
clearscreen = False

# Define servo, switches, and display
s = servo.Servo(Pin(2))
switch_down = Pin(8, Pin.IN)
switch_select = Pin(9, Pin.IN)
switch_up = Pin(10, Pin.IN)

# I2C interface and display
i2c = SoftI2C(scl=Pin(7), sda=Pin(6), freq=100000)
display = icons.SSD1306_SMART(128, 64, i2c, switch_up)

# Initialize VEML6040 sensor
try:
    sensor = VEML6040(i2c, integration_time=COLOR_INTEGRATION_TIME,
                       white_balance=WHITE_BALANCE_RGB)
    print("VEML6040 sensor initialized successfully!")
except Exception as e:
    print(f"Failed to initialize VEML6040: {e}")
    display.showmessage("Sensor Error!")
    raise

# Button handling functions
def downpressed(count=-1):
    global playFlag, triggered
    playFlag = False
    time.sleep(0.05)
    if time.ticks_ms() - lastPressed > 200:
        displayselect(count)
    triggered = True

def uppressed(count=1):
    global playFlag, triggered
    playFlag = False
    time.sleep(0.05)
    if time.ticks_ms() - lastPressed > 200:
        displayselect(count)
    triggered = True

def displayselect(selectedIcon):
    global screenID, highlightedIcon, lastPressed, previousIcon
    highlightedIcon[screenID][0] = (highlightedIcon[screenID][0] + selectedIcon) % highlightedIcon[screenID][1]
    display.selector(screenID, highlightedIcon[screenID][0], previousIcon)
    previousIcon = highlightedIcon[screenID][0]
    lastPressed = time.ticks_ms()

def selectpressed():
    global flags, triggered
    time.sleep(0.05)
    flags[highlightedIcon[screenID][0]] = True    
    triggered = True

def resettohome():
    global screenID, highlightedIcon, previousIcon, clearscreen
    screenID = 0
    previousIcon = 0
    for numberofIcon in numberofIcons:
        highlightedIcon.append([0, numberofIcon])
    display.selector(screenID, highlightedIcon[screenID][0], 0)
    clearscreen = True

def check_switch(p):
    global switch_state_up, switch_state_down, switch_state_select
    global switched_up, switched_down, switched_select
    global last_switch_state_up, last_switch_state_down, last_switch_state_select
    
    switch_state_up = switch_up.value()
    switch_state_down = switch_down.value()
    switch_state_select = switch_select.value()
         
    if switch_state_up != last_switch_state_up:
        switched_up = True
    elif switch_state_down != last_switch_state_down:
        switched_down = True
    elif switch_state_select != last_switch_state_select:
        switched_select = True
                
    if switched_up:
        if switch_state_up == 0:
            uppressed()
        switched_up = False
    elif switched_down:
        if switch_state_down == 0:
            downpressed()
        switched_down = False
    elif switched_select:
        if switch_state_select == 0:
            selectpressed()
        switched_select = False
    
    last_switch_state_up = switch_state_up
    last_switch_state_down = switch_state_down
    last_switch_state_select = switch_state_select

def displaybatt(p):
    batterycharge = sens.readbattery()
    display.showbattery(batterycharge)
    # Disabled logging during RL activity to prevent interference
    # if LOGGING:
    #     # Log current state information
    #     current_point = []
    #     if len(points) > 0:
    #         try:
    #             # Get current RGB reading
    #             r, g, b = sensor.rgb
    #             current_point = [r, g, b]
    #         except:
    #             current_point = [0, 0, 0]
    #     try:
    #         savetolog(time.time(), screenID, highlightedIcon, current_point, points)
    #     except Exception as e:
    #         print(f"Warning: Could not save to log: {e}")
    return batterycharge

def resetflags():
    global flags
    for i in range(len(flags)):
        flags[i] = False

def shakemotor(point):
    motorpos = point[1]
    for i in range(2):
        s.write_angle(min(180, motorpos + 5))
        time.sleep(0.1)
        s.write_angle(max(0, motorpos - 5))
        time.sleep(0.1)

def setloggingmode():
    # Default to logging enabled
    log_enabled = True
    
    try:
        if not switch_down.value() and not switch_up.value() and not switch_select.value():
            try:
                resetlog()
                setprefs()
            except:
                print("Warning: Could not reset log files")
            display.showmessage("LOG: ON")
            print("resetting the log file")
            log_enabled = True
            
        if not switch_down.value() and not switch_up.value() and switch_select.value():
            try:
                resetprefs()
            except:
                print("Warning: Could not reset preferences")
            print("turn OFF the logging")
            display.showmessage("LOG: OFF")
            log_enabled = False

        if switch_down.value() and switch_up.value() and switch_select.value():
            print("default: turn ON the logging")
            log_enabled = True
            
        # Try to import prefs module and get log setting
        try:
            import prefs
            if hasattr(prefs, 'log'):
                log_enabled = prefs.log
        except ImportError:
            print("Warning: prefs module not found, using default logging setting")
        except AttributeError:
            print("Warning: prefs.log attribute not found, using default logging setting")
            
    except Exception as e:
        print(f"Error in setloggingmode: {e}")
        
    return log_enabled

# Q-Learning Agent Class
class QLearningAgent:
    def __init__(self, env, alpha=ALPHA, gamma=GAMMA, epsilon=EPSILON): # Student TODO: Try changing alpha and gamma
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
    def __init__(self, points, index, favorite_color=None, distance_metric="Perceptual"):
        self.states = dict(zip(index, points))
        self.favorite_color = favorite_color
        self.distance_metric = distance_metric
        
        if favorite_color is not None:
            distance_fn = DISTANCE_FUNCS[self.distance_metric]
            self.state_rewards, self.state_distances = compute_state_rewards(points, favorite_color, distance_fn)
            self.highest_reward_state = self.state_rewards.index(max(self.state_rewards))
            self.goal_state = [self.highest_reward_state]
            print(f"Highest reward state: State {self.highest_reward_state}")
        else:
            self.state_rewards = None
            self.goal_state = [len(points) - 1]
            self.highest_reward_state = len(points) - 1
            
        self.end_state = [0, len(index)-1]
        self.current_state = None
        self.action_space = ["LEFT", "RIGHT"]
        self.current_angle = START_ANGLE
        self.angle = STATE_ANGLE_STEP

    def reset(self):
        # Reset to starting position
        self.current_angle = START_ANGLE
        s.write_angle(self.current_angle)
        time.sleep(MOTOR_SETTLE_TIME)
        self.current_state = self.nearestNeighbor(sensor.rgb)
        return self.current_state 

    def reset_cur_angle(self, reset_angle):
        self.current_angle = reset_angle

    def distance(self, color1, color2):
        return DISTANCE_FUNCS[self.distance_metric](color1, color2)

    def nearestNeighbor(self, current_rgb):
        closest_color = None
        min_distance = float('inf')
    
        for color_name, color_value in self.states.items():
            distance = self.distance(current_rgb, color_value)
            if distance < min_distance:
                min_distance = distance
                closest_color = color_name

        print("The closest color is:", closest_color)
        return closest_color

    def step(self, action):
        if action == self.action_space[0]:  # LEFT (decrease angle - move right physically)
            if self.current_angle > 0:
                self.current_angle = max(0, self.current_angle - self.angle)
                s.write_angle(self.current_angle)
            time.sleep(MOTOR_SETTLE_TIME)
        elif action == self.action_space[1]:  # RIGHT (increase angle - move left physically)
            self.current_angle = min(START_ANGLE, self.current_angle + self.angle)
            s.write_angle(self.current_angle)
            time.sleep(MOTOR_SETTLE_TIME)

        self.current_state = self.nearestNeighbor(sensor.rgb)

        if self.state_rewards is not None:
            reward = self.state_rewards[self.current_state]
            done = (self.current_state == self.highest_reward_state)
        else:
            if self.current_state in self.goal_state:
                reward = 10
                done = True
            else:
                reward = -1
                done = False

        return self.current_state, reward, done


POT_THRESHOLD = 2  # degrees; potentiometer change threshold to trigger update

def capture_favorite_color():
    """Point the sensor at any real-world object and press SELECT to lock in
    its color as the 'favorite color' that all rewards will be measured
    against. This is the very first step, before any state calibration.

    The potentiometer drives the servo live here (same absolute
    pot-to-angle mapping as pot mode in calibrate_states()), so the arm can
    be aimed at a specific spot -- e.g. a mark on a sheet of paper the
    device is mounted over -- before locking in the color underneath it.
    """
    display.fill(0)
    display.text("Favorite Color", 10, 5)
    display.text("POT=aim arm", 15, 20)
    display.text("SELECT=lock in", 10, 50)
    display.show()

    while not switch_select.value() or not switch_up.value() or not switch_down.value():
        time.sleep(0.05)

    last_shown = None
    last_pot_angle = -1
    pot_threshold = POT_THRESHOLD
    servo_angle = 180

    while True:
        pot_value = sens.readpot()
        new_angle = int((pot_value / 4095.0) * 180)
        new_angle = max(0, min(180, new_angle))
        if abs(new_angle - last_pot_angle) > pot_threshold:
            servo_angle = new_angle
            s.write_angle(servo_angle)
            last_pot_angle = servo_angle

        r, g, b = sensor.rgb
        if (r, g, b) != last_shown:
            display.fill(0)
            display.text("Favorite Color", 10, 5)
            display.text(f"RGB:{r},{g},{b}", 10, 20)
            display.text(f"Angle: {servo_angle}", 10, 35)
            display.text("SELECT=lock in", 10, 50)
            display.show()
            last_shown = (r, g, b)

        if not switch_select.value():
            r, g, b = sensor.rgb
            display.fill(0)
            display.text("Locked in!", 20, 15)
            display.text(f"RGB:{r},{g},{b}", 10, 35)
            display.show()
            time.sleep(1.5)
            while not switch_select.value():
                time.sleep(0.05)
            return (r, g, b)

        time.sleep(0.05)


# State calibration function
def calibrate_states(target_num_states=None):
    """Allow user to set up states by pressing button at each position"""
    global state_colors, num_states_configured, flags
    
    # Clear any pending flags
    resetflags()
    
    display.fill(0)
    display.text("State Setup", 20, 20)
    display.show()
    time.sleep(2)
    
    state_colors = []
    current_position = 0
    button_pressed = False
    servo_angle = START_ANGLE  # Start at starting angle (reversed)
    ANGLE_INCREMENT = 20  # 20 degrees between states
    pot_mode = True  # Toggle for potentiometer control
    last_pot_angle = -1  # Track last pot angle to reduce updates
    pot_threshold = POT_THRESHOLD
    
    # First, let's read a pot value to understand the range
    initial_pot = sens.readpot()
    print(f"Initial pot reading: {initial_pot}")
    
    print("Starting state calibration...")
    display.fill(0)
    display.text(f"State {current_position}", 30, 5)
    display.text("SELECT=save", 20, 20)
    display.text("UP=next/-20", 15, 30)
    display.text("DWN=finish/POT", 15, 40)
    display.text(f"Angle: {servo_angle}", 20, 50)
    display.show()
    
    # Move to starting position
    s.write_angle(servo_angle)
    time.sleep(2)
    
    # Wait for all buttons to be released first
    while not switch_select.value() or not switch_up.value() or not switch_down.value():
        time.sleep(0.05)
    
    update_counter = 0  # Counter to reduce display updates
    
    while True:
        # Read potentiometer for fine control if in pot mode
        if pot_mode:
            update_counter += 1
            pot_value = sens.readpot()  # Returns 0-4095 (12-bit ADC)
            
            # Map potentiometer value to 0-180 degrees
            # ADC is 12-bit: 0-4095 corresponds to 0-3.3V
            new_angle = int((pot_value / 4095.0) * 180)
            new_angle = max(0, min(180, new_angle))  # Ensure within bounds
            
            # Only update servo if angle changed significantly
            if abs(new_angle - last_pot_angle) > pot_threshold:
                servo_angle = new_angle
                s.write_angle(servo_angle)
                last_pot_angle = servo_angle
                print(f"Pot value: {pot_value}, Angle: {servo_angle}")
            
            # Update display immediately on entry, then less frequently to reduce flicker
            if update_counter == 1 or update_counter % 10 == 0:  # Update every 10 loops
                r, g, b = sensor.rgb
                
                # Update display with pot control
                display.fill(0)
                display.text(f"State {current_position}", 30, 5)
                display.text("POT CONTROL", 25, 15)
                display.text("SELECT=save", 20, 25)
                display.text("DWN=exit POT", 20, 35)
                display.text(f"Angle: {servo_angle}", 20, 45)
                display.text(f"RGB: {r},{g},{b}", 15, 55)
                display.show()
        
        # Only process if no button is currently pressed (debouncing)
        if switch_select.value() and switch_up.value() and switch_down.value():
            button_pressed = False
        
        # Check for button presses only if no button was previously pressed
        if not button_pressed:
            if not switch_select.value():  # Select button pressed - save current state
                button_pressed = True
                r, g, b = sensor.rgb
                state_colors.append([r, g, b])
                print(f"State {current_position} saved: RGB({r}, {g}, {b}) at angle {servo_angle}")
                
                display.fill(0)
                display.text(f"Saved S{current_position}", 20, 15)
                display.text(f"RGB:{r},{g},{b}", 10, 30)
                display.text(f"Angle: {servo_angle}", 10, 45)
                display.show()
                time.sleep(1.5)
                
                current_position += 1
                if target_num_states is not None and current_position >= target_num_states:
                    print(f"Calibration complete. {len(state_colors)} states configured.")
                    display.fill(0)
                    display.text(f"{len(state_colors)} states set", 20, 20)
                    display.text("Starting RL...", 15, 35)
                    display.show()
                    time.sleep(2)
                    num_states_configured = len(state_colors)
                    return state_colors
                pot_mode = True  # Exit pot mode after saving
                update_counter = 0  # Reset counter
                
                # Show next state screen
                display.fill(0)
                display.text(f"State {current_position}", 30, 5)
                display.text("SELECT=save", 20, 20)
                display.text("UP=next/-20", 15, 30)
                display.text("DWN=finish/POT", 15, 40)
                display.text(f"Angle: {servo_angle}", 20, 50)
                display.show()
                
            elif not switch_down.value() and not pot_mode:  # DOWN button - move servo
                button_pressed = True
                # Move servo to next position (decreasing angle)
                servo_angle = max(0, servo_angle - ANGLE_INCREMENT)
                print(f"Moving servo to angle {servo_angle}")
                s.write_angle(servo_angle)
                time.sleep(1)
                
                # Update display
                display.fill(0)
                display.text(f"State {current_position}", 30, 5)
                display.text("SELECT=save", 20, 20)
                display.text("UP=next/-20", 15, 30)
                display.text("DWN=finish/POT", 15, 40)
                display.text(f"Angle: {servo_angle}", 20, 50)
                display.show()
                
            elif not switch_up.value():  # UP button - toggle pot mode or finish
                button_pressed = True
                if len(state_colors) >= 2:  # If we have enough states, ask to finish
                    # Show finish confirmation
                    display.fill(0)
                    display.text("Finish setup?", 15, 10)
                    display.text(f"{len(state_colors)} states", 25, 25)
                    display.text("DOWN=YES", 30, 40)
                    display.text("UP=NO/POT", 20, 50)
                    display.show()
                    
                    # Wait for button release
                    while not switch_up.value():
                        time.sleep(0.05)
                    time.sleep(0.2)
                    
                    # Wait for confirmation
                    confirm_wait = 0
                    while confirm_wait < 30:  # 3 second timeout
                        if not switch_up.value():  # Confirmed finish
                            print(f"Calibration complete. {len(state_colors)} states configured.")
                            display.fill(0)
                            display.text(f"{len(state_colors)} states set", 20, 20)
                            display.text("Starting RL...", 15, 35)
                            display.show()
                            time.sleep(2)
                            num_states_configured = len(state_colors)
                            print(f"Calibration complete. States: {state_colors}")
                            return state_colors
                        elif not switch_down.value():  # Cancel - enter pot mode
                            pot_mode = True
                            last_pot_angle = servo_angle
                            update_counter = 0
                            break
                        time.sleep(0.1)
                        confirm_wait += 1
                    
                    # If timeout or canceled, continue
                    if confirm_wait >= 30:
                        pot_mode = False
                else:
                    # Toggle pot mode if not enough states
                    pot_mode = not pot_mode
                    if pot_mode:
                        print("Entering potentiometer control mode")
                        last_pot_angle = servo_angle
                        update_counter = 0
                    else:
                        print("Exiting potentiometer control mode")
        
        time.sleep(0.05)  # Small delay to prevent excessive CPU usage

def main():
    global calibration_mode, state_colors, points, flags, tim, batt, favorite_color, LOGGING
    
    # Clear display and start fresh
    display.fill(0)
    display.show()
    time.sleep(0.5)
    
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
        
    # Initialize welcome message and logging state
    display.welcomemessage()
    LOGGING = setloggingmode()
    
    # Temporarily disable the timers during calibration
    tim.deinit()
    batt.deinit()
    
    # Setup and calibration loop
    while True:
        if calibration_mode:
            print("Starting calibration mode...")
            display.fill(0)
            display.text("RL Color Sensor", 10, 10)
            display.text("Calibration", 20, 25)
            display.text("Press any btn", 15, 45)
            display.show()
            
            # Wait for any button press to start
            while switch_up.value() and switch_down.value() and switch_select.value():
                time.sleep(0.05)
            time.sleep(0.5)  # Debounce
            
            # Capture favorite color
            favorite_color = capture_favorite_color()
            
            display.fill(0)
            display.text("Instructions:", 10, 5)
            display.text("SELECT=save color", 5, 20)
            display.text("DOWN=move servo", 5, 30)  # Flipped
            display.text("UP=start RL", 5, 40)      # Flipped
            display.text("Press to begin", 10, 55)
            display.show()
            
            # Wait for button release and press
            while not switch_up.value() or not switch_down.value() or not switch_select.value():
                time.sleep(0.05)
            while switch_up.value() and switch_down.value() and switch_select.value():
                time.sleep(0.05)
            time.sleep(0.5)
            
            points = calibrate_states(NUM_STATES)
            calibration_mode = False
        
        # Create environment with calibrated states
        numStates = len(points)
        indices = [i for i in range(0, numStates)]
        env = Environment(points, indices, favorite_color, DISTANCE_METRIC)
        
        # Configure goal state and confirm screen
        display.fill(0)
        display.text("Ready to train", 10, 5)
        display.text(f"States: {numStates}", 10, 20)
        display.text(f"Goal: State {env.highest_reward_state}", 10, 35)
        display.text("SEL=start UP=redo", 5, 50)
        display.show()
        
        # Wait for button release first
        while not switch_up.value() or not switch_select.value():
            time.sleep(0.05)
        time.sleep(0.1)
        
        # Wait for selection
        chosen = None
        while chosen is None:
            if not switch_select.value():
                chosen = "start"
            elif not switch_up.value():
                chosen = "redo"
            time.sleep(0.05)
            
        if chosen == "start":
            while not switch_select.value():
                time.sleep(0.05)
            time.sleep(0.5)
            break
        else:
            calibration_mode = True
            while not switch_up.value():
                time.sleep(0.05)
            time.sleep(0.5)
            
    # Re-enable the timers after calibration
    tim.init(period=50, mode=Timer.PERIODIC, callback=check_switch)
    batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)
    
    # Q-Learning parameters
    EPSILON = 0.1 # Student TODO: Try changing the Q learning Values
    agent = QLearningAgent(env, epsilon=EPSILON)
    
    rewards_history = []
    timesteps = []

    # Student TODO: Try changing these values at the top of the file
    # (EPISODES and TIMESTEPS are module-level constants)
    
    for i in range(EPISODES):
        display.fill(0)
        display.text(f"Episode {i}", 30, 20)
        display.text("Press to run", 20, 40)
        display.show()
        print(f"EPISODE {i}... Press button to start")
        
        # Clear flags and wait for button press
        resetflags()
        while switch_up.value() and switch_down.value() and switch_select.value():
            time.sleep(0.05)
        
        time.sleep(1)
        rew = 0
        ti = 0
        print(f"Episode {i} Beginning...")
        state = env.reset()
        
        for j in range(TIMESTEPS):
            print(f"TIMESTEP {j}")
            print(f"- Current State: {env.states[state]}")
            action = agent.choose_action(state)
            print(f"- Action chosen: {action}")
            new_state, reward, done = env.step(action)
            print(f"- New State: {env.states[new_state]}")
            print(f"- Reward: {reward}")
            
            # Update display with real-time training step details
            display.fill(0)
            display.text(f"Ep {i} Step {j}", 10, 5)
            display.text(f"State: {state}", 10, 20)
            display.text(f"Act: {action}", 10, 35)
            display.text(f"Rew: {reward}", 10, 50)
            display.show()
            
            agent.learn(reward, new_state)
            rew += reward
            state = new_state
            ti += 1
            
            if done:
                print("Goal State reached!")
                display.fill(0)
                display.text("Goal reached!", 20, 30)
                display.show()
                time.sleep(2)
                break
        
        # Reset to starting position
        s.write_angle(START_ANGLE)
        env.reset_cur_angle(START_ANGLE)
        
        rewards_history.append(rew)
        timesteps.append(ti)
        
        print(f"- Episode {i} Reward total: {rew}")
        print(f"- Rewards History: {rewards_history}")
        print(f"- Timesteps History: {timesteps}")
        
        display.fill(0)
        display.text(f"Episode {i} done", 15, 10)
        display.text(f"Reward: {rew}", 10, 25)
        display.text(f"Steps: {ti}", 10, 40)
        display.show()
        time.sleep(3)
        
        resetflags()

# Initialize timer objects globally (uninitialized)
tim = Timer(0)
batt = Timer(1)
LOGGING = True

if __name__ == "__main__":
    main()

