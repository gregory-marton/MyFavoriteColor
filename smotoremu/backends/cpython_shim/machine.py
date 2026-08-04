"""`machine` module shim for Session-driven device imports.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.backends.cpython_shim import current_session
from smotoremu.machine_shim import ADC, DeviceReset, I2C, PWM, Pin, SoftI2C, Timer

Pin.use_board(current_session().board)


def unique_id():
    return current_session().board.unique_id


def reset():
    raise DeviceReset()
