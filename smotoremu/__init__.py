"""SmartMotor emulator package.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.version import __version__
from smotoremu.expect import expect, wait_for
from smotoremu.testing import launch

__all__ = ["__version__", "expect", "launch", "wait_for"]
