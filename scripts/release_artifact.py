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
import tarfile
import tempfile
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
    paths |= {ROOT / "WorkLogger.spec", ROOT / "LICENSE", ROOT / "requirements.txt", ROOT / "requirements-build.txt", ROOT / "requirements-ai.txt"}
    paths |= {Path(source) for source, _destination in bundled_resources(ROOT)}
    value = hashlib.sha256()
    for path in sorted(paths):
        value.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        value.update(bytes.fromhex(digest(path)))
    return value.hexdigest()


def write_build_info(path, lock=None, *, local_inference=True):
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
    paths = []
    root = directory.resolve()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix().lower()
        if path.suffix.lower() in {".db", ".gguf"} or any(token in relative for token in (".db-wal", ".db-shm", ".bak_", ".local.json", "remember_token", "session.json")):
            raise ValueError("Artifact contains private or external runtime data")
        if path.is_symlink():
            if not path.exists() or not path.resolve().is_relative_to(root) or Path(os.readlink(path)).is_absolute():
                raise ValueError("Artifact contains a broken or external symbolic link")
        elif path.is_file():
            paths.append(path)
    return paths


def artifact_checks(executable, directory, *, native_macos=False):
    checks = []
    with tempfile.TemporaryDirectory() as temporary:
        environment = os.environ.copy()
        environment.update(QT_QPA_PLATFORM="offscreen", WORKLOGGER_LANG="en_US",
                           WORKLOGGER_LOG_PATH=str(Path(temporary) / "worklogger.log"))
        for option in ("--smoke-import", "--smoke-startup", "--smoke-workflows", "--smoke-local-model-runtime"):
            completed = subprocess.run([str(executable), option], cwd=temporary, env=environment, timeout=180, capture_output=True)
            if completed.returncode != 0:
                raise RuntimeError(f"Artifact check failed: {option}")
            checks.append(option)
        if native_macos:
            environment["QT_QPA_PLATFORM"] = "cocoa"
            completed = subprocess.run([str(executable), "--smoke-startup"], cwd=temporary,
                                       env=environment, timeout=180, capture_output=True)
            if completed.returncode != 0:
                raise RuntimeError("Artifact check failed: Cocoa startup")
            checks.append("cocoa-startup")
    return checks


def archive_artifact(directory, archive, paths):
    if directory.suffix == ".app":
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(directory), str(archive)], check=True)
    elif sys.platform == "win32":
        if any(path.is_symlink() for path in directory.rglob("*")):
            raise ValueError("Windows ZIP artifacts must not contain symbolic links")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for path in paths:
                bundle.write(path, Path(directory.name) / path.relative_to(directory))
    else:
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(directory, arcname=directory.name)


def verify_artifact(directory, lock, output, *, make_zip=False):
    directory = directory.resolve()
    locked = verify_lock(lock)
    is_macos = directory.suffix == ".app"
    internal = directory / ("Contents/Resources" if is_macos else "_internal")
    info_path = internal / "build-info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("local_inference") is not True or info["application_version"] != APP_VERSION or info["source_digest"] != source_digest() or info["dependency_lock_digest"] != digest(lock) or info["target"] != locked["target"]:
        raise ValueError("Artifact does not match the current source and dependency lock")
    if not (internal / "LICENSE").is_file() or digest(internal / "LICENSE") != digest(ROOT / "LICENSE"):
        raise ValueError("Application license is missing or differs from source")
    for source, destination in bundled_resources(ROOT):
        source = Path(source)
        expected = internal / destination / source.name
        if not expected.is_file() or digest(source) != digest(expected):
            raise ValueError(f"Bundled resource differs: {source.name}")
    executable = directory / ("Contents/MacOS/WorkLogger" if is_macos else
                              "WorkLogger.exe" if sys.platform == "win32" else "WorkLogger")
    paths = artifact_files(directory)
    if is_macos:
        import plistlib
        from worklogger.__about__ import APP_ID
        plist = plistlib.loads((directory / "Contents/Info.plist").read_bytes())
        if plist.get("CFBundleIdentifier") != APP_ID or plist.get("CFBundleShortVersionString") != APP_VERSION:
            raise ValueError("Application bundle metadata differs from source")
        architectures = subprocess.run(["lipo", "-archs", str(executable)], check=True, capture_output=True, text=True).stdout.split()
        if architectures != ["arm64"]:
            raise ValueError("macOS application must contain only the ARM64 architecture")
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(directory)], check=True)
    checks = artifact_checks(executable, directory, native_macos=is_macos)
    report = {"format_version": 1, "build": info, "checks": checks, "files": {
        path.relative_to(directory).as_posix(): digest(path) for path in paths}, "symlinks": {
        path.relative_to(directory).as_posix(): os.readlink(path)
        for path in sorted(directory.rglob("*")) if path.is_symlink()}}
    output.parent.mkdir(parents=True, exist_ok=True)
    if make_zip:
        archive = output.with_suffix(".zip" if is_macos or sys.platform == "win32" else ".tar.gz")
        temporary = archive.with_name(archive.name + ".tmp")
        try:
            archive_artifact(directory, temporary, paths)
            with tempfile.TemporaryDirectory() as verification:
                unpacked = Path(verification)
                if is_macos:
                    subprocess.run(["ditto", "-x", "-k", str(temporary), str(unpacked)], check=True)
                elif sys.platform == "win32":
                    with zipfile.ZipFile(temporary) as bundle:
                        bundle.extractall(unpacked)
                else:
                    with tarfile.open(temporary) as bundle:
                        bundle.extractall(unpacked, filter="data")
                verified = verify_artifact(unpacked / directory.name, lock, unpacked / "verification.json")
                if verified["files"] != report["files"] or verified["symlinks"] != report["symlinks"]:
                    raise ValueError("Archived artifact differs from the verified build")
            os.replace(temporary, archive)
            report["archive"] = {"name": archive.name, "sha256": digest(archive), "checks": verified["checks"]}
        finally:
            temporary.unlink(missing_ok=True)
    with atomic_destination(output) as temporary:
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, default=ROOT / ("dist/WorkLogger.app" if sys.platform == "darwin" else "dist/WorkLogger"))
    parser.add_argument("--output", type=Path, default=ROOT / f"release/WorkLogger-{sys.platform}.json")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--archive", "--zip", dest="zip", action="store_true", help="Create and verify a platform archive")
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
