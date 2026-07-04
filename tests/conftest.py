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
_mock_time_ms = 1000000

def fake_sleep(secs):
    global _mock_time_ms
    _mock_time_ms += int(secs * 1000)

time.sleep = fake_sleep
time.sleep_ms = lambda ms: fake_sleep(ms / 1000.0)
time.sleep_us = lambda us: fake_sleep(us / 1000000.0)
time.ticks_ms = lambda: _mock_time_ms
time.ticks_diff = lambda t1, t2: t1 - t2
