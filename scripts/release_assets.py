"""Prepare release files from verified, commit-bound desktop build artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from worklogger.__about__ import APP_VERSION

TARGETS = {
    "Windows-x64": ("Windows", "amd64", ".zip"),
    "Linux-x64": ("Linux", "x86_64", ".tar.gz"),
    "macOS-arm64": ("Darwin", "arm64", ".zip"),
}
CHECKS = {"--smoke-import", "--smoke-startup", "--smoke-workflows", "--smoke-local-model-runtime"}
SIGNATURE_FILES = {"SHA256SUMS.sigstore.json", "SHA256SUMS.provenance.json"}
RELEASE_PYTHON = "3.14"


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_identity(tag, commit):
    if tag != f"v{APP_VERSION}" or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", tag):
        raise ValueError("Release tag must match the application version")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Release commit must be a complete commit SHA")


def release_names():
    return {f"WorkLogger-{name}{suffix}" for name, (_system, _machine, extension) in TARGETS.items()
            for suffix in (extension, ".json", ".lock.json", ".lock.txt")}


def checked_files(directory, tag, commit, *, source_root=ROOT, staged=False):
    validate_identity(tag, commit)
    files = []
    for name, (system, machine, extension) in TARGETS.items():
        source = directory if staged else directory / name
        if source.is_symlink():
            raise ValueError("Release files must not use symbolic links")
        prefix = f"WorkLogger-{name}"
        names = (prefix + extension, prefix + ".json",
                 prefix + ".lock.json" if staged else "target.lock.json",
                 prefix + ".lock.txt" if staged else "target.lock.txt")
        paths = [source / item for item in names]
        if any(path.is_symlink() or not path.is_file() or path.stat().st_size == 0 for path in paths):
            raise ValueError(f"Release files are missing or invalid for {name}")
        archive, report_path, lock_path, text_path = paths
        report = json.loads(report_path.read_text(encoding="utf-8"))
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        build, packaged = report["build"], report["archive"]
        target = build["target"]
        if (report["format_version"] != 1 or lock["format_version"] != 1 or build["format_version"] != 1
                or build["application_version"] != APP_VERSION or build["source_revision"] != commit
                or build["source_dirty"] is not False or build["local_inference"] is not True
                or target["system"] != system or target["machine"].lower() != machine
                or target["python"].split(".")[:2] != RELEASE_PYTHON.split(".") or target["implementation"] != "CPython"
                or lock["target"] != target or build["dependency_lock_digest"] != checksum(lock_path)
                or packaged["name"] != archive.name or packaged["sha256"] != checksum(archive)):
            raise ValueError(f"Release build identity or checksum differs for {name}")
        required = CHECKS | ({"cocoa-startup"} if system == "Darwin" else set())
        if not required.issubset(report["checks"]) or not required.issubset(packaged["checks"]):
            raise ValueError(f"Release runtime verification is incomplete for {name}")
        inputs = lock["inputs"]
        expected_inputs = {"requirements.txt", "requirements-build.txt", "requirements-ai.txt", "requirements/native-artifacts.json"}
        if set(inputs) != expected_inputs:
            raise ValueError("Release dependency lock must include runtime, build and native dependencies")
        for relative, expected in inputs.items():
            data = (source_root / relative).read_bytes().replace(b"\r\n", b"\n")
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"Release dependency input differs: {relative}")
        if not any(row["name"] == "llama-cpp-python" for row in lock["packages"]):
            raise ValueError("Release dependency lock is missing native inference")
        expected_lines = [f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}" for row in lock["packages"]]
        actual_lines = [line for line in text_path.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.startswith("#")]
        if actual_lines != expected_lines:
            raise ValueError("Release dependency lock files disagree")
        files.extend(zip(paths, (prefix + extension, prefix + ".json", prefix + ".lock.json", prefix + ".lock.txt")))
    return files


def prepare_assets(directory, output, tag, commit, *, source_root=ROOT):
    files = checked_files(directory, tag, commit, source_root=source_root)
    output.mkdir(parents=True, exist_ok=False)
    for source, name in files:
        shutil.copyfile(source, output / name)
    lines = [f"{checksum(output / name)}  {name}" for name in sorted(release_names())]
    (output / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
    return validate_assets(output, tag, commit, source_root=source_root)


def validate_assets(directory, tag, commit, *, source_root=ROOT, require_signatures=False):
    files = checked_files(directory, tag, commit, source_root=source_root, staged=True)
    expected = release_names() | {"SHA256SUMS"}
    present = {path.name for path in directory.iterdir()} & SIGNATURE_FILES
    if present or require_signatures:
        if present != SIGNATURE_FILES:
            raise ValueError("Release signatures are missing or incomplete")
        for name in SIGNATURE_FILES:
            path = directory / name
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
                raise ValueError("Release signature file is invalid")
        expected |= SIGNATURE_FILES
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("Release directory contains missing or unexpected files")
    manifest = directory / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Release checksum manifest is invalid")
    lines = [f"{checksum(directory / name)}  {name}" for name in sorted(release_names())]
    if manifest.read_text(encoding="ascii").splitlines() != lines:
        raise ValueError("Release checksum manifest differs from release files")
    return sorted([source for source, _name in files] + [manifest] + [directory / name for name in present])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = prepare_assets(args.input, args.output, args.tag, args.commit)
    print(f"Verified {len(paths)} release files for {args.tag} at {args.commit}")


if __name__ == "__main__":
    main()
