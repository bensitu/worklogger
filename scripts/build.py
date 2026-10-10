"""Compile catalogs, validate resources, and build the desktop application."""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_resources import bundled_resources
from scripts.i18n.catalog_tools import compile_po_to_mo, locale_po_paths
from scripts.lock_environment import verify_lock
from scripts.release_artifact import write_build_info


def build_environment(console: bool, with_local_inference: bool = False) -> dict[str, str]:
    environment = os.environ.copy()
    environment["WORKLOGGER_BUILD_CONSOLE"] = "1" if console else "0"
    environment["WORKLOGGER_BUILD_LOCAL_INFERENCE"] = "1" if with_local_inference else "0"
    if sys.platform == "win32":
        python_root = Path(sys.executable).parent
        windows_root = Path(environment.get("SystemRoot", r"C:\Windows"))
        # Avoid collecting incompatible DLLs from unrelated tools on PATH.
        environment["PATH"] = os.pathsep.join(str(path) for path in (
            python_root, python_root / "Scripts", windows_root / "System32", windows_root,
        ))
    return environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without running PyInstaller")
    parser.add_argument("--console", action="store_true", help="Build with a console for smoke checks")
    parser.add_argument("--with-local-inference", action="store_true", help="Include optional native inference libraries")
    parser.add_argument("--lock", type=Path, help="Require the exact target-specific dependency environment")
    args = parser.parse_args()
    if args.lock is not None:
        lock = verify_lock(args.lock.resolve())
        if args.with_local_inference and "requirements-ai.txt" not in lock["inputs"]:
            parser.error("Native inference must be included in the dependency lock.")
    for path in locale_po_paths():
        compile_po_to_mo(path)
    subprocess.run([sys.executable, str(ROOT / "scripts/i18n/i18n_check.py")], cwd=ROOT, check=True)
    resources = bundled_resources(ROOT)
    print(f"Validated {len(resources)} bundled resource files.")
    required = ("PySide6", "tzlocal", "tzdata", "holidays", "cryptography", "keyring", "certifi", "jwt", "icalendar", "recurring_ical_events", "portalocker", "openpyxl", "et_xmlfile")
    if args.with_local_inference:
        required += ("llama_cpp",)
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        parser.error(f"Missing runtime dependencies: {', '.join(missing)}")
    if args.check:
        return 0
    if importlib.util.find_spec("PyInstaller") is None:
        parser.error("PyInstaller is required. Install requirements-build.txt first.")
    write_build_info(ROOT / "build/build-info.json", args.lock, local_inference=args.with_local_inference)
    environment = build_environment(args.console, args.with_local_inference)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "WorkLogger.spec")],
        cwd=ROOT, env=environment, check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
