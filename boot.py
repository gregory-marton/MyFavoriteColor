# This file is executed on every boot (including wake-boot from deepsleep)
# Co-authored-by: GPT-5, Aug 2026
# Co-authored-by: GPT-5.6-Sol-high, Aug 2026

# Mirror mode is deliberately the whole device activity. The deployed main.py
# is a no-op, so Ctrl-C from mirror.run() leaves a usable REPL.
try:
    import mirror
    mirror.run()
except KeyboardInterrupt:
    print("Mirror stopped; REPL ready")
