"""
File: standalone.py
Authors: Chris Rogers, Milan Dahal, Tanushree Burman
Modified By: Adin Lamport, Amanda-Lexine Sunga, Amanda Yan (Aug 2024)
             Ryan McLean, Milan Dahal (Jul 2025)
             Gregory (Jul 2026) -- "Favorite Color" RL redesign:
                - Capture a real-world "favorite color" before calibration
                - Reward derived automatically from color distance to favorite
                  (perceptual-weighted or plain Euclidean, student-selectable)
                - Student-selectable fixed-length episodes, number of states,
                  and settings screen generally, so reward "valleys" can be
                  built physically in the environment
                - Live reward readout on screen whenever the arm is stationary
Purpose: MicroPython program to run Reinforcement Learning activity onto Smart
         Motors using Grove I2C color sensor v3
*** For Engineering with Artificial Intelligence Pre-College Program at Tufts University ***
"""

from machine import Pin, SoftI2C, Timer
import time, urandom, math
import servo, icons, sensors
import struct

# ============================================================================
# VEML6040 I2C Peripheral Address and Registers
# ============================================================================
VEML6040_I2C_ADDR = 0x10
_VEML6040_REG_CONF    = 0x00
_VEML6040_REG_R_DATA  = 0x08
_VEML6040_REG_G_DATA  = 0x09
_VEML6040_REG_B_DATA  = 0x0A
_VEML6040_REG_W_DATA  = 0x0B

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
    """VEML6040 RGBW Color Sensor Driver.

    NOTE ON SENSOR PORTABILITY: the rest of this program (distance functions,
    reward computation, live display) only ever calls `.rgb`, which must
    return a roughly-0..255 (R, G, B) tuple. If you swap in a different color
    sensor, write a driver exposing that same `.rgb` property and nothing
    else in this file needs to change -- the reward math is self-normalizing
    (see compute_state_rewards) and doesn't hardcode this sensor's raw range.
    """

    def __init__(self, i2c, address=VEML6040_I2C_ADDR, integration_time=IT_160MS,
                 white_balance=(1.0, 1.0, 1.0)):
        self.i2c = i2c
        self.address = address
        self._current_conf = 0x0000
        self.white_balance = white_balance

        devices = self.i2c.scan()
        if self.address not in devices:
            raise RuntimeError(f"VEML6040 sensor not found at address 0x{self.address:02X}")

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
        """Read RGB values, normalize to roughly 0-255, and apply white
        balance (see WHITE_BALANCE_RGB) to correct for this sensor's
        weaker blue-channel sensitivity."""
        r, g, b, w = self.read_rgbw()
        r = min(255, r >> 6)
        g = min(255, g >> 6)
        b = min(255, b >> 6)
        wr, wg, wb = self.white_balance
        r = min(255, round(r * wr))
        g = min(255, round(g * wg))
        b = min(255, round(b * wb))
        return r, g, b


# ============================================================================
# Color distance functions (student-selectable at runtime)
# ============================================================================
# Both operate on plain (r, g, b) tuples in roughly 0-255 range, so they work
# with any sensor driver exposing `.rgb` in that convention -- no sensor-
# specific constants live here.
#
# DIST_PERCEPTUAL uses ITU-R BT.601-style luma weights as a stand-in for true
# perceptual distance. To upgrade to CIE Lab / delta-E later: write an
# rgb_to_lab() conversion and a dist_delta_e() function with the same
# signature (c1, c2) -> float, then add it to DISTANCE_FUNCS below. Nothing
# else in the program needs to change.

_PERCEPTUAL_WEIGHTS = (0.30, 0.59, 0.11)  # R, G, B


def dist_euclidean(c1, c2):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def dist_perceptual(c1, c2):
    return math.sqrt(sum(w * (a - b) ** 2 for w, a, b in zip(_PERCEPTUAL_WEIGHTS, c1, c2)))


DISTANCE_FUNCS = {
    "Perceptual": dist_perceptual,
    "Euclidean": dist_euclidean,
}
DISTANCE_FUNC_NAMES = list(DISTANCE_FUNCS.keys())  # preserves insertion order on MicroPython


