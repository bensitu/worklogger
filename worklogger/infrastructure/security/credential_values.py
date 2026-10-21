"""Bounded OS credential values with atomic publication of larger secrets."""

import logging
import re
from uuid import uuid4

_PREFIX = "worklogger:parts:1:"
_PART_SIZE = 512
_MAX_PARTS = 512
LOGGER = logging.getLogger(__name__)


def _parts(name, value):
    if not value or not value.startswith(_PREFIX):
        return ()
    match = re.fullmatch(re.escape(_PREFIX) + r"([0-9a-f]{32}):([1-9][0-9]{0,2})", value)
    if not match or not 1 <= int(match[2]) <= _MAX_PARTS:
        raise ValueError("credential_storage_unavailable")
    return tuple(f"{name}:part:{match[1]}:{index}" for index in range(int(match[2])))


def read_credential(backend, service, name):
    value = backend.get_password(service, name)
    names = _parts(name, value)
    if not names:
        return value
    values = [backend.get_password(service, part) for part in names]
    if any(not isinstance(part, str) or len(part) > _PART_SIZE for part in values):
        raise ValueError("credential_storage_unavailable")
    return "".join(values)


def write_credential(backend, service, name, value):
    previous = backend.get_password(service, name)
    if len(value) > _PART_SIZE * _MAX_PARTS:
        raise ValueError("credential_storage_unavailable")
    try:
        old_parts = _parts(name, previous)
    except ValueError:
        # A damaged pointer cannot safely identify parts to remove.
        old_parts = ()
        LOGGER.warning("credential_cleanup_deferred")
    current_parts = ()
    published = value
    if len(value) > _PART_SIZE or value.startswith(_PREFIX):
        chunks = tuple(value[index:index + _PART_SIZE] for index in range(0, len(value), _PART_SIZE))
        published = f"{_PREFIX}{uuid4().hex}:{len(chunks)}"
        current_parts = _parts(name, published)
        try:
            for part, chunk in zip(current_parts, chunks):
                backend.set_password(service, part, chunk)
            backend.set_password(service, name, published)
        except Exception:
            # Do not remove parts if publication may already have reached the keyring.
            try:
                if backend.get_password(service, name) != published:
                    _delete_parts(backend, service, current_parts)
            except Exception:
                LOGGER.warning("credential_cleanup_deferred")
            raise
    elif value:
        backend.set_password(service, name, value)
    elif previous is not None:
        backend.delete_password(service, name)
    _delete_parts(backend, service, old_parts)


def _delete_parts(backend, service, names):
    for name in names:
        try:
            if backend.get_password(service, name) is not None:
                backend.delete_password(service, name)
        except Exception:
            LOGGER.warning("credential_cleanup_deferred")
