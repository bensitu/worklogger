"""Bounded personal backup envelopes with authenticated client-side encryption."""

import gzip
import io
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from worklogger.domain.cloud_backup import MAX_BACKUP_BYTES, MAX_DOCUMENT_BYTES

_MAGIC = b"WL-PERSONAL-1\n"


def _key(passphrase, salt):
    if not isinstance(passphrase, str) or len(passphrase) < 12 or len(passphrase) > 1024:
        raise ValueError("cloud_passphrase_invalid")
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(passphrase.encode("utf-8"))


class PersonalBackupArchive:
    def encode(self, document: bytes, *, encrypted: bool, passphrase: str = "") -> bytes:
        if len(document) > MAX_DOCUMENT_BYTES:
            raise ValueError("cloud_backup_too_large")
        content = gzip.compress(document, mtime=0)
        if encrypted:
            salt, nonce = os.urandom(16), os.urandom(12)
            content = _MAGIC + b"E" + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, content, _MAGIC)
        else:
            content = _MAGIC + b"P" + content
        if len(content) > MAX_BACKUP_BYTES:
            raise ValueError("cloud_backup_too_large")
        return content

    def decode(self, content: bytes, *, passphrase: str = "", require_encrypted: bool = False) -> bytes:
        if len(content) > MAX_BACKUP_BYTES or not content.startswith(_MAGIC):
            raise ValueError("cloud_backup_invalid")
        content = content[len(_MAGIC):]
        if require_encrypted and content[:1] != b"E":
            raise ValueError("cloud_backup_invalid")
        try:
            if content[:1] == b"E":
                salt, nonce = content[1:17], content[17:29]
                content = AESGCM(_key(passphrase, salt)).decrypt(nonce, content[29:], _MAGIC)
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
        except (OSError, EOFError, OverflowError):
            raise ValueError("cloud_backup_invalid") from None
