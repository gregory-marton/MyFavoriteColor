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
import builtins
import os
import random
import sys
import threading
import time as time_module
import tempfile

from smotoremu.backends.cpython_shim import active_session
from smotoremu.clock import VirtualClock
from smotoremu.machine_shim import Board, Pin
from smotoremu.peripherals.adxl345 import ADXL345Device
from smotoremu.peripherals.inputs import Battery, Buttons, Potentiometer
from smotoremu.peripherals.servo import ServoModel
from smotoremu.peripherals.ssd1306 import SSD1306Device
from smotoremu.pinmap import PIN_SERVO
from smotoremu.port import Port
from smotoremu.trace import TraceRecorder
from smotoremu.vfs import VFS

SHIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backends", "cpython_shim")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEVICE_MODULES = [
    "machine",
    "framebuf",
    "micropython",
    "main",
    "myfavcolor",
    "standalone",
    "webconnect",
    "healthcheck",
    "healthcheck_logic",
    "mirror",
    "sensors",
    "icons",
    "ssd1306",
    "adxl345",
    "servo",
    "prefs",
    "files",
    "ubinascii",
    "urandom",
    "uselect",
]


class Session:
    def __init__(self, *, seed=0, clock_mode="instant", world=None, vfs_dir=None, board_config=None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.trace = TraceRecorder(
            seed=seed,
            config={
                "clock_mode": clock_mode,
                "board_config": board_config or {},
            },
        )
        self.clock = VirtualClock(mode=clock_mode)
        self.board = Board(clock=self.clock, trace=self.trace)
        Pin.use_board(self.board)
        self.bus = self.board.i2c_bus
        self.world = world
        self.vfs = VFS(vfs_dir or tempfile.mkdtemp(prefix="smotoremu-flash-"))
        self.vfs_dir = self.vfs.root
        self.board_config = board_config or {}

        self.display = SSD1306Device()
        self.display.on_frame = lambda display: self.trace.record(
            self.clock.now_us,
            "frame",
            {"frame_count": display.frame_count, "nbytes": len(display.gddram)},
        )
        self.bus.register(0x3C, self.display)
        self.servo = ServoModel(self.board, PIN_SERVO)
        self.board.servo_model = self.servo
        self.buttons = Buttons(self.board)
        self.pot = Potentiometer(self.board, rng=self.rng)
        self.battery = Battery(self.board)
        self.accel = None
        if self.board_config.get("accelerometer", True):
            self.accel = ADXL345Device(rng=self.rng)
            self.bus.register(0x53, self.accel)
        self.port = Port(self.board, self.bus)
        self.imported_modules = []

        self._thread = None
        self._exited = False
        self._error = None
        self._stop_requested = False

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
        self._stop_requested = False
        self.clock.stop_requested = False
        self._thread = threading.Thread(target=self._run_entry, args=(entry,), daemon=True)
        self._thread.start()

    def run_until_idle(self, timeout_ms: int = 5000) -> None:
        if self._thread is None:
            return
        self._thread.join(timeout_ms / 1000)

    def stop(self) -> None:
        self._stop_requested = True
        self.clock.stop_requested = True
        self.run_until_idle(timeout_ms=100)

    def _run_entry(self, entry):
        saved_modules = {name: sys.modules.get(name) for name in DEVICE_MODULES}
        old_path = list(sys.path)
        old_cwd = os.getcwd()
        old_time = {
            "sleep": getattr(time_module, "sleep", None),
            "sleep_ms": getattr(time_module, "sleep_ms", None),
            "sleep_us": getattr(time_module, "sleep_us", None),
            "ticks_ms": getattr(time_module, "ticks_ms", None),
            "ticks_diff": getattr(time_module, "ticks_diff", None),
            "time": getattr(time_module, "time", None),
        }
        old_open = builtins.open
        old_print = builtins.print
        old_import = builtins.__import__
        old_os = {
            "listdir": os.listdir,
            "remove": os.remove,
        }
        token = active_session.set(self)
        try:
            Pin.use_board(self.board)
            _purge_device_modules()
            sys.path[:] = _device_sys_path(old_path, self.vfs.root)
            os.chdir(self.vfs.root)
            self._install_time_shim()
            self._install_vfs_shim(old_open, old_os)
            self._install_print_shim(old_print)
            self._install_import_trace(old_import)
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
            builtins.open = old_open
            builtins.print = old_print
            builtins.__import__ = old_import
            os.listdir = old_os["listdir"]
            os.remove = old_os["remove"]
            os.chdir(old_cwd)
            sys.path[:] = old_path
            _restore_modules(saved_modules)

    def _install_time_shim(self):
        def sleep_us(us):
            self._raise_if_stop_requested()
            self.clock.sleep_us(us)
            self._raise_if_stop_requested()

        time_module.sleep = lambda seconds: sleep_us(int(seconds * 1_000_000))
        time_module.sleep_ms = lambda ms: sleep_us(int(ms * 1000))
        time_module.sleep_us = sleep_us
        time_module.ticks_ms = self.clock.now_ms
        time_module.ticks_diff = lambda t1, t2: t1 - t2
        time_module.time = lambda: self.clock.now_us / 1_000_000

    def _raise_if_stop_requested(self):
        if self._stop_requested:
            raise SystemExit()

    def _install_vfs_shim(self, old_open, old_os):
        def checked_open(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.isabs(os.fspath(file)):
                raise ValueError("device code may not open absolute host paths")
            return old_open(file, *args, **kwargs)

        def checked_listdir(path="."):
            _reject_absolute(path)
            return old_os["listdir"](path)

        def checked_remove(path):
            _reject_absolute(path)
            return old_os["remove"](path)

        builtins.open = checked_open
        os.listdir = checked_listdir
        os.remove = checked_remove

    def _install_print_shim(self, old_print):
        def traced_print(*args, **kwargs):
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            message = sep.join(str(arg) for arg in args)
            self.trace.record(self.clock.now_us, "log", {"message": message, "end": end})
            old_print(*args, **kwargs)

        builtins.print = traced_print

    def _install_import_trace(self, old_import):
        def traced_import(name, globals=None, locals=None, fromlist=(), level=0):
            top_level = name.split(".", 1)[0]
            if level == 0 and top_level in DEVICE_MODULES and top_level not in self.imported_modules:
                self.imported_modules.append(top_level)
            return old_import(name, globals, locals, fromlist, level)

        builtins.__import__ = traced_import


def _purge_device_modules():
    for name in DEVICE_MODULES:
        sys.modules.pop(name, None)


def _device_sys_path(old_path, vfs_root):
    path = [entry for entry in old_path if entry not in {SHIM_DIR, vfs_root, REPO_ROOT}]
    fakes_index = next((index for index, entry in enumerate(path) if entry.endswith(os.path.join("tests", "fakes"))), len(path))
    path.insert(fakes_index, REPO_ROOT)
    return [SHIM_DIR, vfs_root] + path


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


def _reject_absolute(path):
    if os.path.isabs(os.fspath(path)):
        raise ValueError("device code may not use absolute host paths")
