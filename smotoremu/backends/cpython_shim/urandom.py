"""`urandom` module shim for Session-driven device imports.

Co-authored-by: GPT-5, Aug 2026
"""

import random

from smotoremu.backends.cpython_shim import current_session


def _rng():
    try:
        return current_session().rng
    except LookupError:
        return random


def seed(n):
    _rng().seed(n)


def uniform(a, b):
    return _rng().uniform(a, b)


def choice(seq):
    return _rng().choice(seq)


def randint(a, b):
    return _rng().randint(a, b)


def getrandbits(n):
    return _rng().getrandbits(n)
