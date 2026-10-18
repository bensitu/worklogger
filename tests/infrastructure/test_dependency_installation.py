"""Resolved wheel identities and hashes used by offline dependency installation."""

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.install_dependencies import wheel_requirements


class DependencyInstallationTests(unittest.TestCase):
    def test_wheel_lock_pins_metadata_identity_and_exact_archive_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "sample-1.2.3-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("sample-1.2.3.dist-info/METADATA", "Name: Sample\nVersion: 1.2.3\n")
                archive.writestr("sample/vendor/dependency-1.0.dist-info/METADATA", "Name: Dependency\nVersion: 1.0\n")
            expected = "sample==1.2.3 --hash=sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest() + "\n"
            self.assertEqual(wheel_requirements(root), expected)
            (root / "unexpected.txt").write_text("Not a wheel", encoding="utf-8")
            with self.assertRaises(ValueError):
                wheel_requirements(root)

    def test_ambiguous_wheel_versions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for version in ("1.0", "2.0"):
                with zipfile.ZipFile(root / f"sample-{version}-py3-none-any.whl", "w") as archive:
                    archive.writestr(f"sample-{version}.dist-info/METADATA", f"Name: Sample\nVersion: {version}\n")
            with self.assertRaisesRegex(ValueError, "more than one wheel"):
                wheel_requirements(root)
