from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Return a new 26-character Crockford-base32 ULID.

    Assumes the system clock is usable for the 48-bit timestamp prefix and that
    ``os.urandom`` can supply 80 bits of entropy.
    """
    timestamp_ms = int(time.time() * 1000)
    if timestamp_ms < 0 or timestamp_ms >= 2**48:
        raise ValueError("timestamp is outside the ULID range")
    entropy = os.urandom(10)
    value = (timestamp_ms << 80) | int.from_bytes(entropy, "big")
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = _CROCKFORD[value & 31]
        value >>= 5
    return "".join(chars)


def is_ulid(value: str) -> bool:
    """Return True when ``value`` is a 26-char Crockford ULID. Assumes ASCII text."""
    if len(value) != 26:
        return False
    alphabet = set(_CROCKFORD)
    return all(char in alphabet for char in value.upper())
