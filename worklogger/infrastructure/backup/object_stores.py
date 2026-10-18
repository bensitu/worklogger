"""Conditional HTTPS object access for WebDAV and S3-compatible storage."""

import base64
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request
from uuid import uuid4

from worklogger.domain.cloud_backup import StoredObject
from worklogger.infrastructure.http import https_opener


def _etag(value):
    if not value or value.startswith("W/") or "\r" in value or "\n" in value:
        raise ValueError("cloud_conditional_unsupported")
    return value


def _key(value):
    if not value or any(part in {"", ".", ".."} for part in value.split("/")) or value.startswith("/"):
        raise ValueError("cloud_backup_invalid")
    return quote(value, safe="/")


class ConditionalObjectStore:
    def test_connection(self):
        name = "probe-" + uuid4().hex
        created = False
        try:
            self.put(name, b"connection-test", expected_etag=None)
            created = True
            found = self.get(name, limit=64)
            if found is None or found.data != b"connection-test":
                raise ValueError("cloud_connection_failed")
            _etag(found.etag)
            for expected in (None, '"unmatched-' + uuid4().hex + '"'):
                try:
                    self.put(name, b"must-not-replace", expected_etag=expected)
                except ValueError as error:
                    if str(error) == "cloud_conflict":
                        continue
                    raise
                raise ValueError("cloud_conditional_unsupported")
        finally:
            if created:
                self.delete(name)


class WebDAVBackupStore(ConditionalObjectStore):
    def __init__(self, configuration, credentials, *, opener=None):
        configuration.validate()
        self._root = configuration.endpoint.rstrip("/") + "/"
        self._prefix = configuration.prefix
        self._open = opener or https_opener(allow_redirects=False)
        self._authorization = "Basic " + base64.b64encode((credentials.username + ":" + credentials.password).encode()).decode()
        self._collections = set()

    def _request(self, method, key, *, data=None, headers=None, limit=0):
        request = Request(self._root + _key(self._prefix + "/" + key), data=data, method=method,
                          headers={"Authorization": self._authorization, **(headers or {})})
        try:
            with self._open(request, timeout=30) as response:
                content = response.read(limit + 1) if limit else b""
                if len(content) > limit:
                    raise ValueError("cloud_backup_too_large")
                return StoredObject(content, response.headers.get("ETag", ""))
        except HTTPError as error:
            status = error.code
            error.close()
            if status == 404 and method in {"GET", "DELETE"}:
                return None
            if status in {409, 412} and method == "PUT":
                raise ValueError("cloud_conflict") from None
            if status == 405 and method == "MKCOL":
                return None
            raise ValueError("cloud_authentication_failed" if status in {401, 403} else "cloud_connection_failed") from None

    def get(self, key, *, limit):
        return self._request("GET", key, limit=limit)

    def _prepare(self, key):
        # MKCOL requires each parent collection to exist before its child.
        parts = (self._prefix + "/" + key).split("/")[:-1]
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            if path in self._collections:
                continue
            request = Request(self._root + _key(path), method="MKCOL", headers={"Authorization": self._authorization})
            try:
                with self._open(request, timeout=30):
                    pass
            except HTTPError as error:
                status = error.code
                error.close()
                if status != 405:
                    raise ValueError("cloud_connection_failed") from None
            self._collections.add(path)

    def put(self, key, data, *, expected_etag):
        self._prepare(key)
        headers = {"Content-Type": "application/octet-stream"}
        headers.update({"If-Match": _etag(expected_etag)} if expected_etag is not None else {"If-None-Match": "*"})
        self._request("PUT", key, data=data, headers=headers)

    def delete(self, key):
        self._request("DELETE", key)


class S3BackupStore(ConditionalObjectStore):
    def __init__(self, configuration, credentials, *, client=None, proxy_url=None):
        configuration.validate()
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client("s3", endpoint_url=configuration.endpoint,
                region_name=configuration.region, aws_access_key_id=credentials.username,
                aws_secret_access_key=credentials.password, aws_session_token=credentials.session_token or None,
                config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=30,
                    proxies={"https": proxy_url} if proxy_url else {},
                    request_checksum_calculation="when_required", response_checksum_validation="when_required",
                    retries={"max_attempts": 2, "mode": "standard"}, s3={"addressing_style": "path"}))
        self.client, self.bucket, self.prefix = client, configuration.bucket, configuration.prefix

    def _call(self, method, key, **kwargs):
        from botocore.exceptions import ClientError
        _key(key)
        try:
            return getattr(self.client, method)(Bucket=self.bucket, Key=self.prefix + "/" + key, **kwargs)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404 and method in {"get_object", "delete_object"}:
                return None
            if status in {409, 412}:
                raise ValueError("cloud_conflict") from None
            raise ValueError("cloud_authentication_failed" if status in {401, 403} else "cloud_connection_failed") from None

    def get(self, key, *, limit):
        response = self._call("get_object", key)
        if response is None:
            return None
        body = response["Body"]
        try:
            if response.get("ContentLength", 0) > limit:
                raise ValueError("cloud_backup_too_large")
            data = body.read(limit + 1)
            if len(data) > limit:
                raise ValueError("cloud_backup_too_large")
            return StoredObject(data, response.get("ETag", ""))
        finally:
            body.close()

    def put(self, key, data, *, expected_etag):
        condition = {"IfMatch": _etag(expected_etag)} if expected_etag is not None else {"IfNoneMatch": "*"}
        self._call("put_object", key, Body=data, ContentType="application/octet-stream",
                   **condition)

    def delete(self, key):
        self._call("delete_object", key)


def backup_store(configuration, credentials, *, opener=None, proxy_url=None):
    if configuration.provider == "webdav":
        return WebDAVBackupStore(configuration, credentials, opener=opener)
    return S3BackupStore(configuration, credentials, proxy_url=proxy_url)
