"""Conditional WebDAV and S3 transfers with bounded, closed response streams."""

from dataclasses import replace
import hashlib
import io
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials
from worklogger.infrastructure.backup.object_stores import WebDAVBackupStore, S3BackupStore
from worklogger.infrastructure.network import AccountHTTPTransport


class Response(io.BytesIO):
    def __init__(self, content=b"", headers=None):
        super().__init__(content)
        self.headers = headers or {}


class WebDAVServer:
    def __init__(self, *, conditional=True):
        self.objects, self.requests, self.responses = {}, [], []
        self.conditional = conditional

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        method, url, headers = request.method, request.full_url, dict(request.header_items())
        current = self.objects.get(url)
        etag = '"' + hashlib.sha256(current).hexdigest() + '"' if current is not None else None
        if method == "GET" and current is None:
            raise HTTPError(url, 404, "not found", {}, io.BytesIO())
        if method == "PUT":
            if self.conditional and ((headers.get("If-none-match") == "*" and current is not None)
                                     or ("If-match" in headers and headers["If-match"] != etag)):
                raise HTTPError(url, 412, "conflict", {}, io.BytesIO())
            self.objects[url] = request.data
        if method == "DELETE":
            self.objects.pop(url, None)
        response = Response(current if method == "GET" else b"", {"ETag": etag} if etag else {})
        self.responses.append(response)
        return response


class CloudObjectStoreTests(unittest.TestCase):
    def test_cloud_transports_apply_account_proxy_without_environment_overrides(self):
        settings, password = Mock(), Mock()
        settings.get_many.return_value = {"network_proxy_enabled": "1", "network_proxy_address": "127.0.0.1",
                                         "network_proxy_port": "8080"}
        server, routes = WebDAVServer(), []
        def opener_factory(**options):
            routes.append(options)
            return server
        transport = AccountHTTPTransport(settings=settings, user_id=1, proxy_password=password, opener_factory=opener_factory)
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://ignored.example:9999", "NO_PROXY": "*"}):
            webdav = WebDAVBackupStore(self.configuration, self.credentials, opener=transport.opener(allow_redirects=False))
            webdav.test_connection()
            self.assertTrue(routes)
            self.assertTrue(all(route == dict(public_only=False, allow_redirects=False,
                                              proxy_url="http://127.0.0.1:8080") for route in routes))
            configuration = replace(self.configuration, provider="s3", bucket="personal-backups")
            for enabled, expected in (("1", {"https": "http://127.0.0.1:8080"}), ("0", {})):
                settings.get_many.return_value["network_proxy_enabled"] = enabled
                store = S3BackupStore(configuration, self.credentials, proxy_url=transport.proxy_url())
                self.addCleanup(store.client.close)
                self.assertEqual(store.client.meta.config.proxies, expected)
        password.load.assert_not_called()

    def setUp(self):
        self.configuration = BackupConfiguration(endpoint="https://storage.example/webdav", prefix="personal/backups")
        self.credentials = BackupCredentials("synthetic-user", "synthetic-password")

    def test_webdav_checks_conditions_creates_parents_and_never_leaves_response_streams_open(self):
        server = WebDAVServer()
        store = WebDAVBackupStore(self.configuration, self.credentials, opener=server)
        store.test_connection()
        self.assertFalse(server.objects)
        store.put("objects/sample.wlbackup", b"first", expected_etag=None)
        found = store.get("objects/sample.wlbackup", limit=8)
        self.assertEqual(found.data, b"first")
        store.put("objects/sample.wlbackup", b"second", expected_etag=found.etag)
        with self.assertRaisesRegex(ValueError, "cloud_conflict"):
            store.put("objects/sample.wlbackup", b"stale", expected_etag=found.etag)
        with self.assertRaisesRegex(ValueError, "cloud_backup_too_large"):
            store.get("objects/sample.wlbackup", limit=2)
        self.assertTrue(all(response.closed for response in server.responses))
        parents = [request.full_url for request in server.requests if request.method == "MKCOL"]
        self.assertEqual(parents[:2], ["https://storage.example/webdav/personal", "https://storage.example/webdav/personal/backups"])
        self.assertIsNone(store.get("missing", limit=1))

    def test_webdav_rejects_servers_that_ignore_conditional_writes(self):
        server = WebDAVServer(conditional=False)
        with self.assertRaisesRegex(ValueError, "cloud_conditional_unsupported"):
            WebDAVBackupStore(self.configuration, self.credentials, opener=server).test_connection()
        self.assertFalse(server.objects)

    def test_webdav_errors_are_sanitized_and_failed_creation_does_not_delete_objects(self):
        calls = []
        def denied(request, *, timeout):
            calls.append(request.method)
            raise HTTPError(request.full_url, 401, "sensitive-server-details", {}, io.BytesIO())
        store = WebDAVBackupStore(self.configuration, self.credentials, opener=denied)
        with self.assertRaises(ValueError) as failure:
            store.test_connection()
        self.assertNotIn("sensitive", str(failure.exception))
        self.assertNotIn("DELETE", calls)

    def s3(self):
        client = boto3.client("s3", endpoint_url="https://storage.example", region_name="us-east-1",
            aws_access_key_id="synthetic-access", aws_secret_access_key="synthetic-secret")
        self.addCleanup(client.close)
        stubber = self.enterContext(Stubber(client))
        self.addCleanup(stubber.assert_no_pending_responses)
        store = S3BackupStore(replace(self.configuration, provider="s3", bucket="personal-backups"), self.credentials, client=client)
        return store, stubber

    def test_s3_uses_sdk_conditional_parameters_and_bounds_downloads(self):
        store, stubber = self.s3()
        key = {"Bucket": "personal-backups", "Key": "personal/backups/head.json"}
        stubber.add_response("put_object", {}, {**key, "Body": b"first", "ContentType": "application/octet-stream", "IfNoneMatch": "*"})
        store.put("head.json", b"first", expected_etag=None)
        stream = io.BytesIO(b"first")
        stubber.add_response("get_object", {"Body": StreamingBody(stream, 5), "ContentLength": 5, "ETag": '"first"'}, key)
        self.assertEqual(store.get("head.json", limit=5).data, b"first")
        self.assertTrue(stream.closed)
        stubber.add_client_error("put_object", "PreconditionFailed", http_status_code=412,
            expected_params={**key, "Body": b"second", "ContentType": "application/octet-stream", "IfMatch": '"first"'})
        with self.assertRaisesRegex(ValueError, "cloud_conflict"):
            store.put("head.json", b"second", expected_etag='"first"')
        stream = io.BytesIO(b"oversized")
        stubber.add_response("get_object", {"Body": StreamingBody(stream, 9), "ContentLength": 9}, key)
        with self.assertRaisesRegex(ValueError, "cloud_backup_too_large"):
            store.get("head.json", limit=2)
        self.assertTrue(stream.closed)
        stubber.add_client_error("get_object", "NoSuchKey", http_status_code=404, expected_params=key)
        self.assertIsNone(store.get("head.json", limit=5))
