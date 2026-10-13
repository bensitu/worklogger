"""Prepare a checksum-verified small model for native runtime verification."""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.native_artifacts import verified_artifact


def main():
    directory = Path(os.environ.get("RUNNER_TEMP", ROOT / "build")) / "native-verification"
    directory.mkdir(parents=True, exist_ok=True)
    path = verified_artifact({
        "filename": "stories260K.gguf",
        "url": "https://huggingface.co/ggml-org/models/resolve/499bc8821c6b12b4e53c5bffcb21ec206f212d81/tinyllamas/stories260K.gguf",
        "sha256": "270cba1bd5109f42d03350f60406024560464db173c0e387d91f0426d3bd256d",
    }, directory)
    environment_file = os.environ.get("GITHUB_ENV")
    if environment_file:
        with Path(environment_file).open("a", encoding="utf-8") as stream:
            stream.write(f"WORKLOGGER_VERIFY_MODEL_PATH={path.resolve()}\n")
    print(f"Verified native model: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
