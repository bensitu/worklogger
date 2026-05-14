from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
import unittest
from urllib.error import HTTPError

from worklogger.app.ports import AIRequest
from worklogger.infrastructure.ai.local import LocalModelGateway, strip_thinking
from worklogger.infrastructure.local_model import JsonLocalModelStore, sha256_of_file


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

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
    def test_import_model_creates_catalog_manifest_and_verifies_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "demo.gguf"
            source.write_bytes(b"GGUF demo")
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

    def test_refresh_catalog_falls_back_to_cached_catalog(self) -> None:
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

            self.assertTrue(result.ok)
            assert result.value is not None
            self.assertEqual(result.value[0].id, "cached")

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
                return FakeResponse(payload)

            from worklogger.infrastructure.local_model.store import HttpRangeDownloader

            store = JsonLocalModelStore(
                models_dir,
                downloader=HttpRangeDownloader(opener=opener),
            )
            result = store.download_model("remote")

            self.assertTrue(result.ok)
            self.assertEqual((models_dir / "remote.gguf").read_bytes(), payload)

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

        gateway = LocalModelGateway(
            generator=generator,
            model_id="qwen3_demo",
            catalog_entry={"display_name": "Qwen3 Demo"},
            max_output_tokens=123,
        )
        result = gateway.generate(
            AIRequest(
                messages=({"role": "user", "content": "hello"},),
                model="local",
                timeout_seconds=1,
            )
        )

        self.assertTrue(result.ok)
        assert result.value is not None
        self.assertEqual(result.value.text, "visible")
        self.assertIn("/no_think", seen["messages"][-1]["content"])
        self.assertEqual(strip_thinking("<thinking>x</thinking>answer"), "answer")


if __name__ == "__main__":
    unittest.main()
