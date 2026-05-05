import hashlib
import json
import os
import shutil
import sys
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import services.local_model_service as local_model_service

from services.local_model_service import (
    _sha256_of_file_detailed,
    delete_model_file,
    ensure_catalog,
    load_catalog,
    refresh_catalog_from_remote,
    resolve_model_path,
    validate_model_url,
    verify_model_file_with_reason,
)

OLD_CATALOG_FIELDS = {
    "label",
    "file",
    "url",
    "size_mb",
    "ram_gb",
    "n_ctx",
    "max_tokens",
    "quant",
    "default",
    "hf_repo",
    "desc",
    "pros",
}


class LocalModelVerificationFlowTests(unittest.TestCase):
    def test_root_model_catalog_uses_current_object_format(self):
        with open(Path(PROJECT_ROOT) / "model_catalog.json", encoding="utf-8") as fh:
            catalog = json.load(fh)
        validated = local_model_service.validate_catalog_data(catalog, require_url=True)

        self.assertEqual(validated["default_model_id"], "qwen3_4b_instruct_2507_q4")
        models = validated["models"]
        self.assertEqual(len(models), 5)
        self.assertEqual(len({entry["id"] for entry in models}), 5)
        self.assertEqual(
            [entry["repo_id"] for entry in models],
            [
                "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF",
                "unsloth/Qwen3-8B-GGUF",
                "unsloth/Phi-4-mini-instruct-GGUF",
                "lmstudio-community/Qwen2.5-7B-Instruct-GGUF",
                "unsloth/Qwen3.5-4B-GGUF",
            ],
        )
        self.assertNotIn("schema_version", catalog)
        for entry in models:
            self.assertFalse(OLD_CATALOG_FIELDS.intersection(entry))
            self.assertTrue(entry["filename"].endswith(".gguf"))
            self.assertNotIn("/", entry["filename"])
            self.assertTrue(entry["download_url"].startswith("https://huggingface.co/"))
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                set(entry["description"]),
                {"en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"},
            )

    def _temp_root(self) -> Path:
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts" / "tmp_verify_cases"
        base.mkdir(parents=True, exist_ok=True)
        root = base / f"case_{uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _write_manifest(self, root: Path, file_name: str, sha256: str) -> None:
        manifest = [
            {
                "id": "local",
                "filename": file_name,
                "download_url": "",
                "sha256": sha256,
                "available": True,
            }
        ]
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _catalog_entry(
        self,
        entry_id: str,
        filename: str,
        *,
        download_url: str = "",
        sha256: str = "",
        status: str = "stable",
    ) -> dict:
        is_remote = bool(download_url)
        return {
            "id": entry_id,
            "display_name": entry_id.title(),
            "provider": "huggingface" if is_remote else "",
            "repo_type": "model" if is_remote else "",
            "repo_id": "demo/demo" if is_remote else "",
            "revision": "main" if is_remote else "",
            "filename": filename,
            "file_format": "gguf",
            "quantization": "Q4_K_M" if is_remote else "custom",
            "download_url": download_url,
            "sha256": sha256,
            "estimated_size_mb": 1,
            "min_ram_gb": 1 if is_remote else 0,
            "context_length": 8192,
            "max_output_tokens": 1024,
            "license": "apache-2.0" if is_remote else "custom",
            "status": status,
            "description": {
                lang: entry_id for lang in local_model_service.SUPPORTED_CATALOG_LOCALES
            },
        }

    def _catalog_object(self, *entries: dict) -> dict:
        return {"default_model_id": entries[0]["id"], "models": list(entries)}

    def test_verify_returns_missing_for_absent_file(self):
        root = self._temp_root()
        try:
            self._write_manifest(root, "missing.gguf", "abcd")
            ok, reason = verify_model_file_with_reason(root, "local", timeout_s=1.0)
            self.assertFalse(ok)
            self.assertEqual(reason, "missing")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_verify_returns_hash_mismatch_for_corrupted_file(self):
        root = self._temp_root()
        try:
            model = root / "local.gguf"
            model.write_bytes(b"broken")
            self._write_manifest(root, "local.gguf", "0" * 64)
            ok, reason = verify_model_file_with_reason(root, "local", timeout_s=1.0)
            self.assertFalse(ok)
            self.assertEqual(reason, "hash_mismatch")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_verify_retries_on_timeout_and_then_succeeds(self):
        root = self._temp_root()
        try:
            model = root / "local.gguf"
            model.write_bytes(b"abc")
            expected = hashlib.sha256(b"abc").hexdigest()
            self._write_manifest(root, "local.gguf", expected)

            calls = {"n": 0}

            def _fake_sha(*_args, **_kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    return "", "timeout"
                return expected, "ok"

            with patch("services.local_model_service._sha256_of_file_detailed", side_effect=_fake_sha):
                ok, reason = verify_model_file_with_reason(
                    root, "local", timeout_s=0.01, retries=1
                )
            self.assertTrue(ok)
            self.assertEqual(reason, "ok")
            self.assertEqual(calls["n"], 2)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_verify_returns_cancelled_when_cancel_event_is_set(self):
        root = self._temp_root()
        try:
            model = root / "local.gguf"
            model.write_bytes(b"abc")
            expected = hashlib.sha256(b"abc").hexdigest()
            self._write_manifest(root, "local.gguf", expected)
            evt = threading.Event()
            evt.set()
            ok, reason = verify_model_file_with_reason(
                root, "local", timeout_s=2.0, cancel_event=evt
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "cancelled")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_sha256_reports_permission_denied(self):
        root = self._temp_root()
        try:
            model = root / "local.gguf"
            model.write_bytes(b"abc")
            with patch("builtins.open", side_effect=PermissionError):
                digest, reason = _sha256_of_file_detailed(model)
            self.assertEqual(digest, "")
            self.assertEqual(reason, "permission_denied")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_sha256_reports_progress(self):
        root = self._temp_root()
        try:
            model = root / "local.gguf"
            model.write_bytes(b"x" * (2 << 20))
            seen: list[int] = []
            digest, reason = _sha256_of_file_detailed(
                model,
                progress_cb=lambda p: seen.append(p),
            )
            self.assertEqual(reason, "ok")
            self.assertTrue(digest)
            self.assertTrue(seen)
            self.assertGreaterEqual(max(seen), 100)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_model_filename_rejects_path_traversal(self):
        root = self._temp_root()
        try:
            with self.assertRaises(ValueError):
                resolve_model_path(root, "../outside.gguf")
            with self.assertRaises(ValueError):
                resolve_model_path(root, r"..\outside.gguf")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_model_url_rejects_non_https_and_private_hosts(self):
        self.assertEqual(
            validate_model_url("https://huggingface.co/model.gguf"),
            "https://huggingface.co/model.gguf",
        )
        for url in (
            "http://huggingface.co/model.gguf",
            "file:///tmp/model.gguf",
            "https://localhost/model.gguf",
            "https://127.0.0.1/model.gguf",
            "https://192.168.1.10/model.gguf",
            "https://[::1]/model.gguf",
            "https://huggingface.co/model.gguf\r\nX-Injected: evil",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_model_url(url)

    def test_refresh_catalog_from_remote_validates_and_preserves_custom_entries(self):
        root = self._temp_root()
        try:
            (root / "custom.gguf").write_bytes(b"custom")
            (root / "catalog.json").write_text(
                json.dumps(
                    self._catalog_object(
                        self._catalog_entry(
                            "custom_local",
                            "custom.gguf",
                            status="local",
                        )
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            remote = self._catalog_object(
                self._catalog_entry(
                    "demo",
                    "demo.gguf",
                    download_url="https://huggingface.co/demo/demo/resolve/main/demo.gguf",
                    sha256="0" * 64,
                )
            )

            class _Response:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, _limit):
                    return json.dumps(remote).encode("utf-8")

            with patch("urllib.request.urlopen", return_value=_Response()):
                catalog = refresh_catalog_from_remote(root)

            self.assertEqual([entry["id"] for entry in catalog], ["demo", "custom_local"])
            saved = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual([entry["id"] for entry in saved["models"]], ["demo", "custom_local"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_refresh_catalog_from_remote_passes_ssl_context_and_retries(self):
        root = self._temp_root()
        try:
            remote = self._catalog_object(
                self._catalog_entry(
                    "demo",
                    "demo.gguf",
                    download_url="https://huggingface.co/demo/demo/resolve/main/demo.gguf",
                    sha256="0" * 64,
                )
            )

            class _Response:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, _limit):
                    return json.dumps(remote).encode("utf-8")

            ssl_context = object()
            calls = []

            def _urlopen(request, *, timeout, context):
                calls.append((request, timeout, context))
                if len(calls) == 1:
                    raise urllib.error.URLError("temporary")
                return _Response()

            with patch("urllib.request.urlopen", side_effect=_urlopen), \
                 patch("services.local_model_service.time.sleep") as mock_sleep:
                catalog = refresh_catalog_from_remote(root, ssl_context=ssl_context)

            self.assertEqual([entry["id"] for entry in catalog], ["demo"])
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call[2] is ssl_context for call in calls))
            mock_sleep.assert_called_once()
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_packaged_remote_catalog_file_is_not_used_as_runtime_seed(self):
        root = self._temp_root()
        try:
            models_dir = root / "models"
            remote_seed = [
                {
                    "id": "packaged_seed",
                    "label": "Packaged Seed",
                    "file": "seed.gguf",
                    "url": "https://huggingface.co/demo/seed.gguf",
                }
            ]
            (root / "model_catalog.json").write_text(
                json.dumps(remote_seed, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(local_model_service.sys, "_MEIPASS", str(root), create=True):
                ensure_catalog(models_dir)
                catalog = load_catalog(models_dir)

            self.assertFalse((models_dir / "catalog.json").exists())
            self.assertNotIn("packaged_seed", {entry.get("id") for entry in catalog})
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_refresh_catalog_preserves_downloaded_removed_remote_until_delete(self):
        root = self._temp_root()
        try:
            (root / "legacy.gguf").write_bytes(b"downloaded")
            (root / "catalog.json").write_text(
                json.dumps(
                    self._catalog_object(
                        self._catalog_entry(
                            "legacy",
                            "legacy.gguf",
                            download_url="https://huggingface.co/legacy/legacy/resolve/main/legacy.gguf",
                            sha256="1" * 64,
                        )
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (root / "manifest.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "legacy",
                            "filename": "legacy.gguf",
                            "download_url": "https://huggingface.co/legacy/legacy/resolve/main/legacy.gguf",
                            "sha256": "1" * 64,
                            "available": True,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            remote = self._catalog_object(
                self._catalog_entry(
                    "demo",
                    "demo.gguf",
                    download_url="https://huggingface.co/demo/demo/resolve/main/demo.gguf",
                    sha256="0" * 64,
                )
            )

            class _Response:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, _limit):
                    return json.dumps(remote).encode("utf-8")

            with patch("urllib.request.urlopen", return_value=_Response()):
                catalog = refresh_catalog_from_remote(root)

            self.assertEqual([entry["id"] for entry in catalog], ["demo", "legacy"])
            saved = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
            legacy = next(entry for entry in saved["models"] if entry["id"] == "legacy")
            self.assertTrue(legacy.get("_local_preserved"))

            delete_model_file("legacy", root)

            saved_after_delete = json.loads(
                (root / "catalog.json").read_text(encoding="utf-8")
            )
            self.assertEqual([entry["id"] for entry in saved_after_delete["models"]], ["demo"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_verify_100mb_model_within_5_seconds(self):
        root = self._temp_root()
        try:
            model = root / "bench_100mb.gguf"
            chunk = b"0123456789abcdef" * (1 << 12)  # 64 KiB
            with model.open("wb") as f:
                for _ in range(1600):  # 1600 * 64 KiB = 100 MiB
                    f.write(chunk)

            expected = hashlib.sha256(model.read_bytes()).hexdigest()
            self._write_manifest(root, "bench_100mb.gguf", expected)

            t0 = time.perf_counter()
            ok, reason = verify_model_file_with_reason(
                root,
                "local",
                timeout_s=5.0,
                retries=0,
            )
            elapsed = time.perf_counter() - t0

            self.assertTrue(ok)
            self.assertEqual(reason, "ok")
            self.assertLessEqual(elapsed, 5.0)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

