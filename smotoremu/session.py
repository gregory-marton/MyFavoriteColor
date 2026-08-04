"""Session runner for emulated SmartMotor device code.

Device code runs in one daemon thread while the controller owns the session
object. This first T013 runner serializes at boot/run_until_idle boundaries and
uses virtual time for MicroPython-style sleeps. The intended invariant for the
interactive runner is stricter: only one of the device thread or controller
thread may execute session-owned state at a time, with condition-variable
handoff whenever device code sleeps or performs emulated I/O.

Co-authored-by: GPT-5, Aug 2026
"""

import importlib
import os
import random
import sys
import threading
import time as time_module

from smotoremu.backends.cpython_shim import active_session
from smotoremu.clock import VirtualClock
from smotoremu.machine_shim import Board, Pin
from smotoremu.peripherals.adxl345 import ADXL345Device
from smotoremu.peripherals.inputs import Battery, Buttons, Potentiometer
from smotoremu.peripherals.servo import ServoModel
from smotoremu.peripherals.ssd1306 import SSD1306Device
from smotoremu.pinmap import PIN_SERVO

SHIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backends", "cpython_shim")

DEVICE_MODULES = [
    "machine",
    "framebuf",
    "micropython",
    "main",
    "myfavcolor",
    "standalone",
    "webconnect",
    "sensors",
    "icons",
    "ssd1306",
    "adxl345",
    "servo",
    "prefs",
    "files",
]


class Port:
    pass


class Session:
    def __init__(self, *, seed=0, clock_mode="instant", world=None, vfs_dir=None, board_config=None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.clock = VirtualClock(mode=clock_mode)
        self.board = Board(clock=self.clock)
        Pin.use_board(self.board)
        self.bus = self.board.i2c_bus
        self.world = world
        self.vfs_dir = vfs_dir
        self.board_config = board_config or {}

        self.display = SSD1306Device()
        self.bus.register(0x3C, self.display)
        self.servo = ServoModel(self.board, PIN_SERVO)
        self.buttons = Buttons(self.board)
        self.pot = Potentiometer(self.board, rng=self.rng)
        self.battery = Battery(self.board)
        self.accel = None
        if self.board_config.get("accelerometer", True):
            self.accel = ADXL345Device(rng=self.rng)
            self.bus.register(0x53, self.accel)
        self.port = Port()

        self._thread = None
        self._exited = False
        self._error = None

    @property
    def exited(self) -> bool:
        return self._exited

    @property
    def error(self) -> BaseException | None:
        return self._error

    def boot(self, entry: str = "main") -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("session is already running")
        self._exited = False
        self._error = None
        self._thread = threading.Thread(target=self._run_entry, args=(entry,), daemon=True)
        self._thread.start()

    def run_until_idle(self, timeout_ms: int = 5000) -> None:
        if self._thread is None:
            return
        self._thread.join(timeout_ms / 1000)

    def stop(self) -> None:
        self.run_until_idle(timeout_ms=0)

    def _run_entry(self, entry):
        saved_modules = {name: sys.modules.get(name) for name in DEVICE_MODULES}
        old_path = list(sys.path)
        old_time = {
            "sleep": getattr(time_module, "sleep", None),
            "sleep_ms": getattr(time_module, "sleep_ms", None),
            "sleep_us": getattr(time_module, "sleep_us", None),
            "ticks_ms": getattr(time_module, "ticks_ms", None),
            "ticks_diff": getattr(time_module, "ticks_diff", None),
        }
        token = active_session.set(self)
        try:
            Pin.use_board(self.board)
            _purge_device_modules()
            if SHIM_DIR in sys.path:
                sys.path.remove(SHIM_DIR)
            sys.path.insert(0, SHIM_DIR)
            self._install_time_shim()
            module = importlib.import_module(entry)
            if hasattr(module, "main"):
                module.main()
            self._exited = True
        except SystemExit:
            self._exited = True
        except BaseException as exc:
            self._error = exc
        finally:
            active_session.reset(token)
            _restore_time(old_time)
            sys.path[:] = old_path
            _restore_modules(saved_modules)

    def _install_time_shim(self):
        time_module.sleep = lambda seconds: self.clock.sleep_us(int(seconds * 1_000_000))
        time_module.sleep_ms = lambda ms: self.clock.sleep_us(int(ms * 1000))
        time_module.sleep_us = self.clock.sleep_us
        time_module.ticks_ms = self.clock.now_ms
        time_module.ticks_diff = lambda t1, t2: t1 - t2


def _purge_device_modules():
    for name in DEVICE_MODULES:
        sys.modules.pop(name, None)


def _restore_modules(saved_modules):
    for name in DEVICE_MODULES:
        if saved_modules[name] is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved_modules[name]


def _restore_time(old_time):
    for name, value in old_time.items():
        if value is None:
            try:
                delattr(time_module, name)
            except AttributeError:
                pass
        else:
            setattr(time_module, name, value)
