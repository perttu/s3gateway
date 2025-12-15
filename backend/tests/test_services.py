import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException

from app import services
from app.models import DiscoverySnapshot, SnapshotBucket, SnapshotFile, S3Credentials


def build_bucket(name: str, file_sizes: list[int]) -> SnapshotBucket:
    files = [
        SnapshotFile(
            key=f"{name}-file-{idx}",
            size=size,
            last_modified="2024-01-01T00:00:00Z",
            etag=f"etag-{idx}",
        )
        for idx, size in enumerate(file_sizes)
    ]
    return SnapshotBucket(name=name, files=files, versioning_status="Enabled")


def make_credentials() -> S3Credentials:
    return S3Credentials(
        access_key="test",
        secret_key="secret",
        region="default",
        endpoint_url="https://example.com",
    )


def test_sanitize_snapshot_buckets_enforces_limits(monkeypatch):
    bucket_one = build_bucket("primary", [10, 20, 30])
    bucket_two = build_bucket("secondary", [5])

    monkeypatch.setattr(services, "MAX_SNAPSHOT_BUCKETS", 1)
    monkeypatch.setattr(services, "MAX_FILES_PER_BUCKET", 2)
    monkeypatch.setattr(services, "MAX_SNAPSHOT_FILES", 2)

    sanitized, total_size, total_files = services._sanitize_snapshot_buckets(
        [bucket_one, bucket_two]
    )

    assert len(sanitized) == 1
    assert sanitized[0]["file_count"] == 2
    assert total_size == 30  # 10 + 20 trimmed by caps
    assert total_files == 2
    assert sanitized[0]["files"][0]["key"] == "primary-file-0"


def test_persist_snapshot_writes_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "SNAPSHOTS_DIR", tmp_path)

    snapshot = DiscoverySnapshot(
        endpoint="https://storage.local",
        region="eu",
        buckets=[build_bucket("primary", [42])],
        total_size=42,
        total_files=1,
    )

    metadata = services.persist_snapshot(snapshot)

    assert metadata.bucket_count == 1
    assert metadata.total_files == 1
    assert metadata.total_size == 42

    saved_path = tmp_path / metadata.filename
    assert saved_path.exists()

    payload = json.loads(saved_path.read_text(encoding="utf-8"))
    assert payload["endpoint"] == snapshot.endpoint
    assert payload["region"] == snapshot.region
    assert payload["buckets"][0]["name"] == "primary"


def test_list_buckets_invalid_access_key(monkeypatch):
    error = ClientError(
        {"Error": {"Code": "InvalidAccessKeyId", "Message": "bad key"}},
        "ListBuckets",
    )

    class FakeClient:
        def list_buckets(self):
            raise error

    monkeypatch.setattr(services, "_create_s3_client", lambda _: FakeClient())

    with pytest.raises(HTTPException) as excinfo:
        services.list_buckets(make_credentials())

    assert excinfo.value.status_code == 401
    assert "Invalid access key" in excinfo.value.detail


def test_list_buckets_missing_credentials(monkeypatch):
    def raise_no_creds(_):
        raise NoCredentialsError()

    monkeypatch.setattr(services, "_create_s3_client", raise_no_creds)

    with pytest.raises(HTTPException) as excinfo:
        services.list_buckets(make_credentials())

    assert excinfo.value.status_code == 401
    assert "Invalid credentials" in excinfo.value.detail
