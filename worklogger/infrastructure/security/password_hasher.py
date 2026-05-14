"""PBKDF2 password hashing adapter."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets


@dataclass(frozen=True)
class PasswordHash:
    hash_hex: str
    salt_hex: str


@dataclass(frozen=True)
class PasswordVerification:
    matched: bool
    needs_upgrade: bool = False


class PBKDF2PasswordHasher:
    def __init__(
        self,
        *,
        iterations: int = 600_000,
        legacy_iterations: tuple[int, ...] = (100_000,),
    ) -> None:
        self.iterations = int(iterations)
        self.legacy_iterations = tuple(int(value) for value in legacy_iterations)

    def hash_password(self, password: str) -> PasswordHash:
        salt_hex = secrets.token_hex(16)
        return PasswordHash(
            hash_hex=self.hash_with_salt(
                password,
                salt_hex,
                iterations=self.iterations,
            ),
            salt_hex=salt_hex,
        )

    def hash_with_salt(
        self,
        password: str,
        salt_hex: str,
        *,
        iterations: int | None = None,
    ) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            self.iterations if iterations is None else int(iterations),
        ).hex()

    def verify(
        self,
        password: str,
        stored_hash: str,
        salt_hex: str,
    ) -> PasswordVerification:
        current = self.hash_with_salt(password, salt_hex)
        if hmac.compare_digest(current, stored_hash):
            return PasswordVerification(matched=True, needs_upgrade=False)
        for iterations in self.legacy_iterations:
            legacy = self.hash_with_salt(password, salt_hex, iterations=iterations)
            if hmac.compare_digest(legacy, stored_hash):
                return PasswordVerification(matched=True, needs_upgrade=True)
        return PasswordVerification(matched=False)