def compute_state_rewards(state_colors, favorite_color, distance_fn, max_reward=200):
    """Turn calibrated state colors into rewards, purely from color distance
    to the favorite color. Self-normalizing: whatever calibrated state is
    furthest from the favorite color becomes ~0 reward, whatever is closest
    becomes ~max_reward. No sensor-specific constants -- works the same
    whether raw values are 0-255, 0-4095, or anything else, as long as the
    sensor driver's `.rgb` is internally consistent.
    """
    distances = [distance_fn(c, favorite_color) for c in state_colors]
    max_d = max(distances) if max(distances) > 0 else 1
    rewards = [round(max_reward * (1 - d / max_d)) for d in distances]
    return rewards, distances


# ============================================================================
# STUDENT-EDITABLE SETTINGS
# ============================================================================
# Change these values and re-upload to adjust the activity. Each is
# explained below. You do NOT edit anything else in this file to tune the
# experiment -- just these constants.

# How many arm positions ("states") the agent can be in. During setup you
# will aim the arm and press SELECT once for each of these positions.
NUM_STATES = 5

# How many moves the agent makes per episode before the episode ends. This
# is the key knob for the "reward valley" idea: with a short episode, a
# high-reward state that's far away (across low-reward territory) may not be
# worth reaching -- or even reachable -- so the agent settles for a closer,
# lower peak. Longer episodes let it justify the trip. Try values from ~4
# up to ~3x NUM_STATES.
EPISODE_LENGTH = 10

# How color distance is measured when turning "how far is this from my
# favorite color" into a reward. "Perceptual" weights green more than red
# or blue (closer to how human eyes work); "Euclidean" treats all three
# channels equally. Must be exactly one of those two strings.
DISTANCE_METRIC = "Perceptual"

# Seconds to wait after the arm moves before reading the color sensor, so
# the reading isn't taken mid-swing. Increase if the arm is slow or wobbly.
SETTLE_TIME = 2.0

# How many training episodes to run when you press SELECT to start.
EPISODES = 10

# Color sensor exposure time. If RGB readings look too dark (e.g. reading
# under 40 for a bright white object -- check by watching the live RGB
# readout during calibration), increase this. Options, darkest/fastest to
# brightest/slowest: IT_40MS, IT_80MS, IT_160MS, IT_320MS, IT_640MS,
# IT_1280MS. Keep SETTLE_TIME above this value, or readings may be taken
# before a fresh measurement cycle has finished.
COLOR_INTEGRATION_TIME = IT_640MS

# Correction for this sensor's uneven color response -- the blue channel
# reads noticeably weaker than red/green for the same physical light, so
# a truly neutral gray/white surface comes out looking yellowish without
# this fix. To re-derive for your own sensor/lighting: point it at
# something you know is neutral white or gray, read the raw (r, g, b) via
# the live RGB readout during calibration, then set each gain to
# max(r, g, b) / that channel's value (so the strongest channel keeps
# gain 1.0 and the others are boosted up to match it).
WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)

# ============================================================================
# Sensor + display + actuator setup
# ============================================================================
sens = sensors.SENSORS()

# Favorite color + calibrated state data
favorite_color = None       # (r, g, b) captured before calibration
state_colors = []           # RGB reading at each calibrated state
state_angles = []           # servo angle at each calibrated state
state_rewards = []          # reward computed from distance to favorite_color
state_distances = []        # raw distance values, kept for debug/display

# Tracks whether the servo is mid-move, so the live-reward poller avoids
# reading the color sensor while the arm is still travelling/settling.
motor_moving = False

s = servo.Servo(Pin(2))
switch_down = Pin(8, Pin.IN)
switch_select = Pin(9, Pin.IN)
switch_up = Pin(10, Pin.IN)

i2c = SoftI2C(scl=Pin(7), sda=Pin(6), freq=100000)
display = icons.SSD1306_SMART(128, 64, i2c, switch_up)

