"""`uselect` module shim for Session-driven device imports.

Co-authored-by: GPT-5, Aug 2026
"""

POLLIN = 1


class poll:
    def __init__(self):
        self.registered = []

    def register(self, obj, eventmask):
        self.registered.append((obj, eventmask))

    def poll(self, timeout=0):
        return []
