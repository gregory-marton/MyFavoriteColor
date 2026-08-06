# This file is executed on every boot (including wake-boot from deepsleep)
# Co-authored-by: GPT-5, Aug 2026
# Co-authored-by: GPT-5.6-Sol-high, Aug 2026

# Always leave a short, interruptible escape window before importing hardware
# drivers or starting an activity. Ctrl-C during this sleep returns to REPL.
import time
print("Boot pause: 2 seconds; press Ctrl-C for REPL")
try:
    time.sleep(2)
except KeyboardInterrupt:
    print("Boot stopped.")
    raise
