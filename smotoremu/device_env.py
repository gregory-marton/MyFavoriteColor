"""Loads real, unmodified device .py files (ssd1306.py, servo.py, ...) against
our shims, by absolute file path rather than plain `import`.

Necessary because tests/fakes/ is earlier on sys.path than the repo root (set
up in tests/conftest.py for the existing device-code test suite), so a plain
`import ssd1306` would silently resolve to tests/fakes/ssd1306.py -- a
different, simpler fake -- instead of the real driver this emulator needs to
run pixel-faithfully. Per EMULATOR_TASKS.md ground rule R1, the real device
files are never modified to make this work.
"""

import importlib.util
import os
import sys
import types

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def _install_fake_modules():
    if "framebuf" not in sys.modules or getattr(sys.modules["framebuf"], "__smotoremu__", False):
        from smotoremu import framebuf_shim
        framebuf_shim.__smotoremu__ = True
        sys.modules["framebuf"] = framebuf_shim

    if "micropython" not in sys.modules or getattr(sys.modules["micropython"], "__smotoremu__", False):
        micropython_fake = types.ModuleType("micropython")
        micropython_fake.__smotoremu__ = True
        micropython_fake.const = lambda x: x
        sys.modules["micropython"] = micropython_fake


def load_real_module(filename, module_name=None):
    """Load a .py file from the repo root by path, bypassing sys.path order."""
    _install_fake_modules()
    module_name = module_name or ("smotoremu_real_" + filename[:-3])
    path = os.path.join(REPO_ROOT, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_real_ssd1306():
    return load_real_module("ssd1306.py")
