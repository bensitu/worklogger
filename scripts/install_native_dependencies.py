"""Install the pinned native inference backend for the current build target."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from scripts.lock_environment import compatible_wheels
from scripts.native_artifacts import select_artifact, verified_artifact
from scripts.install_dependencies import install_dependencies


def install_native_dependencies(wheels: Path, *, from_source: bool = False):
    if from_source and sys.platform not in {"linux", "darwin"}:
        raise ValueError("Source builds are supported only on Linux and macOS")
    build_from_source = from_source or sys.platform == "darwin"
    requirements = ROOT / "requirements-ai.txt"
    entries = [Requirement(line.strip()) for line in requirements.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    native = next(entry for entry in entries if canonicalize_name(entry.name) == "llama-cpp-python")
    pins = list(native.specifier)
    if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
        raise ValueError("Native inference must specify one exact version")
    wheels.mkdir(parents=True, exist_ok=True)
    artifact = select_artifact(ROOT / "requirements/native-artifacts.json", pins[0].version,
                               source=build_from_source)
    distribution = verified_artifact(artifact, wheels)
    if build_from_source:
        environment = source_build_environment(sys.platform)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-cache-dir",
                        "--wheel-dir", str(wheels), str(distribution)], check=True, env=environment)
    matches = compatible_wheels(wheels, native.name, pins[0].version) if build_from_source else [distribution]
    if len(matches) != 1:
        raise ValueError("Expected one compatible native inference wheel")
    install_dependencies((requirements,), wheels=(matches[0],), lock_output=ROOT / "build/native-dependencies.lock.txt",
                         constraints=(ROOT / "requirements.txt", ROOT / "requirements-build.txt"))


def source_build_environment(platform):
    environment = os.environ | {"CMAKE_BUILD_PARALLEL_LEVEL": "2"}
    if platform == "darwin":
        environment.update(
            CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_METAL=ON -DCMAKE_OSX_ARCHITECTURES=arm64 "
                       "-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0",
            MACOSX_DEPLOYMENT_TARGET="11.0",
        )
    elif platform == "linux":
        environment["CMAKE_ARGS"] = (
            "-DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_AVX512=OFF "
            "-DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_SSE42=OFF -DGGML_BMI2=OFF -DGGML_BACKEND_DL=OFF"
        )
    else:
        raise ValueError("Source builds are supported only on Linux and macOS")
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, default=ROOT / "build/wheels")
    parser.add_argument("--from-source", action="store_true", help="Build the verified source distribution on Linux or macOS")
    args = parser.parse_args()
    install_native_dependencies(args.wheels.resolve(), from_source=args.from_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