try:
    sensor = VEML6040(i2c, integration_time=COLOR_INTEGRATION_TIME,
                       white_balance=WHITE_BALANCE_RGB)
    print("VEML6040 sensor initialized successfully!")
except Exception as e:
    print(f"Failed to initialize VEML6040: {e}")
    display.showmessage("Sensor Error!")
    raise


def move_servo(angle, settle=None):
    """Centralized servo move so we can flag motor_moving around it and use
    the student-configurable settle time everywhere instead of a hardcoded
    sleep scattered through the file.
    """
    global motor_moving
    if settle is None:
        settle = SETTLE_TIME
    motor_moving = True
    s.write_angle(angle)
    time.sleep(settle)
    motor_moving = False


def displaybatt(p):
    batterycharge = sens.readbattery()
    display.showbattery(batterycharge)
    return batterycharge


# ============================================================================
# Live reward readout
# ============================================================================
# Polls the color sensor and shows the current distance-derived "reward" the
# arm would receive right now if it were a calibrated state. Only reads while
# the motor is stationary (motor_moving is False) to avoid hammering I2C
# during a servo move and to avoid showing meaningless in-transit readings.
_live_reward_row = 56  # bottom row of the 64px-tall display, out of the way
                        # of other screen content


def live_reward_tick(p):
    if motor_moving:
        return
    if favorite_color is None:
        return
    try:
        rgb = sensor.rgb
        distance_fn = DISTANCE_FUNCS[DISTANCE_METRIC]
        d = distance_fn(rgb, favorite_color)
        # Normalize against the current calibration's own max distance if we
        # have one, else just show raw distance.
        if state_distances:
            max_d = max(state_distances) if max(state_distances) > 0 else 1
        else:
            max_d = 255  # rough fallback before any calibration exists
        reward_now = max(0, round(200 * (1 - d / max_d)))
        display.fill_rect(0, _live_reward_row, 128, 8, 0)
        display.text(f"Now: R={reward_now}", 0, _live_reward_row, 1)
        display.show()
    except Exception as e:
        # Don't let a transient I2C hiccup take down the periodic timer
        print(f"live_reward_tick error: {e}")


# ============================================================================
# Q-Learning Agent
# ============================================================================
class QLearningAgent:
    def __init__(self, env, alpha=0.1, gamma=0.9, epsilon=0.1):
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
                if (val == max_val):
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


# ============================================================================
# Environment
# ============================================================================
class Environment:
    def __init__(self, points, index, state_angles, state_rewards, highest_reward_state, second_highest_reward_state):
        self.states = dict(zip(index, points))
        self.state_angles = state_angles
        self.state_rewards = state_rewards
        self.start_state = 0
        self.highest_reward_state = highest_reward_state
        self.second_highest_reward_state = second_highest_reward_state
        self.end_state = [0, len(index) - 1]
        self.current_state = None
        self.action_space = ["LEFT", "RIGHT"]
        self.current_angle = self.state_angles[self.start_state]
        print(f"Highest reward state: State {self.highest_reward_state}")
        print(f"Second-highest reward state: State {self.second_highest_reward_state}")
        print("Episode ends when the highest reward state is reached, or when the timestep limit is reached.")
        print(f"Start state: {self.start_state}")

    def reset(self):
        self.current_angle = self.state_angles[self.start_state]
        move_servo(self.current_angle)
        self.current_state = self.nearestNeighbor(sensor.rgb)
        print(f"Episode reset to State {self.start_state} at angle {self.current_angle}")
        return self.current_state

    def reset_cur_angle(self, reset_angle):
        self.current_angle = reset_angle

    def distance(self, color1, color2):
        return DISTANCE_FUNCS[DISTANCE_METRIC](color1, color2)

    def nearestNeighbor(self, current_rgb):
        closest_color = None
        min_distance = float('inf')

        for color_name, color_value in self.states.items():
            distance = self.distance(current_rgb, color_value)
            if distance < min_distance:
                min_distance = distance
                closest_color = color_name

        return closest_color

    def step(self, action, episode=None, timestep=None):
        previous_state = self.current_state

        if action == self.action_space[0]:  # LEFT
            target_state = max(0, previous_state - 1)
        elif action == self.action_space[1]:  # RIGHT
            target_state = min(len(self.state_angles) - 1, previous_state + 1)
        else:
            target_state = previous_state

        target_angle = self.state_angles[target_state]
        self.current_angle = target_angle
        move_servo(self.current_angle)

        self.current_state = self.nearestNeighbor(sensor.rgb)
        reward = self.state_rewards[self.current_state]
        done = False

        if self.current_state == self.highest_reward_state:
            done = True

        print(f"E{episode} T{timestep}: s{previous_state} --{action}--> s{target_state} "
              f"(angle {target_angle}), sensed s{self.current_state}, reward {reward}"
              f"{', DONE' if done else ''}")

        return self.current_state, reward, done


