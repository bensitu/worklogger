"""Build provenance, isolated artifact verification and checksum delivery."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.lock_environment import digest, verify_lock, target
from scripts.build_resources import bundled_resources
from worklogger.__about__ import APP_VERSION
from worklogger.infrastructure.files import atomic_destination


def source_digest():
    paths = set((ROOT / "worklogger").rglob("*.py")) | set((ROOT / "scripts").rglob("*.py"))
    paths |= {ROOT / "WorkLogger.spec", ROOT / "LICENSE", ROOT / "requirements.txt", ROOT / "requirements-build.txt"}
    paths |= {Path(source) for source, _destination in bundled_resources(ROOT)}
    value = hashlib.sha256()
    for path in sorted(paths):
        value.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        value.update(bytes.fromhex(digest(path)))
    return value.hexdigest()


def write_build_info(path, lock=None, *, local_inference=False):
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False)
    value = {"format_version": 1, "application_version": APP_VERSION, "target": target(),
             "built_at": datetime.now(timezone.utc).isoformat(), "source_revision": revision.stdout.strip(),
             "source_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
             "source_digest": source_digest(), "local_inference": local_inference,
             "dependency_lock_digest": digest(lock) if lock else None,
             "dependencies": {row.metadata["Name"]: row.version for row in metadata.distributions()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_files(directory):
    paths = sorted(path for path in directory.rglob("*") if path.is_file())
    for path in paths:
        relative = path.relative_to(directory).as_posix().lower()
        if path.is_symlink() or path.suffix.lower() in {".db", ".gguf"} or any(token in relative for token in (".db-wal", ".db-shm", ".bak_", ".local.json", "remember_token", "session.json")):
            raise ValueError("Artifact contains private or external runtime data")
    return paths


def verify_artifact(directory, lock, output, *, make_zip=False):
    locked = verify_lock(lock)
    internal = directory / "_internal"
    info_path = internal / "build-info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info["source_digest"] != source_digest() or info["dependency_lock_digest"] != digest(lock) or info["target"] != locked["target"]:
        raise ValueError("Artifact does not match the current source and dependency lock")
    if not (internal / "LICENSE").is_file() or digest(internal / "LICENSE") != digest(ROOT / "LICENSE"):
        raise ValueError("Application license is missing or differs from source")
    for source, destination in bundled_resources(ROOT):
        source = Path(source)
        expected = internal / destination / source.name
        if not expected.is_file() or digest(source) != digest(expected):
            raise ValueError(f"Bundled resource differs: {source.name}")
    executable = directory / ("WorkLogger.exe" if sys.platform == "win32" else "WorkLogger")
    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM="offscreen", WORKLOGGER_LANG="en_US")
    checks = []
    for option in ("--smoke-import", "--smoke-startup", "--smoke-workflows"):
        completed = subprocess.run([str(executable), option], cwd=directory, env=environment, timeout=180, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(f"Artifact check failed: {option}")
        checks.append(option)
    paths = artifact_files(directory)
    report = {"format_version": 1, "build": info, "checks": checks, "files": {
        path.relative_to(directory).as_posix(): digest(path) for path in paths}}
    output.parent.mkdir(parents=True, exist_ok=True)
    if make_zip:
        archive = output.with_suffix(".zip")
        temporary = archive.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
                for path in paths:
                    bundle.write(path, Path(directory.name) / path.relative_to(directory))
            os.replace(temporary, archive)
            report["archive"] = {"name": archive.name, "sha256": digest(archive)}
        finally:
            temporary.unlink(missing_ok=True)
    with atomic_destination(output) as temporary:
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, default=ROOT / "dist/WorkLogger")
    parser.add_argument("--output", type=Path, default=ROOT / "release/WorkLogger-windows.json")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--zip", action="store_true")
    args = parser.parse_args()
    verify_lock(args.lock.resolve())
    if args.build:
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"], cwd=ROOT, check=True)
        arguments = [sys.executable, str(ROOT / "scripts/build.py"), "--lock", str(args.lock.resolve())]
        if "requirements-ai.txt" in verify_lock(args.lock.resolve())["inputs"]:
            arguments.append("--with-local-inference")
        subprocess.run(arguments, cwd=ROOT, check=True)
    verify_artifact(args.artifact.resolve(), args.lock.resolve(), args.output.resolve(), make_zip=args.zip)
    print("Artifact verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
