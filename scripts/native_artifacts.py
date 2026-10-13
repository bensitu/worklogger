"""Select and verify approved native dependency distributions before installation."""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename


def select_artifact(manifest, version, *, source=False):
    data = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if data["version"] != version:
        raise ValueError("Native dependency manifest version does not match requirements")
    compatible = set(sys_tags())
    matches = []
    for item in data["artifacts"]:
        name = item["filename"]
        parsed = urlsplit(item["url"])
        if (Path(name).name != name or parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.hostname not in {"github.com", "files.pythonhosted.org"}
                or Path(parsed.path).name != name or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise ValueError("Native dependency manifest contains an invalid artifact")
        if source:
            if name == f"llama_cpp_python-{version}.tar.gz":
                matches.append(item)
        elif name.endswith(".whl"):
            package, wheel_version, _build, tags = parse_wheel_filename(name)
            if canonicalize_name(package) == "llama-cpp-python" and str(wheel_version) == version and tags & compatible:
                matches.append(item)
    if len(matches) != 1:
        raise ValueError("Expected one approved native dependency artifact for this target")
    return matches[0]


def verified_artifact(item, directory, *, opener=urlopen):
    destination = Path(directory) / item["filename"]
    if not destination.exists():
        temporary = destination.with_name(destination.name + ".partial")
        try:
            with opener(Request(item["url"], headers={"User-Agent": "WorkLogger"}), timeout=60) as response:
                with temporary.open("wb") as stream:
                    total = 0
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        total += len(block)
                        if total > 256 * 1024 * 1024:
                            raise ValueError("Native dependency artifact exceeds the size limit")
                        stream.write(block)
            _verify_digest(temporary, item["sha256"])
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    _verify_digest(destination, item["sha256"])
    return destination


def _verify_digest(path, expected):
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise ValueError("Native dependency artifact checksum does not match the approved manifest")
