import sys
import os
import builtins
import time
import pytest

# Add the repo root and tests/fakes to sys.path so tests work from any cwd.
tests_dir = os.path.dirname(__file__)
repo_root = os.path.abspath(os.path.join(tests_dir, os.pardir))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

fakes_path = os.path.abspath(os.path.join(tests_dir, "fakes"))
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


@pytest.fixture(autouse=True)
def reset_fake_machine():
    try:
        import machine
        machine.reset_mock_state()
    except Exception:
        pass
    yield
