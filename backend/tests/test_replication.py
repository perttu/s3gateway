import os
import tempfile
import io

import pytest

from app import db as db_module
from app import models, proxy_meta, replication
from app import backend_clients


@pytest.fixture()
def conn(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "metadata.db")
        monkeypatch.setenv("PROXY_METADATA_DB_PATH", path)
        db_module.init_db()
        connection = db_module.get_connection()
        try:
            yield connection
        finally:
            connection.close()
        monkeypatch.delenv("PROXY_METADATA_DB_PATH", raising=False)


def create_bucket_and_object(conn):
    mapping = proxy_meta.create_bucket_mapping(
        models.BucketMappingRequest(
            customer_id="tenant",
            region_id="fi",
            logical_name="logs",
            backend_ids=["cluster-a", "cluster-b"],
        ),
        conn=conn,
    )
    response = proxy_meta.create_object_metadata(
        models.ObjectMetadataRequest(
            customer_id="tenant",
            logical_name="logs",
            backend_id="cluster-a",
            object_key="foo.txt",
            size=100,
            etag="etag",
        ),
        conn=conn,
    )
    return response.id, mapping.backend_mapping


class StubClient:
    def __init__(self):
        self.storage = {}

    def get_object(self, Bucket, Key):
        data = self.storage.get((Bucket, Key))
        if data is None:
            raise RuntimeError("missing object")
        return {"Body": io.BytesIO(data), "ContentType": "text/plain"}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.storage[(Bucket, Key)] = Body


@pytest.fixture()
def stub_clients(monkeypatch):
    clients = {"cluster-a": StubClient(), "cluster-b": StubClient()}

    def fake_get_client(backend_id: str):
        return clients[backend_id]

    monkeypatch.setattr(backend_clients, "get_client", fake_get_client)
    return clients


def test_create_job_and_process_success(conn, stub_clients):
    object_id, mapping = create_bucket_and_object(conn)
    source_bucket = mapping["cluster-a"]
    target_bucket = mapping["cluster-b"]
    stub_clients["cluster-a"].storage[(source_bucket, "foo.txt")] = b"hello"

    proxy_meta.create_replication_job(
        models.ReplicationJobRequest(object_id=object_id, target_backend="cluster-b"),
        conn=conn,
    )

    count = replication.process_pending_jobs(conn)
    assert count == 1
    assert stub_clients["cluster-b"].storage[(target_bucket, "foo.txt")] == b"hello"


def test_job_failure_marks_status(conn):
    object_id, _ = create_bucket_and_object(conn)
    proxy_meta.create_replication_job(
        models.ReplicationJobRequest(object_id=object_id, target_backend="cluster-c"),
        conn=conn,
    )

    def handler(_conn, _job):
        raise RuntimeError("boom")

    replication.process_pending_jobs(conn, handler)
    rows = db_module.list_replication_jobs(conn, status="failed")
    assert len(rows) == 1
    assert rows[0]["last_error"] == "boom"
