
from machine import Pin, SoftI2C, Timer
import time, urandom, math
import servo, icons, sensors
import struct

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
		r, g, b, w = self.read_rgbw()
		r = min(255, r >> 6)
		g = min(255, g >> 6)
		b = min(255, b >> 6)
		wr, wg, wb = self.white_balance
		r = min(255, round(r * wr))
		g = min(255, round(g * wg))
		b = min(255, round(b * wb))
		return r, g, b

_PERCEPTUAL_WEIGHTS = (0.30, 0.59, 0.11)

def dist_euclidean(c1, c2):
	return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))

def dist_perceptual(c1, c2):
	return math.sqrt(sum(w * (a - b) ** 2 for w, a, b in zip(_PERCEPTUAL_WEIGHTS, c1, c2)))

DISTANCE_FUNCS = {
	"Perceptual": dist_perceptual,
	"Euclidean": dist_euclidean,
}
DISTANCE_FUNC_NAMES = list(DISTANCE_FUNCS.keys())

def compute_state_rewards(state_colors, favorite_color, distance_fn, max_reward=200):
	distances = [distance_fn(c, favorite_color) for c in state_colors]
	max_d = max(distances) if max(distances) > 0 else 1
	rewards = [round(max_reward * (1 - d / max_d)) for d in distances]
	return rewards, distances

NUM_STATES = 5

EPISODE_LENGTH = 10

DISTANCE_METRIC = "Perceptual"

SETTLE_TIME = 2.0

EPISODES = 10

COLOR_INTEGRATION_TIME = IT_640MS

WHITE_BALANCE_RGB = (1.0, 1.066, 1.948)

sens = sensors.SENSORS()

favorite_color = None
state_colors = []
state_angles = []
state_rewards = []
state_distances = []

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

_live_reward_row = 56

def live_reward_tick(p):
	if motor_moving:
		return
	if favorite_color is None:
		return
	try:
		rgb = sensor.rgb
		distance_fn = DISTANCE_FUNCS[DISTANCE_METRIC]
		d = distance_fn(rgb, favorite_color)

		if state_distances:
			max_d = max(state_distances) if max(state_distances) > 0 else 1
		else:
			max_d = 255
		reward_now = max(0, round(200 * (1 - d / max_d)))
		display.fill_rect(0, _live_reward_row, 128, 8, 0)
		display.text(f"Now: R={reward_now}", 0, _live_reward_row, 1)
		display.show()
	except Exception as e:

		print(f"live_reward_tick error: {e}")

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

		if action == self.action_space[0]:
			target_state = max(0, previous_state - 1)
		elif action == self.action_space[1]:
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

def capture_favorite_color():
	display.fill(0)
	display.text("Favorite Color", 10, 5)
	display.text("POT=aim arm", 15, 20)
	display.text("SELECT=lock in", 10, 50)
	display.show()

	while not switch_select.value() or not switch_up.value() or not switch_down.value():
		time.sleep(0.05)

	last_shown = None
	last_pot_angle = -1
	pot_threshold = 2
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

def calibrate_states(target_num_states):
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
				s.write_angle(servo_angle)
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
			if not switch_select.value():
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

			elif not switch_down.value() and not pot_mode:
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

			elif not switch_up.value():
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

def _wait_release():
	while not switch_select.value() or not switch_up.value() or not switch_down.value():
		time.sleep(0.05)

def _favorite_color_state_index():
	if not state_colors or favorite_color is None:
		return None
	distance_fn = DISTANCE_FUNCS[DISTANCE_METRIC]
	dists = [distance_fn(c, favorite_color) for c in state_colors]
	return dists.index(min(dists))

def confirm_screen():
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

batt = Timer(0)
live_tim = Timer(1)

display.welcomemessage()

batt.init(period=10000, mode=Timer.PERIODIC, callback=displaybatt)

display.fill(0)
display.show()

if __name__ == "__main__":

	main()
