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


def install_native_dependencies(wheels: Path):
    requirements = ROOT / "requirements-ai.txt"
    entries = [Requirement(line.strip()) for line in requirements.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
    native = next(entry for entry in entries if canonicalize_name(entry.name) == "llama-cpp-python")
    pins = list(native.specifier)
    if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
        raise ValueError("Native inference must specify one exact version")
    wheels.mkdir(parents=True, exist_ok=True)
    if sys.platform == "linux":
        # Build against the target libc; the upstream Linux wheels use musl.
        environment = os.environ | {
            "CMAKE_ARGS": "-DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF "
                          "-DGGML_AVX512=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BACKEND_DL=OFF",
            "CMAKE_BUILD_PARALLEL_LEVEL": "2",
        }
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-binary=llama-cpp-python",
                        "--wheel-dir", str(wheels), str(native)], check=True, env=environment)
    else:
        index = "metal" if sys.platform == "darwin" else "cpu"
        subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
                        "--index-url", f"https://abetlen.github.io/llama-cpp-python/whl/{index}",
                        "--dest", str(wheels), str(native)], check=True)
    matches = compatible_wheels(wheels, native.name, pins[0].version)
    if len(matches) != 1:
        raise ValueError("Expected one compatible native inference wheel")
    subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:",
                    str(matches[0]), "-r", str(requirements)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, default=ROOT / "build/wheels")
    args = parser.parse_args()
    install_native_dependencies(args.wheels.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