# ============================================================================
# Favorite color capture
# ============================================================================
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
    pot_threshold = 2  # degrees; matches calibrate_states()'s pot-mode throttle
    servo_angle = s.angle if hasattr(s, "angle") else 90

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


# ============================================================================
# State calibration
# ============================================================================
def calibrate_states(target_num_states):
    """Allow user to set up states by pressing button at each position.
    Colors are recorded per state but NOT turned into rewards here --
    reward computation happens afterward, once, from distance to
    favorite_color (see compute_state_rewards).
    """
    global state_colors, state_angles

    display.fill(0)
    display.text("State Setup", 20, 20)
    display.text(f"Target: {target_num_states} states", 5, 35)
    display.show()
    time.sleep(2)

    state_colors = []
    state_angles = []
    current_position = 0
    button_pressed = False
    servo_angle = 180
    ANGLE_INCREMENT = 20
    pot_mode = True
    last_pot_angle = -1
    pot_threshold = 2

    initial_pot = sens.readpot()
    print(f"Initial pot reading: {initial_pot}")

    print("Starting state calibration...")
    display.fill(0)
    display.text(f"State {current_position}/{target_num_states}", 20, 5)
    display.text("SELECT=save", 20, 20)
    display.text("UP=pot on/off", 12, 30)
    display.text("DWN=nudge -20", 12, 40)
    display.text(f"Angle: {servo_angle}", 20, 50)
    display.show()

    move_servo(servo_angle)

    while not switch_select.value() or not switch_up.value() or not switch_down.value():
        time.sleep(0.05)

    update_counter = 0

    while True:
        if pot_mode:
            update_counter += 1
            pot_value = sens.readpot()
            new_angle = int((pot_value / 4095.0) * 180)
            new_angle = max(0, min(180, new_angle))

            if abs(new_angle - last_pot_angle) > pot_threshold:
                servo_angle = new_angle
                s.write_angle(servo_angle)  # live drag, not a discrete "move" -- no settle wait
                last_pot_angle = servo_angle
                print(f"Pot value: {pot_value}, Angle: {servo_angle}")

            if update_counter % 10 == 0:
                r, g, b = sensor.rgb
                display.fill(0)
                display.text(f"State {current_position}/{target_num_states}", 15, 5)
                display.text("POT CONTROL", 25, 15)
                display.text("SELECT=save", 20, 25)
                display.text("UP=exit POT", 20, 35)
                display.text(f"Angle: {servo_angle}", 20, 45)
                display.text(f"RGB:{r},{g},{b}", 10, 55)
                display.show()

        if switch_select.value() and switch_up.value() and switch_down.value():
            button_pressed = False

        if not button_pressed:
            if not switch_select.value():  # SELECT - save current state
                button_pressed = True
                r, g, b = sensor.rgb
                state_colors.append([r, g, b])
                state_angles.append(servo_angle)
                print(f"State {current_position} saved: RGB({r}, {g}, {b}) at angle {servo_angle}")

                display.fill(0)
                display.text(f"Saved S{current_position}", 20, 15)
                display.text(f"RGB:{r},{g},{b}", 10, 30)
                display.text(f"Angle: {servo_angle}", 10, 45)
                display.show()
                time.sleep(1.5)

                current_position += 1
                pot_mode = True
                update_counter = 0

                if current_position >= target_num_states:
                    print(f"Reached target of {target_num_states} states.")
                    display.fill(0)
                    display.text(f"{len(state_colors)} states set", 15, 25)
                    display.show()
                    time.sleep(1.5)
                    return state_colors

                display.fill(0)
                display.text(f"State {current_position}/{target_num_states}", 15, 5)
                display.text("SELECT=save", 20, 20)
                display.text("UP=next/-20", 15, 30)
                display.text("DWN=finish/POT", 15, 40)
                display.text(f"Angle: {servo_angle}", 20, 50)
                display.show()

            elif not switch_down.value() and not pot_mode:  # DOWN - move servo
                button_pressed = True
                servo_angle = max(0, servo_angle - ANGLE_INCREMENT)
                print(f"Moving servo to angle {servo_angle}")
                move_servo(servo_angle)

                r, g, b = sensor.rgb
                display.fill(0)
                display.text(f"State {current_position}/{target_num_states}", 15, 5)
                display.text("SELECT=save", 20, 20)
                display.text("UP=next/-20", 15, 30)
                display.text(f"Angle: {servo_angle}", 20, 40)
                display.text(f"RGB:{r},{g},{b}", 10, 52)
                display.show()

            elif not switch_up.value():  # UP - toggle potentiometer drag mode
                button_pressed = True
                pot_mode = not pot_mode
                if pot_mode:
                    print("Entering potentiometer control mode")
                    last_pot_angle = servo_angle
                    update_counter = 0
                else:
                    print("Exiting potentiometer control mode")

        time.sleep(0.05)


