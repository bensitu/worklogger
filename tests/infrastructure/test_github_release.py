"""Release provenance, artifact selection and recoverable draft publication."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import github_release, release_assets
from worklogger.__about__ import APP_VERSION

COMMIT = "a" * 40
TAG = f"v{APP_VERSION}"


class MemoryGitHub:
    def __init__(self):
        self.commit = None
        self.release = None
        self.writes = []
        self.uploads = []
        self.fail_upload = None
        self.corrupt_digest = False

    def request(self, path, *, body=None, missing_ok=False, paginate=False):
        if body is not None:
            self.writes.append((path, body))
            if path == "git/refs":
                self.commit = body["sha"]
                return {"object": {"type": "commit", "sha": self.commit}}
            if path == "releases":
                self.release = body | {"id": 7, "assets": [], "html_url": "https://github.com/example/app/releases/tag/" + TAG}
                return deepcopy(self.release)
        if path.startswith("git/ref/tags/"):
            return {"object": {"type": "commit", "sha": self.commit}} if self.commit else None
        if path == "releases?per_page=100":
            return [[deepcopy(self.release)]] if self.release else [[]]
        if path == "releases/7":
            return deepcopy(self.release)
        raise AssertionError(f"Unexpected GitHub request: {path}")

    def upload(self, tag, path):
        self.uploads.append(path.name)
        if self.fail_upload == path.name:
            self.fail_upload = None
            raise RuntimeError("Upload interrupted")
        value = {"name": path.name, "state": "uploaded", "size": path.stat().st_size,
                 "digest": "sha256:" + ("0" * 64 if self.corrupt_digest else release_assets.checksum(path))}
        self.release["assets"] = [asset for asset in self.release["assets"] if asset["name"] != path.name] + [value]


class GitHubReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.builds = self.root / "builds"
        self.output = self.root / "assets"
        self.reports = {}
        for name, (system, machine, extension) in release_assets.TARGETS.items():
            folder = self.builds / name
            folder.mkdir(parents=True)
            prefix = f"WorkLogger-{name}"
            archive = folder / (prefix + extension)
            archive.write_bytes(b"Synthetic verified archive")
            target = {"system": system, "machine": machine, "python": "3.12.7", "implementation": "CPython"}
            packages = [{"name": "llama-cpp-python", "version": "0.3.19", "sha256": "b" * 64}]
            inputs = {filename: hashlib.sha256((release_assets.ROOT / filename).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                      for filename in ("requirements.txt", "requirements-build.txt", "requirements-ai.txt")}
            lock = folder / "target.lock.json"
            lock.write_text(json.dumps({"format_version": 1, "target": target, "inputs": inputs, "packages": packages}), encoding="utf-8")
            (folder / "target.lock.txt").write_text("llama-cpp-python==0.3.19 --hash=sha256:" + "b" * 64 + "\n", encoding="utf-8")
            checks = sorted(release_assets.CHECKS | ({"cocoa-startup"} if system == "Darwin" else set()))
            report = {"format_version": 1, "build": {"format_version": 1, "application_version": APP_VERSION,
                "source_revision": COMMIT, "source_dirty": False, "local_inference": True, "target": target,
                "dependency_lock_digest": release_assets.checksum(lock)}, "checks": checks,
                "archive": {"name": archive.name, "sha256": release_assets.checksum(archive), "checks": checks}}
            report_path = folder / (prefix + ".json")
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.reports[name] = (report_path, report)

    def prepare(self):
        return release_assets.prepare_assets(self.builds, self.output, TAG, COMMIT)

    def test_prepare_keeps_platform_locks_separate_and_checksums_every_release_file(self):
        paths = self.prepare()
        self.assertEqual(len(paths), 13)
        self.assertEqual(set(path.name for path in paths), release_assets.release_names() | {"SHA256SUMS"})
        self.assertEqual(paths, release_assets.validate_assets(self.output, TAG, COMMIT))

    def test_invalid_build_identity_or_verification_creates_no_release_files(self):
        report_path, original = self.reports["Windows-x64"]
        changes = (
            ("source_revision", "c" * 40), ("application_version", "0.0.0"),
            ("source_dirty", True), ("local_inference", False),
            ("target", original["build"]["target"] | {"python": "3.11.9"}),
        )
        for key, value in changes:
            with self.subTest(field=key):
                report = deepcopy(original)
                report["build"][key] = value
                report_path.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.output.exists())
        report = deepcopy(original)
        report["archive"]["checks"] = []
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_missing_changed_or_unexpected_files_cannot_be_published(self):
        self.prepare()
        archive = self.output / "WorkLogger-Windows-x64.zip"
        original = archive.read_bytes()
        for content in (b"changed", b""):
            archive.write_bytes(content)
            with self.assertRaises(ValueError):
                release_assets.validate_assets(self.output, TAG, COMMIT)
        archive.write_bytes(original)
        extra = self.output / "unexpected.txt"
        extra.write_text("Unexpected release file", encoding="utf-8")
        with self.assertRaises(ValueError):
            release_assets.validate_assets(self.output, TAG, COMMIT)
        extra.unlink()
        (self.output / "WorkLogger-Linux-x64.lock.txt").unlink()
        with self.assertRaises(ValueError):
            release_assets.validate_assets(self.output, TAG, COMMIT)

    def test_changed_dependency_input_or_text_lock_is_rejected(self):
        folder = self.builds / "Windows-x64"
        (folder / "target.lock.txt").write_text("llama-cpp-python==0.0.0\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()
        report_path, report = self.reports["Windows-x64"]
        lock_path = folder / "target.lock.json"
        lock = json.loads(lock_path.read_text())
        lock["inputs"]["requirements-ai.txt"] = "0" * 64
        lock_path.write_text(json.dumps(lock), encoding="utf-8")
        report["build"]["dependency_lock_digest"] = release_assets.checksum(lock_path)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_interrupted_upload_resumes_same_draft_and_verifies_server_checksums(self):
        paths = self.prepare()
        client = MemoryGitHub()
        client.fail_upload = paths[2].name
        with self.assertRaises(RuntimeError):
            github_release.publish_draft(client, self.output, TAG, COMMIT)
        self.assertEqual(client.commit, COMMIT)
        self.assertTrue(client.release["draft"])
        url = github_release.publish_draft(client, self.output, TAG, COMMIT)
        self.assertEqual(url, client.release["html_url"])
        self.assertEqual(len(client.release["assets"]), 13)
        self.assertEqual([path for path, _body in client.writes], ["git/refs", "releases"])
        self.assertTrue(client.writes[-1][1]["generate_release_notes"])

    def test_conflicting_tag_and_published_release_are_never_modified(self):
        self.prepare()
        for conflict in ("tag", "published", "immutable", "unexpected_asset"):
            with self.subTest(conflict=conflict):
                client = MemoryGitHub()
                client.commit = "c" * 40 if conflict == "tag" else COMMIT
                client.release = {"id": 7, "tag_name": TAG, "draft": conflict != "published",
                    "immutable": conflict == "immutable", "target_commitish": COMMIT,
                    "assets": [{"name": "manual.txt"}] if conflict == "unexpected_asset" else []}
                with self.assertRaises(ValueError):
                    github_release.publish_draft(client, self.output, TAG, COMMIT)
                self.assertEqual(client.writes, [])
                self.assertEqual(client.uploads, [])

    def test_publication_detects_corrupt_upload_and_mid_upload_release_changes(self):
        self.prepare()
        client = MemoryGitHub()
        client.corrupt_digest = True
        with self.assertRaises(ValueError):
            github_release.publish_draft(client, self.output, TAG, COMMIT)
        client = MemoryGitHub()
        original = client.upload

        def publish_during_upload(tag, path):
            original(tag, path)
            client.release["draft"] = False

        client.upload = publish_during_upload
        with self.assertRaises(ValueError):
            github_release.publish_draft(client, self.output, TAG, COMMIT)
        self.assertEqual(len(client.uploads), 1)

    def test_artifact_selection_recovers_mixed_attempts_and_rejects_wrong_commit_or_expiration(self):
        artifacts = []
        for identifier, platform in enumerate(("Windows-x64", "Linux-x64", "macOS-arm64"), 1):
            artifacts.append({"id": identifier, "name": f"WorkLogger-{platform}-Python-3.12-Attempt-1",
                              "expired": False, "workflow_run": {"head_sha": COMMIT}})
        artifacts.append(artifacts[0] | {"id": 4, "name": "WorkLogger-Windows-x64-Python-3.12-Attempt-2"})
        client = MemoryGitHub()
        with patch.object(client, "request", side_effect=[{"head_sha": COMMIT}, [{"artifacts": artifacts}]]):
            self.assertEqual(github_release.select_artifacts(client, 42, 2, COMMIT, "builds"), {"windows": 4, "linux": 2, "macos": 3})
        with patch.object(client, "request", return_value={"head_sha": "c" * 40}), self.assertRaises(ValueError):
            github_release.select_artifacts(client, 42, 2, COMMIT, "builds")
        artifacts[1]["expired"] = True
        with patch.object(client, "request", side_effect=[{"head_sha": COMMIT}, [{"artifacts": artifacts}]]), self.assertRaises(ValueError):
            github_release.select_artifacts(client, 42, 2, COMMIT, "builds")

    def test_remote_validation_resolves_annotated_tags_and_rejects_other_draft_commits(self):
        client = MemoryGitHub()
        with patch.object(client, "request", side_effect=[{"object": {"type": "tag", "sha": "b" * 40}},
                {"object": {"type": "commit", "sha": COMMIT}}, [[]]]):
            self.assertEqual(github_release.validate_remote(client, TAG, COMMIT), (COMMIT, None))
        client.release = {"tag_name": TAG, "draft": True, "target_commitish": "c" * 40}
        with self.assertRaises(ValueError):
            github_release.validate_remote(client, TAG, COMMIT)

    def test_version_and_commit_validation_rejects_invalid_input(self):
        for tag, commit in (("v0.0.0", COMMIT), (TAG + "; command", COMMIT), (TAG, "main"), (TAG, "")):
            with self.subTest(tag=tag, commit=commit), self.assertRaises(ValueError):
                release_assets.validate_identity(tag, commit)
