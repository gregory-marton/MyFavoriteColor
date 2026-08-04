"""Public SmartMotor emulator facade.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.expect import expect, wait_for
from smotoremu.testing import launch

__all__ = ["expect", "launch", "wait_for"]
