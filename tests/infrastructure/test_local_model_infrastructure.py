from __future__ import annotations

import hashlib
from dataclasses import fields
import json
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from worklogger.app.ports import AIRequest
from worklogger.domain.local_model.models import LocalModelEntry
from worklogger.infrastructure.ai.local import LocalModelGateway, strip_thinking
from worklogger.infrastructure.local_model import JsonLocalModelStore, bundled_model_catalog_path, sha256_of_file
from worklogger.infrastructure.local_model.catalog import model_entry_from_mapping


class FakeResponse:
    def __init__(self, payload: bytes, status=200, headers=None) -> None:
        self._payload = payload
        self._offset = 0
        self.status = status
        self.headers = headers or {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        chunk = self._payload[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


class LocalModelInfrastructureTests(unittest.TestCase):
    def test_remote_catalog_cannot_replace_bundled_model_identity_or_filename(self):
        bundled_entry = {"id": "bundled", "filename": "trusted.gguf", "sha256": "a" * 64,
                         "download_url": "https://trusted.example/model.gguf"}
        remote = {"models": [{**bundled_entry, "download_url": "https://changed.example/model.gguf", "sha256": "b" * 64},
                             {**bundled_entry, "id": "alias"}, {"id": "additional", "filename": "additional.gguf"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.json"
            bundled.write_text(json.dumps({"models": [bundled_entry]}), encoding="utf-8")
            store = JsonLocalModelStore(root / "models", bundled_catalog_path=bundled,
                remote_catalog_url="https://catalog.example/models.json",
                catalog_opener=lambda *_args, **_kwargs: FakeResponse(json.dumps(remote).encode()))
            result = store.refresh_catalog()
            self.assertTrue(result.ok, result.error)
            entries = {entry.id: entry for entry in result.value}
            self.assertEqual(set(entries), {"bundled", "additional"})
            self.assertEqual(entries["bundled"].sha256, bundled_entry["sha256"])
            self.assertEqual(entries["bundled"].download_url, bundled_entry["download_url"])

    def test_completed_partial_download_is_verified_without_downloading_again_after_range_rejection(self):
        from unittest.mock import Mock
        from worklogger.infrastructure.local_model.download import HttpRangeDownloader
        payload = b"GGUF" + b"verified model"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            path.with_suffix(".gguf.tmp").write_bytes(payload)
            opener = Mock(side_effect=HTTPError("https://example.test/model.gguf", 416, "range", {}, None))
            result = HttpRangeDownloader(opener=opener).download(url="https://example.test/model.gguf", destination=path,
                expected_sha256=hashlib.sha256(payload).hexdigest())
            self.assertTrue(result.ok, result.error)
            self.assertEqual(path.read_bytes(), payload)
            opener.assert_called_once()

    def test_download_checks_available_space_before_writing_a_response(self):
        from types import SimpleNamespace
        from worklogger.infrastructure.local_model.download import HttpRangeDownloader
        payload = b"GGUF" + b"model"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            downloader = HttpRangeDownloader(opener=lambda *_args, **_kwargs: FakeResponse(payload, headers={"Content-Length": str(len(payload))}))
            with patch("worklogger.infrastructure.local_model.download.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
                result = downloader.download(url="https://example.test/model.gguf", destination=path,
                    expected_sha256=hashlib.sha256(payload).hexdigest())
            self.assertEqual(result.error.code, "local_model_disk_full")
            self.assertFalse(path.exists())

    def test_unknown_length_download_checks_space_before_writing(self):
        from types import SimpleNamespace
        from worklogger.infrastructure.local_model.download import HttpRangeDownloader
        payload = b"GGUF" + b"model"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            downloader = HttpRangeDownloader(opener=lambda *_args, **_kwargs: FakeResponse(payload))
            with patch("worklogger.infrastructure.local_model.download.shutil.disk_usage", return_value=SimpleNamespace(free=1)):
                result = downloader.download(url="https://example.test/model.gguf", destination=path,
                    expected_sha256=hashlib.sha256(payload).hexdigest())
            self.assertEqual(result.error.code, "local_model_disk_full")
            self.assertFalse(path.exists())
            self.assertEqual(path.with_suffix(".gguf.tmp").read_bytes(), b"")

    def test_replaced_download_temporary_file_cannot_redirect_writes(self):
        from worklogger.infrastructure.local_model.download import HttpRangeDownloader
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, destination = root / "retained.txt", root / "model.gguf"
            target.write_bytes(b"Retained content")
            link = destination.with_suffix(".gguf.tmp")
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symbolic links are unavailable on this system")
            link.unlink()
            def open_request(*_args, **_kwargs):
                link.symlink_to(target)
                return FakeResponse(b"replacement")
            result = HttpRangeDownloader(opener=open_request).download(
                url="https://example.test/model.gguf", destination=destination,
                expected_sha256=hashlib.sha256(b"replacement").hexdigest())
            self.assertFalse(result.ok)
            self.assertEqual(target.read_bytes(), b"Retained content")
            self.assertFalse(destination.exists())

    def test_runtime_model_storage_applies_catalog_and_download_timeouts(self):
        from unittest.mock import Mock
        from worklogger.composition.context import build_local_model_store
        from worklogger.infrastructure.network import AccountHTTPTransport
        from worklogger.infrastructure.runtime_config import LocalModelsRuntimeConfiguration

        payload = b"GGUF\x03\x00\x00\x00" + bytes(16) + b"Synthetic model"
        catalog = {"models": [{"id": "configured-model", "filename": "configured.gguf", "status": "stable",
                               "download_url": "https://example.test/configured.gguf",
                               "sha256": hashlib.sha256(payload).hexdigest()}]}
        requests = []
        routes = []
        def opener(request, *, timeout):
            requests.append((request.full_url, timeout))
            content = json.dumps(catalog).encode() if request.full_url.endswith("catalog.json") else payload
            return FakeResponse(content, headers={"Content-Length": str(len(content))})
        def opener_factory(**options):
            routes.append(options)
            return opener
        values = {"network_proxy_enabled": "1", "network_proxy_address": "127.0.0.1", "network_proxy_port": "8080"}
        settings = Mock()
        settings.get_many.side_effect = lambda _user, keys: {key: values[key] for key in keys if key in values}
        transport = AccountHTTPTransport(settings=settings, user_id=1, proxy_password=Mock(), opener_factory=opener_factory)
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict("os.environ", {"WORKLOGGER_MODEL_CATALOG_URL": "https://example.test/catalog.json"}):
            store = build_local_model_store(Path(directory) / "worklog.db",
                transport=transport,
                configuration=LocalModelsRuntimeConfiguration(download_timeout_seconds=19, catalog_timeout_seconds=7))
            self.assertTrue(store.refresh_catalog().ok)
            self.assertTrue(store.download_model("configured-model").ok)
            self.assertEqual(requests, [("https://example.test/catalog.json", 7), ("https://example.test/configured.gguf", 19)])
            self.assertEqual(routes, [dict(public_only=True, allow_redirects=True,
                                           proxy_url="http://127.0.0.1:8080")] * 2)
            values["network_proxy_address"] = "https://invalid-proxy.example"
            self.assertFalse(store.refresh_catalog().ok)
            self.assertEqual(len(requests), 2)

    def test_file_verification_does_not_block_catalog_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.gguf"
            source.write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(16) + b"model")
            store = JsonLocalModelStore(root / "models")
            entry = store.import_model(source).value
            entered, release = threading.Event(), threading.Event()
            results = []
            def hash_file(path, **kwargs):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError()
                return sha256_of_file(path, **kwargs)
            with patch("worklogger.infrastructure.local_model.store.sha256_of_file", side_effect=hash_file):
                worker = threading.Thread(target=lambda: results.append(store.verify_model(entry.id)))
                worker.start()
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertTrue(store.list_models().ok)
                finally:
                    release.set()
                    worker.join(3)
                self.assertFalse(worker.is_alive())
            self.assertTrue(results[0].value.verified)

    def test_download_limits_headers_and_streaming_without_replacing_existing_files(self):
        from worklogger.infrastructure.local_model.store import HttpRangeDownloader
        for options in ({"chunk_size": 0}, {"chunk_size": -1}, {"timeout_seconds": 0},
                        {"timeout_seconds": float("nan")}, {"max_bytes": 0}):
            with self.assertRaisesRegex(ValueError, "local_model_download_limit_invalid"):
                HttpRangeDownloader(**options)
        payload = b"x" * 16
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            path.write_bytes(b"Existing model")
            for headers in ({"Content-Length": "16"}, {}):
                downloader = HttpRangeDownloader(opener=lambda *_args, **_kwargs: FakeResponse(payload, headers=headers),
                                                 max_bytes=8, chunk_size=4)
                result = downloader.download(url="https://example.test/model.gguf", destination=path,
                                             expected_sha256=hashlib.sha256(payload).hexdigest())
                self.assertEqual(result.error.code, "local_model_file_too_large")
                self.assertEqual(path.read_bytes(), b"Existing model")
                self.assertFalse(path.with_suffix(".gguf.tmp").exists())

    def test_catalog_merges_bundled_and_local_entries_and_invalidates_cached_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.json"
            bundled.write_text(json.dumps({"models": [{
                "id": "shared", "filename": "shared.gguf", "license": "MIT",
                "description": {"en_US": "Bundled description", "ja_JP": "Localized description"},
            }]}), encoding="utf-8")
            models = root / "models"
            store = JsonLocalModelStore(models, bundled_catalog_path=bundled)
            with patch("worklogger.infrastructure.local_model.catalog.model_entry_from_mapping",
                       wraps=model_entry_from_mapping) as parse:
                for _ in range(3):
                    entry = store.list_models().value[0]
                    self.assertEqual(entry.description, "Bundled description")
                    self.assertEqual(entry.description_translations["ja_JP"], "Localized description")
                    self.assertEqual(entry.license, "MIT")
                    self.assertFalse(store.verify_model(entry.id).value.available)
                self.assertEqual(parse.call_count, 1)
                models.mkdir()
                catalog = models / "catalog.json"
                catalog.write_text(json.dumps({"models": [{"id": "shared", "filename": "replacement.gguf"}]}), encoding="utf-8")
                self.assertEqual(store.list_models().value[0].filename, "shared.gguf")
                catalog.unlink()
                self.assertEqual(store.list_models().value[0].filename, "shared.gguf")
            source = root / "import.gguf"
            source.write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(16) + b"model")
            with patch("worklogger.infrastructure.local_model.store.sha256_of_file", wraps=sha256_of_file) as hashing:
                imported = store.import_model(source).value
                self.assertEqual(hashing.call_count, 1)
                duplicate = store.import_model(source).value
                self.assertEqual(duplicate.id, imported.id)
                self.assertEqual(hashing.call_count, 3)
            restored = JsonLocalModelStore(models, bundled_catalog_path=bundled)
            self.assertEqual({item.id for item in restored.list_models().value}, {"shared", imported.id})
            self.assertTrue(restored.delete_model(imported.id).ok)
            self.assertEqual([item.id for item in restored.list_models().value], ["shared"])
            catalog.write_bytes(b"x" * 128)
            self.assertFalse(JsonLocalModelStore(models, max_catalog_bytes=64).list_models().ok)

    def test_bundled_catalog_matches_the_supported_model_schema(self):
        catalog = bundled_model_catalog_path()
        raw = json.loads(catalog.read_text(encoding="utf-8"))["models"]
        names = {field.name for field in fields(LocalModelEntry)}
        with tempfile.TemporaryDirectory() as directory:
            entries = JsonLocalModelStore(directory, bundled_catalog_path=catalog).list_models().value
            self.assertEqual(len(entries), len(raw))
            self.assertEqual(len({item.id for item in entries}), len(raw))
            for item, data in zip(entries, raw):
                self.assertEqual(set(data), names)
                self.assertRegex(item.download_url, r"^https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/")
                self.assertRegex(item.sha256, r"^[0-9a-f]{64}$")
                self.assertLessEqual(item.max_output_tokens, item.context_length)
                self.assertEqual(set(item.description_translations), {"zh_CN", "zh_TW", "ja_JP", "ko_KR"})

    def test_download_transfer_validation_and_cancellation_preserve_destination(self):
        from worklogger.infrastructure.local_model.store import HttpRangeDownloader

        payload = b"complete model"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "model.gguf"
            destination.write_bytes(b"previous model")
            partial = destination.with_suffix(".gguf.tmp")
            for status, headers, body, succeeds in (
                (200, {"Content-Length": str(len(payload))}, payload, True),
                (206, {"Content-Range": f"bytes 3-{len(payload)-1}/{len(payload)}"}, payload[3:], True),
                (200, {"Content-Length": "100"}, payload, False),
                (206, {"Content-Range": "bytes 1-5/10"}, b"wrong", False),
            ):
                with self.subTest(status=status, headers=headers):
                    destination.write_bytes(b"previous model")
                    partial.write_bytes(payload[:3])
                    result = HttpRangeDownloader(opener=lambda *a, body=body, status=status, headers=headers, **k: FakeResponse(body, status, headers)).download(
                        url="https://example.test/model.gguf", destination=destination, expected_sha256=digest,
                    )
                    self.assertEqual(result.ok, succeeds)
                    self.assertEqual(destination.read_bytes(), payload if succeeds else b"previous model")
            downloader = HttpRangeDownloader(opener=lambda *a, **k: self.fail("Unexpected network request"))
            self.assertFalse(downloader.download(url="https://example.test/model.gguf", destination=destination).ok)
            result = downloader.download(url="https://example.test/model.gguf", destination=destination,
                                         expected_sha256=digest, is_cancelled=lambda: True)
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "job_cancelled")

    def test_model_verification_cache_invalidates_when_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "model.gguf"
            source.write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(16) + b"model")
            store = JsonLocalModelStore(Path(directory) / "models")
            entry = store.import_model(source).value
            with patch("worklogger.infrastructure.local_model.store.sha256_of_file", wraps=sha256_of_file) as hashing:
                self.assertTrue(store.verify_model(entry.id).value.verified)
                self.assertTrue(store.verify_model(entry.id).value.verified)
                self.assertEqual(hashing.call_count, 1)
                (Path(directory) / "models" / entry.filename).write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(16) + b"changed model")
                self.assertFalse(store.verify_model(entry.id).value.verified)
                self.assertEqual(hashing.call_count, 2)

    def test_import_model_creates_catalog_manifest_and_verifies_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demo.gguf"
            source.write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(16) + b"demo")
            store = JsonLocalModelStore(Path(directory) / "models")

            imported = store.import_model(source)

            self.assertTrue(imported.ok)
            assert imported.value is not None
            self.assertEqual(imported.value.sha256, sha256_of_file(source))
            self.assertTrue((Path(directory) / "models" / "catalog.json").exists())
            status = store.verify_model(imported.value.id)
            self.assertTrue(status.ok)
            assert status.value is not None
            self.assertTrue(status.value.verified)

    def test_import_rejects_invalid_headers_without_creating_catalog_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.gguf"
            store = JsonLocalModelStore(root / "models")
            for payload in (b"text file", b"GGUF", b"GGUF" + bytes(20), b"GGUF\x04\x00\x00\x00" + bytes(16)):
                with self.subTest(payload=payload):
                    source.write_bytes(payload)
                    result = store.import_model(source)
                    self.assertEqual(result.error.code, "local_model_file_must_be_gguf")
                    self.assertEqual(store.list_models().value, ())
            for version, order in ((2, "little"), (3, "little"), (3, "big")):
                source.write_bytes(b"GGUF" + version.to_bytes(4, order) + bytes(16))
                self.assertTrue(store.import_model(source).ok)

    def test_catalog_failures_preserve_cached_models_and_return_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            models_dir = Path(directory) / "models"
            cached = {
                "models": [
                    {
                        "id": "cached",
                        "display_name": "Cached",
                        "filename": "cached.gguf",
                        "status": "stable",
                    }
                ]
            }
            models_dir.mkdir()
            (models_dir / "catalog.json").write_text(
                json.dumps(cached),
                encoding="utf-8",
            )

            def failing_opener(*args: object, **kwargs: object) -> FakeResponse:
                raise OSError("offline")

            store = JsonLocalModelStore(
                models_dir,
                remote_catalog_url="https://example.test/catalog.json",
                catalog_opener=failing_opener,
            )
            result = store.refresh_catalog()

            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "local_model_catalog_failed")
            self.assertEqual(store.list_models().value[0].id, "cached")
            (models_dir / "catalog.json").write_text("invalid json", encoding="utf-8")
            for operation in (store.verify_model, store.download_model, store.delete_model):
                self.assertFalse(operation("cached").ok)

    def test_download_model_uses_downloader_and_verifies_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            models_dir = Path(directory) / "models"
            payload = b"downloaded gguf"
            digest = hashlib.sha256(payload).hexdigest()
            catalog = {
                "models": [
                    {
                        "id": "remote",
                        "display_name": "Remote",
                        "filename": "remote.gguf",
                        "status": "stable",
                        "download_url": "https://example.test/remote.gguf",
                        "sha256": digest,
                    }
                ]
            }
            models_dir.mkdir()
            (models_dir / "catalog.json").write_text(
                json.dumps(catalog),
                encoding="utf-8",
            )

            def opener(*args: object, **kwargs: object) -> FakeResponse:
                return FakeResponse(payload, headers={"Content-Length": str(len(payload))})

            from worklogger.infrastructure.local_model.store import HttpRangeDownloader

            store = JsonLocalModelStore(
                models_dir,
                downloader=HttpRangeDownloader(opener=opener),
            )
            progress = []
            result = store.download_model("remote", progress=progress.append)

            self.assertTrue(result.ok)
            self.assertEqual((models_dir / "remote.gguf").read_bytes(), payload)
            self.assertEqual(progress[0].received_bytes, 0)
            self.assertEqual(progress[0].total_bytes, len(payload))
            self.assertEqual(progress[-1].operation, "verification")
            self.assertEqual(progress[-1].received_bytes, len(payload))

    def test_downloader_recovers_from_http_416_by_resetting_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            from worklogger.infrastructure.local_model.store import HttpRangeDownloader

            destination = Path(directory) / "remote.gguf"
            destination.with_suffix(".gguf.tmp").write_bytes(b"stale")
            payload = b"fresh payload"
            calls: list[str | None] = []

            def opener(request: object, **kwargs: object) -> FakeResponse:
                range_header = request.get_header("Range")
                calls.append(range_header)
                if range_header:
                    raise HTTPError(
                        request.full_url,
                        416,
                        "Range Not Satisfiable",
                        hdrs=None,
                        fp=None,
                    )
                return FakeResponse(payload)

            result = HttpRangeDownloader(opener=opener).download(
                url="https://example.test/remote.gguf",
                destination=destination,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )

            self.assertTrue(result.ok)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(calls[0], "bytes=5-")

    def test_local_gateway_adds_no_think_and_strips_reasoning(self) -> None:
        seen: dict[str, object] = {}

        def generator(messages: tuple[dict[str, str], ...], max_tokens: int) -> str:
            seen["messages"] = messages
            seen["max_tokens"] = max_tokens
            return "<think>hidden</think>\nFinal answer: visible"

        for model_id, name, needs_directive in (
            ("qwen3_demo", "Qwen3 Demo", True),
            ("qwen3_4b_instruct_2507_q4", "Qwen3-4B-Instruct-2507", False),
            ("qwen35_4b_q4", "Qwen3.5-4B", False),
            ("qwen25_7b_instruct_q4", "Qwen2.5-7B-Instruct", False),
        ):
            gateway = LocalModelGateway(generator=generator, model_id=model_id,
                                        catalog_entry={"display_name": name}, max_output_tokens=123)
            result = gateway.generate(AIRequest(messages=({"role": "user", "content": "hello"},),
                                                model="local", timeout_seconds=1))
            self.assertTrue(result.ok)
            self.assertEqual(result.value.text, "visible")
            self.assertEqual("/no_think" in seen["messages"][-1]["content"], needs_directive)
        self.assertEqual(strip_thinking("<thinking>x</thinking>answer"), "answer")
        for marker in ("<think>", "< thinking >", "<|begin_of_thought|>"):
            self.assertEqual(strip_thinking(marker + "truncated reasoning"), "")
            self.assertEqual(strip_thinking("visible" + marker + "truncated reasoning"), "visible")
        self.assertEqual(strip_thinking("orphan reasoning</think>Final answer: visible"), "visible")


if __name__ == "__main__":
    unittest.main()
