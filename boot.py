# This file is executed on every boot (including wake-boot from deepsleep)
# Co-authored-by: GPT-5, Aug 2026
#import esp
#esp.osdebug(None)
#import webrepl
#webrepl.start()

try:
    import smirror
    smirror.install()
except Exception:
    # Mirror telemetry is observational and must never prevent normal boot.
    pass
