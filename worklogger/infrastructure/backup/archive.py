"""Bounded personal backup envelopes with authenticated client-side encryption."""

import gzip
import io
import os
import unicodedata
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from worklogger.domain.cloud_backup import MAX_BACKUP_BYTES, MAX_DOCUMENT_BYTES

_MAGIC = b"WL-PERSONAL-2\n"
_LEGACY_MAGIC = b"WL-PERSONAL-1\n"


def _key(passphrase, salt):
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(passphrase.encode("utf-8"))


class PersonalBackupArchive:
    def encode(self, document: bytes, *, encrypted: bool, passphrase: str = "") -> bytes:
        if len(document) > MAX_DOCUMENT_BYTES:
            raise ValueError("cloud_backup_too_large")
        content = gzip.compress(document, mtime=0)
        if encrypted:
            if not isinstance(passphrase, str) or not 12 <= len(passphrase) <= 1024:
                raise ValueError("cloud_passphrase_invalid")
            salt, nonce = os.urandom(16), os.urandom(12)
            header = _MAGIC + b"E" + salt + nonce
            key = _key(unicodedata.normalize("NFC", passphrase), salt)
            content = header + AESGCM(key).encrypt(nonce, content, header)
        else:
            content = _MAGIC + b"P" + content
        if len(content) > MAX_BACKUP_BYTES:
            raise ValueError("cloud_backup_too_large")
        return content

    def decode(self, content: bytes, *, passphrase: str = "", require_encrypted: bool = False) -> bytes:
        magic = next((value for value in (_MAGIC, _LEGACY_MAGIC) if content.startswith(value)), None)
        if len(content) > MAX_BACKUP_BYTES or magic is None:
            raise ValueError("cloud_backup_invalid")
        content = content[len(magic):]
        if require_encrypted and content[:1] != b"E":
            raise ValueError("cloud_backup_invalid")
        try:
            if content[:1] == b"E":
                if len(content) < 45:
                    raise ValueError("cloud_backup_invalid")
                salt, nonce = content[1:17], content[17:29]
                content = _decrypt(content, passphrase, salt, nonce, magic)
            elif content[:1] == b"P":
                content = content[1:]
            else:
                raise ValueError("cloud_backup_invalid")
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as stream:
                document = stream.read(MAX_DOCUMENT_BYTES + 1)
            if len(document) > MAX_DOCUMENT_BYTES:
                raise ValueError("cloud_backup_too_large")
            return document
        except InvalidTag:
            raise ValueError("cloud_decryption_failed") from None
        except (OSError, EOFError, OverflowError, zlib.error):
            raise ValueError("cloud_backup_invalid") from None


def _decrypt(content, passphrase, salt, nonce, magic):
    if not isinstance(passphrase, str) or not passphrase or len(passphrase) > 4096:
        raise ValueError("cloud_passphrase_invalid")
    canonical = unicodedata.normalize("NFC", passphrase)
    if magic == _MAGIC:
        return AESGCM(_key(canonical, salt)).decrypt(nonce, content[29:], magic + content[:29])
    candidates = dict.fromkeys((passphrase, canonical, unicodedata.normalize("NFD", passphrase)))
    for candidate in candidates:
        if not 12 <= len(candidate) <= 1024:
            continue
        try:
            return AESGCM(_key(candidate, salt)).decrypt(nonce, content[29:], magic)
        except InvalidTag:
            continue
    raise InvalidTag