def full_setup(target_num_states):
    """Runs the complete favorite-color capture + state calibration +
    reward computation sequence. Used both for the very first setup and
    whenever the settings menu triggers a recalibration.
    """
    global favorite_color, state_colors, state_angles, state_rewards, state_distances

    favorite_color = capture_favorite_color()
    print(f"Favorite color captured: RGB{favorite_color}")

    calibrate_states(target_num_states)

    if len(state_colors) < 2 or len(state_angles) != len(state_colors):
        print("ERROR: Calibration data incomplete.")
        display.fill(0)
        display.text("Calib error", 20, 20)
        display.text("Check console", 15, 40)
        display.show()
        return False

    distance_fn = DISTANCE_FUNCS[DISTANCE_METRIC]
    state_rewards, state_distances = compute_state_rewards(state_colors, favorite_color, distance_fn)

    print("Calibration complete. States:")
    for i, (rgb, angle, reward, dist) in enumerate(zip(state_colors, state_angles, state_rewards, state_distances)):
        print(f"- State {i}: RGB{tuple(rgb)}, angle {angle}, distance {dist:.1f}, reward {reward}")

    return True


# ============================================================================
# Settings menu
# ============================================================================
# Confirm screen (start vs. recalibrate)
# ============================================================================
def _wait_release():
    while not switch_select.value() or not switch_up.value() or not switch_down.value():
        time.sleep(0.05)


def _favorite_color_state_index():
    """Which calibrated state is closest to the favorite color -- shown on
    the confirm screen so students can sanity-check calibration."""
    if not state_colors or favorite_color is None:
        return None
    distance_fn = DISTANCE_FUNCS[DISTANCE_METRIC]
    dists = [distance_fn(c, favorite_color) for c in state_colors]
    return dists.index(min(dists))


def confirm_screen():
    """Show a summary and wait for the student to choose. Returns True to
    start training, or False to recalibrate (favorite color + all states).
    SELECT starts; UP recalibrates."""
    fav_idx = _favorite_color_state_index()
    display.fill(0)
    display.text("Ready to train", 5, 0)
    if fav_idx is not None:
        display.text(f"Fav ~ State {fav_idx}", 5, 14)
    display.text(f"States:{len(state_colors)} Ep:{EPISODE_LENGTH}", 5, 28)
    display.text(DISTANCE_METRIC, 5, 42)
    display.text("SEL=go  UP=redo", 5, 56)
    display.show()

    _wait_release()
    while True:
        if not switch_select.value():
            _wait_release()
            return True
        if not switch_up.value():
            _wait_release()
            return False
        time.sleep(0.05)


