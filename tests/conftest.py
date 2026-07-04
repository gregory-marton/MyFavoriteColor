import sys
import os
import builtins
import time

# Add tests/fakes to the front of sys.path so mock hardware modules are imported instead of failing
fakes_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fakes"))
if fakes_path not in sys.path:
    sys.path.insert(0, fakes_path)

# Mock the MicroPython 'const' built-in function
builtins.const = lambda x: x

# Mock MicroPython time functions on the standard time module
time.sleep_ms = lambda ms: time.sleep(ms / 1000.0)
time.sleep_us = lambda us: time.sleep(us / 1000000.0)
