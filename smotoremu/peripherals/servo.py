"""Servo model for PWM-driven SmartMotor emulation.

Co-authored-by: GPT-5, Aug 2026
"""


class ServoModel:
    SLEW_DEG_PER_SEC = 400  # GUESS: ~0.15 s/60deg hobby servo; needs bench data.

    def __init__(self, board, pin_id):
        self.board = board
        self.pin_id = pin_id
        self.commanded_angle = 0.0
        self._actual_angle = 0.0
        self._start_angle = 0.0
        self._move_start_us = board.clock.now_us
        self._move_end_us = board.clock.now_us
        self._is_moving = False
        self._settle_handle = None
        self.on_change = None
        self.board.on_pwm_change(pin_id, self._on_pwm_change)

    @property
    def actual_angle(self):
        self._update_position()
        return self._actual_angle

    @property
    def is_moving(self):
        self._update_position()
        return self._is_moving

    def _on_pwm_change(self, pin_id, freq, duty):
        self._update_position()
        if duty == 0:
            self._cancel_settle()
            self.commanded_angle = self._actual_angle
            self._is_moving = False
            self._notify()
            return

        pulse_us = duty * 1_000_000 / (1024 * freq)
        angle = (pulse_us - 600) * 180 / (2400 - 600)
        self.commanded_angle = min(180.0, max(0.0, angle))
        self._start_move()
        self._notify()

    def _start_move(self):
        self._cancel_settle()
        self._start_angle = self._actual_angle
        self._move_start_us = self.board.clock.now_us
        distance = abs(self.commanded_angle - self._start_angle)
        duration_us = int(round(distance / self.SLEW_DEG_PER_SEC * 1_000_000))
        self._move_end_us = self._move_start_us + duration_us
        if duration_us == 0:
            self._actual_angle = self.commanded_angle
            self._is_moving = False
            return
        self._is_moving = True
        self._settle_handle = self.board.scheduler.after(duration_us, self._settle)

    def _update_position(self):
        if not self._is_moving:
            return
        now = self.board.clock.now_us
        if now >= self._move_end_us:
            self._settle()
            return
        span = self._move_end_us - self._move_start_us
        progress = (now - self._move_start_us) / span
        self._actual_angle = self._start_angle + (self.commanded_angle - self._start_angle) * progress

    def _settle(self):
        self._actual_angle = self.commanded_angle
        self._is_moving = False
        self._settle_handle = None
        self._notify()

    def _cancel_settle(self):
        if self._settle_handle is not None:
            self.board.scheduler.cancel(self._settle_handle)
            self._settle_handle = None

    def _notify(self):
        if self.on_change is not None:
            self.on_change(self)
