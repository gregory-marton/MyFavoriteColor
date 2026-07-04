"""
File: standalone.py
Authors: Chris Rogers, Milan Dahal, Tanushree Burman
Modified By: Adin Lamport, Amanda-Lexine Sunga, Amanda Yan (Aug 2024)
             Ryan McLean, Milan Dahal (Jul 2025)
Purpose: MicroPython program to run Reinforcement Learning activity onto Smart Motors using Grove I2C color sensor v3
*** For Engineering with Artificial Intelligence Pre-College Program at Tufts University ***
"""

from machine import Pin, SoftI2C, Timer, unique_id
from files import *
import time, ubinascii, urandom, math
import servo, icons, sensors
import machine, os, sys
import struct

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

IT_40MS   = (0b000 << 4)
IT_80MS   = (0b001 << 4)
IT_160MS  = (0b010 << 4)
IT_320MS  = (0b011 << 4)
IT_640MS  = (0b100 << 4)
IT_1280MS = (0b101 << 4)

class VEML6040:
    """VEML6040 RGBW Color Sensor Driver"""
    
    def __init__(self, i2c, address=VEML6040_I2C_ADDR):
        self.i2c = i2c
        self.address = address
        self._current_conf = 0x0000
        
        # Check if device is present
        devices = self.i2c.scan()
        if self.address not in devices:
            raise RuntimeError(f"VEML6040 sensor not found at address 0x{self.address:02X}")

        # Initialize sensor
        self.enable_sensor()
        self.set_integration_time(IT_160MS)
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
        self._current_conf = (self._current_conf & ~_IT_MASK) | (it_value & _IT_MASK)
        self._write_word(_VEML6040_REG_CONF, self._current_conf)

    def enable_sensor(self):
        self._current_conf &= (~_SD_MASK)
        self._write_word(_VEML6040_REG_CONF, self._current_conf)

    def set_auto_mode(self):
        self._current_conf &= (~_AF_MASK)
        self._write_word(_VEML6040_REG_CONF, self._current_conf)

    def read_rgbw(self):
        red = self._read_word(_VEML6040_REG_R_DATA)
        green = self._read_word(_VEML6040_REG_G_DATA)
        blue = self._read_word(_VEML6040_REG_B_DATA)
        white = self._read_word(_VEML6040_REG_W_DATA)
        return (red, green, blue, white)

    @property
    def rgb(self):
        """Read RGB values and normalize to 0-255 range"""
        r, g, b, w = self.read_rgbw()
        # Normalize to 8-bit values (0-255)
        # Adjust these scaling factors based on your sensor's typical output
        r = min(255, r >> 6)  # Divide by 64
        g = min(255, g >> 6)
        b = min(255, b >> 6)
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
    sensor = VEML6040(i2c)
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
    def __init__(self, env, alpha=0.1, gamma=0.9, epsilon=0.1): # Student TODO: Try changing alpha and gamma
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
    def __init__(self, points, index): # Student TODO: Try changing/adding new rewards
        self.states = dict(zip(index, points))
        self.goal_state = [len(points) - 1]  # Last state is goal
        self.end_state = [0, len(index)-1]
        self.reward_default = -1
        self.reward_goal = 10
        self.current_state = None
        self.action_space = ["LEFT", "RIGHT"]
        self.current_angle = 180  # Start at 180 degrees (reversed)
        self.angle = 20  # Fixed 20 degrees between states

    def reset(self):
        # Reset to first state position (180 degrees)
        self.current_angle = 180
        s.write_angle(self.current_angle)
        time.sleep(2)
        self.current_state = self.nearestNeighbor(sensor.rgb)
        return self.current_state 

    def reset_cur_angle(self, reset_angle):
        self.current_angle = reset_angle

    def euclidean_distance(self, color1, color2):
        return math.sqrt(sum((c1 - c2) ** 2 for c1, c2 in zip(color1, color2)))

    def nearestNeighbor(self, current_rgb):
        closest_color = None
        min_distance = float('inf')
    
        for color_name, color_value in self.states.items():
            distance = self.euclidean_distance(current_rgb, color_value)
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
            time.sleep(2)
        elif action == self.action_space[1]:  # RIGHT (increase angle - move left physically)
            self.current_angle = min(180, self.current_angle + self.angle)
            s.write_angle(self.current_angle)
            time.sleep(2)

        self.current_state = self.nearestNeighbor(sensor.rgb)

        if self.current_state in self.goal_state:
            reward = self.reward_goal
            done = True
        else:
            reward = self.reward_default
            done = False

        return self.current_state, reward, done

# State calibration function
def calibrate_states():
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
    servo_angle = 180  # Start at 180 degrees (reversed)
    ANGLE_INCREMENT = 20  # 20 degrees between states
    pot_mode = True  # Toggle for potentiometer control
    last_pot_angle = -1  # Track last pot angle to reduce updates
    pot_threshold = 2  # Only update if angle changes by more than this
    
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
            
            # Update display less frequently to reduce flicker
            if update_counter % 10 == 0:  # Update every 10 loops
                # Calculate voltage for display
                voltage = (pot_value / 4095.0) * 3.3
                
                # Update display with pot control
                display.fill(0)
                display.text(f"State {current_position}", 30, 5)
                display.text("POT CONTROL", 25, 15)
                display.text("SELECT=save", 20, 25)
                display.text("DWN=exit POT", 20, 35)
                display.text(f"Angle: {servo_angle}", 20, 45)
                display.text(f"V: {voltage:.2f}V", 20, 55)
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
    global calibration_mode, state_colors, points, flags, tim, batt
    
    # Temporarily disable the timers during calibration
    tim.deinit()
    batt.deinit()
    
    # Clear display and start fresh
    display.fill(0)
    display.show()
    time.sleep(0.5)
    
    # Calibration phase
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
        
        points = calibrate_states()
        calibration_mode = False
    
    # Re-enable the timers after calibration
    tim.init(period=50, mode=Timer.PERIODIC, callback=check_switch)
    batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)
    
    # Create environment with calibrated states
    numStates = len(points)
    indices = [i for i in range(0, numStates)]
    env = Environment(points, indices)
    
    # Configure goal state
    display.fill(0)
    display.text("RL Training", 20, 10)
    display.text(f"States: {numStates}", 20, 25)
    display.text(f"Goal: State {numStates-1}", 10, 40)
    display.text("Press to start", 10, 55)
    display.show()
    
    # Wait for button press to start training
    while switch_up.value() and switch_down.value() and switch_select.value():
        time.sleep(0.05)
    time.sleep(0.5)
    
    # Q-Learning parameters
    EPSILON = 0.1 # Student TODO: Try changing the Q learning Values
    agent = QLearningAgent(env, epsilon=EPSILON)
    
    rewards_history = []
    timesteps = []

    # Student TODO: Try changing these values
    EPISODES = 10
    TIMESTEPS = 15
    
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
        
        # Reset to start position (180 degrees)
        s.write_angle(180)
        env.reset_cur_angle(180)
        
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

# Initialize timers (moved to after sensor initialization)
tim = Timer(0)
batt = Timer(1)

# Display welcome message
display.welcomemessage()
LOGGING = setloggingmode()

# Initialize timers AFTER welcome message
tim.init(period=50, mode=Timer.PERIODIC, callback=check_switch)
# Increase battery check interval to reduce sensor reads
batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)  # Changed from 3000ms to 10000ms

# Don't show homescreen selector - go straight to main
# Clear display and go to calibration
display.fill(0)
display.show()
main()
