import os
import tempfile

import pytest
from fastapi import HTTPException

from app import db as db_module
from app import models, proxy_meta


@pytest.fixture()
def db_conn(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "metadata.db")
        monkeypatch.setenv("PROXY_METADATA_DB_PATH", db_path)
        db_module.init_db()
        conn = db_module.get_connection()
        try:
            yield conn
        finally:
            conn.close()
        monkeypatch.delenv("PROXY_METADATA_DB_PATH", raising=False)


def test_create_and_get_bucket_mapping(db_conn):
    request = models.BucketMappingRequest(
        customer_id="tenant-1",
        region_id="fi",
        logical_name="logs",
        backend_ids=["ceph", "minio"],
    )
    response = proxy_meta.create_bucket_mapping(request, conn=db_conn)
    assert response.customer_id == request.customer_id
    assert set(response.backend_mapping.keys()) == set(request.backend_ids)

    retrieved = proxy_meta.get_bucket_mapping(
        request.customer_id, request.logical_name, conn=db_conn
    )
    assert retrieved.backend_mapping == response.backend_mapping


def test_create_and_list_object_metadata(db_conn):
    proxy_meta.create_bucket_mapping(
        models.BucketMappingRequest(
            customer_id="tenant-2",
            region_id="de",
            logical_name="analytics",
            backend_ids=["cluster-a"],
        ),
        conn=db_conn,
    )

    obj_req = models.ObjectMetadataRequest(
        customer_id="tenant-2",
        logical_name="analytics",
        backend_id="cluster-a",
        object_key="foo/bar.csv",
        size=100,
        etag="etag-1",
        encrypted_key="enc",
        residency="DE",
        replica_count=2,
    )
    created = proxy_meta.create_object_metadata(obj_req, conn=db_conn)
    assert created.backend_bucket.startswith("s3gw-")

    listed = proxy_meta.list_object_metadata(obj_req.customer_id, obj_req.logical_name, conn=db_conn)
    assert len(listed.objects) == 1
    assert listed.objects[0].object_key == obj_req.object_key


def test_object_metadata_requires_mapping(db_conn):
    obj_req = models.ObjectMetadataRequest(
        customer_id="tenant-x",
        logical_name="missing",
        backend_id="cluster-a",
        object_key="file.txt",
        size=1,
        etag="etag",
    )
    with pytest.raises(HTTPException):
        proxy_meta.create_object_metadata(obj_req, conn=db_conn)
