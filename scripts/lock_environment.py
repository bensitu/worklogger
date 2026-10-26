"""Capture and verify complete target-specific build dependencies and wheel hashes."""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]


def target():
    return {"system": platform.system(), "machine": platform.machine(),
            "python": platform.python_version(), "implementation": platform.python_implementation()}


def digest(path):
    if path.suffix == ".txt":
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def input_digest(path):
    if path.suffix == ".json":
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return digest(path)


def read_requirement_files(requirement_files):
    inputs = {}
    visiting = set()

    def visit(path):
        path = Path(path).resolve()
        if path in visiting:
            raise ValueError("Requirement files contain an include cycle")
        if path in inputs:
            return
        visiting.add(path)
        requirements = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if line.startswith("-r "):
                    visit(path.parent / line[3:].strip())
                else:
                    requirements.append(Requirement(line))
        visiting.remove(path)
        inputs[path] = tuple(requirements)

    for path in requirement_files:
        visit(path)
    return inputs


def dependency_closure(requirement_files):
    pending = ["pip", "setuptools"]
    for requirements in read_requirement_files(requirement_files).values():
        for requirement in requirements:
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                if metadata.version(requirement.name) not in requirement.specifier:
                    raise ValueError(f"Installed version does not match {requirement.name}")
                pending.append(requirement.name)
    result = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in result:
            continue
        distribution = metadata.distribution(name)
        result[name] = distribution.version
        for value in distribution.requires or ():
            requirement = Requirement(value)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                if metadata.version(requirement.name) not in requirement.specifier:
                    raise ValueError(f"Unsatisfied dependency: {requirement.name}")
                pending.append(requirement.name)
    return result


def verify_lock(path, *, installed=None, current_target=None):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format_version") != 1 or value["target"] != (current_target or target()):
        raise ValueError("Dependency lock belongs to a different target environment")
    for relative, expected in value["inputs"].items():
        if input_digest(ROOT / relative) != expected:
            raise ValueError(f"Dependency input changed: {relative}")
    installed = installed if installed is not None else {canonicalize_name(d.metadata["Name"]): d.version for d in metadata.distributions()}
    expected = {row["name"]: row["version"] for row in value["packages"]}
    if installed != expected:
        missing = sorted(name for name, version in expected.items() if installed.get(name) != version)
        extra = sorted(set(installed) - set(expected))
        raise ValueError(f"Build environment differs from lock; mismatched: {missing}; extra: {extra}")
    return value


def compatible_wheels(directory, name, version):
    compatible = set(sys_tags())
    matches = []
    for path in directory.glob("*.whl"):
        wheel_name, wheel_version, _build, tags = parse_wheel_filename(path.name)
        if wheel_name == canonicalize_name(name) and str(wheel_version) == version and tags & compatible:
            matches.append(path)
    return matches


def capture_lock(output, requirement_files, wheel_directory):
    versions = dependency_closure(requirement_files)
    wheel_directory.mkdir(parents=True, exist_ok=True)
    missing = [f"{name}=={version}" for name, version in sorted(versions.items())
               if not compatible_wheels(wheel_directory, name, version)]
    if missing:
        subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps", "--dest", str(wheel_directory),
                        *missing], check=True)
    packages = []
    for name, version in sorted(versions.items()):
        matches = compatible_wheels(wheel_directory, name, version)
        if len(matches) != 1:
            raise ValueError(f"Expected one target wheel for {name}")
        packages.append({"name": name, "version": version, "wheel": matches[0].name, "sha256": digest(matches[0])})
    inputs = {path.relative_to(ROOT).as_posix(): input_digest(path)
              for path in read_requirement_files(requirement_files)}
    native_manifest = ROOT / "requirements/native-artifacts.json"
    if native_manifest.exists():
        inputs[native_manifest.relative_to(ROOT).as_posix()] = input_digest(native_manifest)
    value = {"format_version": 1, "target": target(), "inputs": inputs, "packages": packages}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    lines = ["# Target-specific dependencies; verify the adjacent JSON lock before building."]
    lines += [f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}" for row in packages]
    output.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--with-local-inference", action="store_true", default=True,
                        help="Retained for compatibility; distribution locks always include native inference")
    parser.add_argument("--wheels", type=Path, default=ROOT / "build/wheels")
    args = parser.parse_args()
    if args.capture:
        requirements = [ROOT / "requirements.txt", ROOT / "requirements-build.txt"]
        if args.with_local_inference:
            requirements.append(ROOT / "requirements-ai.txt")
        capture_lock(args.lock.resolve(), requirements, args.wheels.resolve())
    else:
        verify_lock(args.lock.resolve())
    print("Dependency lock verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
