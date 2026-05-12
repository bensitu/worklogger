from __future__ import annotations

import base64
import hashlib
import secrets


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def build_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)
