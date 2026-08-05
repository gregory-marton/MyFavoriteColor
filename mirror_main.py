"""Keep the normal MicroPython main slot empty while mirror.py owns the device.

Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

# boot.py runs mirror.py. This file intentionally does nothing so a mirror
# interrupt returns to the REPL instead of starting the normal activity.
