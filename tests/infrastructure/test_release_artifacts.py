"""Distribution resource integrity and archive compatibility checks."""

from pathlib import Path
from contextlib import redirect_stderr
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import release_artifact
from scripts.lock_environment import digest
from worklogger.__about__ import APP_ID, APP_VERSION


class ReleaseArtifactTests(unittest.TestCase):
    def test_process_failure_reports_exit_code_and_redacted_diagnostics(self):
        log = self.root / "application.log"
        log.write_text("startup_failed password=synthetic-private-value", encoding="utf-8")
        output = io.StringIO()
        completed = subprocess.CompletedProcess([], -6, stdout=b"Starting application",
                                                stderr=b"access_token=synthetic-token-value")
        with patch.object(release_artifact.subprocess, "run", return_value=completed), redirect_stderr(output):
            with self.assertRaisesRegex(RuntimeError, "exit code -6"):
                release_artifact._run_artifact_check(self.artifact, "--smoke-startup", label="startup",
                    directory=self.root, environment={"WORKLOGGER_LOG_PATH": str(log)})
        self.assertIn("Starting application", output.getvalue())
        self.assertIn("startup_failed", output.getvalue())
        self.assertNotIn("synthetic-private-value", output.getvalue())
        self.assertNotIn("synthetic-token-value", output.getvalue())

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "LICENSE").write_text("Synthetic license", encoding="utf-8")
        self.resource = self.source / "icon.svg"
        self.resource.write_text("<svg/>", encoding="utf-8")
        self.lock = self.root / "target.lock.json"
        self.lock.write_text("{}", encoding="utf-8")
        self.artifact = self.root / "WorkLogger"
        self.internal = self.artifact / "_internal"
        self.internal.mkdir(parents=True)
        (self.internal / "LICENSE").write_bytes((self.source / "LICENSE").read_bytes())
        (self.internal / "icon.svg").write_bytes(self.resource.read_bytes())
        self.info = {"application_version": APP_VERSION, "local_inference": True, "source_digest": "synthetic-source",
                     "dependency_lock_digest": digest(self.lock), "target": {"system": "fixture"}}
        self.write_info()
        self.output = self.root / "release/WorkLogger.json"
        self.enterContext(patch.object(release_artifact, "ROOT", self.source))
        self.enterContext(patch.object(release_artifact, "verify_lock", return_value={"target": self.info["target"]}))
        self.enterContext(patch.object(release_artifact, "source_digest", return_value="synthetic-source"))
        self.enterContext(patch.object(release_artifact, "bundled_resources", return_value=[(str(self.resource), ".")]))
        self.enterContext(patch.object(release_artifact, "artifact_checks", return_value=["--smoke-import", "--smoke-startup", "--smoke-workflows"]))

    def write_info(self):
        (self.internal / "build-info.json").write_text(json.dumps(self.info), encoding="utf-8")

    def macos_bundle(self):
        bundle = self.root / "WorkLogger.app"
        self.artifact.rename(bundle)
        self.artifact = bundle
        contents = bundle / "Contents"
        contents.mkdir()
        self.internal = contents / "Resources"
        (bundle / "_internal").rename(self.internal)
        executable = contents / "MacOS/WorkLogger"
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": APP_ID, "CFBundleShortVersionString": APP_VERSION,
        }))
        return bundle

    def test_artifact_verification_rejects_changed_resources_and_provenance(self):
        for field in ("application_version", "source_digest", "dependency_lock_digest", "target"):
            with self.subTest(field=field):
                previous = self.info[field]
                self.info[field] = "changed"
                self.write_info()
                with self.assertRaises(ValueError):
                    release_artifact.verify_artifact(self.artifact, self.lock, self.output)
                self.info[field] = previous
                self.write_info()
        (self.internal / "icon.svg").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            release_artifact.verify_artifact(self.artifact, self.lock, self.output)
        self.assertFalse(self.output.exists())

    def test_windows_archive_verifies_extracted_resources_and_records_checksum(self):
        (self.artifact / "WorkLogger.exe").write_bytes(b"Synthetic executable")
        with patch.object(release_artifact.sys, "platform", "win32"):
            report = release_artifact.verify_artifact(self.artifact, self.lock, self.output, make_zip=True)
        archive = self.output.with_suffix(".zip")
        self.assertEqual(report["archive"]["sha256"], digest(archive))
        self.assertEqual(report["archive"]["checks"], report["checks"])
        self.assertEqual(json.loads(self.output.read_text())["files"], report["files"])

    def test_distribution_without_native_inference_cannot_pass_verification(self):
        self.info["local_inference"] = False
        self.write_info()
        with self.assertRaises(ValueError):
            release_artifact.verify_artifact(self.artifact, self.lock, self.output)

    @unittest.skipIf(os.name == "nt", "Symbolic links and POSIX modes require a Unix host")
    def test_unix_archive_preserves_internal_links_and_executable_permissions(self):
        executable = self.artifact / "WorkLogger"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        (self.internal / "icon-link.svg").symlink_to("icon.svg")
        checks = []

        def verify_executable(path, directory, **kwargs):
            self.assertTrue(os.access(path, os.X_OK))
            self.assertTrue((directory / "_internal/icon-link.svg").is_symlink())
            checks.append(path)
            return ["--smoke-import"]

        with patch.object(release_artifact.sys, "platform", "linux"), patch.object(
            release_artifact, "artifact_checks", side_effect=verify_executable
        ):
            report = release_artifact.verify_artifact(self.artifact, self.lock, self.output, make_zip=True)
        self.assertEqual(len(checks), 2)
        self.assertEqual(report["symlinks"], {"_internal/icon-link.svg": "icon.svg"})
        self.assertEqual(report["archive"]["sha256"], digest(self.output.with_suffix(".tar.gz")))

    @unittest.skipIf(os.name == "nt", "Symbolic links require a Unix host")
    def test_artifact_inventory_rejects_external_and_broken_links(self):
        link = self.internal / "linked-data"
        link.symlink_to("../../source", target_is_directory=True)
        with self.assertRaises(ValueError):
            release_artifact.artifact_files(self.artifact)
        link.unlink()
        link.symlink_to("missing")
        with self.assertRaises(ValueError):
            release_artifact.artifact_files(self.artifact)

    def test_failed_archive_verification_does_not_publish_archive_or_report(self):
        (self.artifact / "WorkLogger.exe").write_bytes(b"Synthetic executable")
        with patch.object(release_artifact.sys, "platform", "win32"), patch.object(
            release_artifact, "artifact_checks", side_effect=[["--smoke-import"], RuntimeError("startup_failed")]
        ):
            with self.assertRaises(RuntimeError):
                release_artifact.verify_artifact(self.artifact, self.lock, self.output, make_zip=True)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".zip").exists())
        self.assertFalse(self.output.with_suffix(".zip.tmp").exists())

    def test_macos_verification_rejects_incorrect_bundle_metadata(self):
        bundle = self.macos_bundle()
        (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "different.application", "CFBundleShortVersionString": APP_VERSION,
        }))
        with self.assertRaises(ValueError):
            release_artifact.verify_artifact(bundle, self.lock, self.output)

    def test_macos_verification_rejects_an_unexpected_architecture(self):
        bundle = self.macos_bundle()
        with patch.object(release_artifact.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, stdout="x86_64 arm64\n"
        )):
            with self.assertRaises(ValueError):
                release_artifact.verify_artifact(bundle, self.lock, self.output)

    @unittest.skipUnless(sys.platform == "darwin", "macOS archives require ditto")
    def test_macos_archive_preserves_bundle_layout_and_internal_links(self):
        bundle = self.macos_bundle()
        (self.internal / "icon-link.svg").symlink_to("icon.svg")
        run = subprocess.run

        def native_tools(command, **kwargs):
            if command[0] in {"lipo", "codesign"}:
                return subprocess.CompletedProcess(command, 0, stdout="arm64\n")
            return run(command, **kwargs)

        with patch.object(release_artifact.subprocess, "run", side_effect=native_tools):
            report = release_artifact.verify_artifact(bundle, self.lock, self.output, make_zip=True)
        self.assertEqual(report["symlinks"], {"Contents/Resources/icon-link.svg": "icon.svg"})
        self.assertEqual(report["archive"]["sha256"], digest(self.output.with_suffix(".zip")))
