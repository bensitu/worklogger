"""Install a resolved wheel set offline with mandatory SHA-256 verification."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def wheel_requirements(directory):
    packages = {}
    for path in sorted(directory.iterdir()):
        if path.suffix != ".whl" or not path.is_file() or path.is_symlink():
            raise ValueError("Dependency downloads must contain only wheels")
        with zipfile.ZipFile(path) as wheel:
            metadata = [name for name in wheel.namelist() if name.count("/") == 1 and name.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("Wheel metadata is missing or ambiguous")
            package = BytesParser().parsebytes(wheel.read(metadata[0]))
        name, version = package.get("Name", ""), package.get("Version", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.!+-]*", version):
            raise ValueError("Wheel package identity is invalid")
        name = re.sub(r"[-_.]+", "-", name).lower()
        if name in packages:
            raise ValueError("A dependency resolves to more than one wheel")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        packages[name] = f"{name}=={version} --hash=sha256:{digest}"
    if not packages:
        raise ValueError("No dependency wheels were downloaded")
    return "\n".join(packages[name] for name in sorted(packages)) + "\n"


def install_dependencies(requirements, *, lock_output, wheels=(), constraints=()):
    with tempfile.TemporaryDirectory(prefix="worklogger-dependencies-") as temporary:
        directory = Path(temporary)
        command = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--dest", str(directory)]
        command.extend(str(path) for path in wheels)
        for path in requirements:
            command.extend(("-r", str(path)))
        for path in constraints:
            command.extend(("-c", str(path)))
        subprocess.run(command, check=True)
        lock_output.parent.mkdir(parents=True, exist_ok=True)
        lock_output.write_text(wheel_requirements(directory), encoding="utf-8")
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--require-hashes",
                        "--only-binary=:all:", "--find-links", str(directory),
                        "-r", str(lock_output)], check=True)
        if wheels:
            artifacts = []
            for wheel in wheels:
                wheel = Path(wheel).resolve()
                with wheel.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                artifacts.append(wheel.as_uri() + "#sha256=" + digest)
            subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                            "--require-hashes", "--force-reinstall", *artifacts], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", nargs="+", type=Path)
    parser.add_argument("--lock-output", type=Path, default=ROOT / "build/dependencies.lock.txt")
    args = parser.parse_args()
    install_dependencies(args.requirements, lock_output=args.lock_output)


if __name__ == "__main__":
    main()
