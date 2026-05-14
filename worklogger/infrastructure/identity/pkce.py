"""PKCE helpers for OIDC authorization."""

from __future__ import annotations

import base64
import hashlib
import secrets


def generate_verifier(length: int = 64) -> str:
    size = max(32, min(96, int(length)))
    return secrets.token_urlsafe(size)[:128]


def build_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(str(verifier).encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