# ============================================================================
# Main
# ============================================================================
def main():
    global state_colors, state_angles, state_rewards, batt, live_tim

    batt.deinit()
    live_tim.deinit()

    display.fill(0)
    display.show()
    time.sleep(0.5)

    print("Starting setup (favorite color + calibration)...")
    display.fill(0)
    display.text("Favorite Color RL", 5, 10)
    display.text("Setup", 45, 25)
    display.text("Press any btn", 15, 45)
    display.show()

    while switch_up.value() and switch_down.value() and switch_select.value():
        time.sleep(0.05)
    time.sleep(0.5)

    if not full_setup(NUM_STATES):
        return

    # Confirm screen: SELECT starts training, UP recalibrates (redo favorite
    # color + all states). Loop until the student chooses to start.
    while not confirm_screen():
        if not full_setup(NUM_STATES):
            return

    numStates = len(state_colors)
    if numStates < 2 or len(state_angles) != numStates:
        print("ERROR: Calibration data incomplete; cannot start RL training.")
        display.fill(0)
        display.text("Calib error", 20, 20)
        display.text("Check console", 15, 40)
        display.show()
        return

    batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)
    live_tim.init(period=300, mode=Timer.PERIODIC, callback=live_reward_tick)

    indices = [i for i in range(0, numStates)]
    highest_reward_state = state_rewards.index(max(state_rewards))
    remaining = [(i, r) for i, r in enumerate(state_rewards) if i != highest_reward_state]
    second_highest_reward_state = max(remaining, key=lambda pair: pair[1])[0] if remaining else highest_reward_state

    env = Environment(state_colors, indices, state_angles, state_rewards,
                       highest_reward_state, second_highest_reward_state)

    display.fill(0)
    display.text("RL Training", 20, 10)
    display.text(f"States: {numStates}", 20, 25)
    display.text(f"High: State {highest_reward_state}", 10, 40)
    display.text("Press to start", 10, 55)
    display.show()

    while switch_up.value() and switch_down.value() and switch_select.value():
        time.sleep(0.05)
    time.sleep(0.5)

    print("Initializing fresh Q-table for current reward function.")
    agent = QLearningAgent(env, epsilon=0.1)

    rewards_history = []
    timesteps = []

    for i in range(EPISODES):
        display.fill(0)
        display.text(f"Episode {i}", 30, 20)
        display.text("Press to run", 20, 40)
        display.show()
        print(f"EPISODE {i}... Press button to start")

        while switch_up.value() and switch_down.value() and switch_select.value():
            time.sleep(0.05)

        time.sleep(1)
        rew = 0
        ti = 0
        state = env.reset()

        for j in range(EPISODE_LENGTH):
            action = agent.choose_action(state)
            new_state, reward, done = env.step(action, i, j)
            agent.learn(reward, new_state)
            rew += reward
            state = new_state
            ti += 1
            if done:
                break

        move_servo(state_angles[0])
        env.reset_cur_angle(state_angles[0])

        rewards_history.append(rew)
        timesteps.append(ti)

        print(f"Episode {i}: total reward {rew} in {ti} steps")
        print(f"Rewards history: {rewards_history}")
        print(f"Timesteps history: {timesteps}")

        display.fill(0)
        display.text(f"Episode {i} done", 15, 10)
        display.text(f"Reward: {rew}", 10, 25)
        display.text(f"Steps: {ti}", 10, 40)
        display.show()
        time.sleep(3)



# Timers. NOTE: ESP32-C3 has only two hardware timers (ids 0 and 1) --
# do not use Timer(2)+ on this board.
batt = Timer(0)
live_tim = Timer(1)

display.welcomemessage()

batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)

display.fill(0)
display.show()

if __name__ == "__main__":
    # On the real ESP32, MicroPython runs this file as __main__, so this
    # always executes exactly as before. The guard exists only so this file
    # can be imported as a module for desktop testing (see tests/) without
    # immediately launching the full interactive favorite-color/calibration/
    # training flow.
    main()
