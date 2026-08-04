"""`ubinascii` module shim for Session-driven device imports.

Co-authored-by: GPT-5, Aug 2026
"""

import binascii


def hexlify(data):
    return binascii.hexlify(data)


def unhexlify(data):
    return binascii.unhexlify(data)
