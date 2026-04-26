"""Shared cryptographic helpers."""

from __future__ import annotations

import hashlib
import platform
import uuid


def machine_key() -> bytes:
    """Derive a stable 32-byte key from this machine's hardware identifiers."""
    seed = f"{platform.node()}|{uuid.getnode()}".encode("utf-8")
    return hashlib.sha256(seed).digest()
