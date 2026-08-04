"""CPython import shims for running MicroPython device modules in a Session.

The active session is stored in a ContextVar so future session handoff code can
keep device-thread state explicit. The first T013 runner still serializes at
the thread boundary; interactive condition-variable handoff comes later.

Co-authored-by: GPT-5, Aug 2026
"""

from contextvars import ContextVar

active_session = ContextVar("smotoremu_active_session")


def current_session():
    return active_session.get()
