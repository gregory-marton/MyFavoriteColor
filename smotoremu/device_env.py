"""Loads real, unmodified device .py files (ssd1306.py, servo.py, ...) against
our shims, by absolute file path rather than plain `import`.

This keeps device imports independent of host sys.path details and guarantees
that display tests use the real repo-root driver with emulator shims injected
for MicroPython-only modules. Per EMULATOR_TASKS.md ground rule R1, the real
device files are never modified to make this work.

Co-authored-by: GPT-5, Aug 2026
"""

import importlib.util
import builtins
import os
import sys
import types

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _install_fake_modules():
    if not hasattr(builtins, "const"):
        builtins.const = lambda x: x

    if "framebuf" not in sys.modules or getattr(sys.modules["framebuf"], "__smotoremu__", False):
        from smotoremu import framebuf_shim
        framebuf_shim.__smotoremu__ = True
        sys.modules["framebuf"] = framebuf_shim

    if "micropython" not in sys.modules or getattr(sys.modules["micropython"], "__smotoremu__", False):
        micropython_fake = types.ModuleType("micropython")
        micropython_fake.__smotoremu__ = True
        micropython_fake.const = lambda x: x
        sys.modules["micropython"] = micropython_fake

    if "ubinascii" not in sys.modules or getattr(sys.modules["ubinascii"], "__smotoremu__", False):
        from smotoremu.backends.cpython_shim import ubinascii
        ubinascii.__smotoremu__ = True
        sys.modules["ubinascii"] = ubinascii

    if "urandom" not in sys.modules or getattr(sys.modules["urandom"], "__smotoremu__", False):
        from smotoremu.backends.cpython_shim import urandom
        urandom.__smotoremu__ = True
        sys.modules["urandom"] = urandom

    if "uselect" not in sys.modules or getattr(sys.modules["uselect"], "__smotoremu__", False):
        from smotoremu.backends.cpython_shim import uselect
        uselect.__smotoremu__ = True
        sys.modules["uselect"] = uselect


def _install_machine_module():
    from smotoremu import machine_shim

    machine_fake = types.ModuleType("machine")
    machine_fake.__smotoremu__ = True
    for name in (
        "ADC",
        "DeviceReset",
        "I2C",
        "PWM",
        "Pin",
        "SoftI2C",
        "Timer",
        "mem32",
        "reset",
        "unique_id",
    ):
        setattr(machine_fake, name, getattr(machine_shim, name))
    sys.modules["machine"] = machine_fake


def load_real_module(filename, module_name=None):
    """Load a .py file from the repo root by path, bypassing sys.path order."""
    _install_fake_modules()
    _install_machine_module()
    module_name = module_name or ("smotoremu_real_" + filename[:-3])
    path = os.path.join(REPO_ROOT, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_real_ssd1306():
    return load_real_module("ssd1306.py")


def load_real_icons():
    old_machine = sys.modules.get("machine")
    old_ssd1306 = sys.modules.get("ssd1306")
    _install_fake_modules()
    try:
        sys.modules["ssd1306"] = load_real_ssd1306()
        _install_machine_module()
        return load_real_module("icons.py")
    finally:
        _restore_module("machine", old_machine)
        _restore_module("ssd1306", old_ssd1306)


def load_real_servo():
    old_machine = sys.modules.get("machine")
    try:
        _install_machine_module()
        return load_real_module("servo.py")
    finally:
        _restore_module("machine", old_machine)


def load_real_sensors():
    old_machine = sys.modules.get("machine")
    old_adxl345 = sys.modules.get("adxl345")
    try:
        _install_machine_module()
        return load_real_module("sensors.py")
    finally:
        _restore_module("machine", old_machine)
        _restore_module("adxl345", old_adxl345)


def load_real_adxl345():
    old_machine = sys.modules.get("machine")
    try:
        _install_machine_module()
        return load_real_module("adxl345.py")
    finally:
        _restore_module("machine", old_machine)


def _restore_module(name, module):
    if module is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = module
