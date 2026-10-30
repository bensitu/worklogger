"""Atomic replacement for locally generated files."""

from contextlib import contextmanager
from pathlib import Path
import os
import tempfile


def file_fingerprint(status: os.stat_result) -> tuple[int, int, int, int, int]:
    """Identify a file and its current metadata for cache invalidation."""
    return status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns, status.st_size


def _sync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def atomic_destination(destination: Path, *, overwrite: bool = True):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=destination.suffix, dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, destination)
        elif os.name == "nt":
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
        _sync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)


def spreadsheet_text(value: str) -> str:
    """Prevent user text from being interpreted as a spreadsheet formula."""
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text
