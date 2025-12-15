"""
FastAPI router exposing metadata APIs for the S3 proxy layer.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
import sqlite3
from typing import Optional

from . import hash_utils, models
from .db import (
    get_db,
    insert_replication_job,
    list_replication_jobs,
    fetch_pending_jobs,
    mark_job_success,
    mark_job_failure,
    upsert_tenant_credentials,
    fetch_tenant_by_access_key,
)
from .admin import require_admin

router = APIRouter(prefix="/proxy", tags=["proxy-metadata"])


@router.post(
    "/buckets",
    response_model=models.BucketMappingResponse,
    dependencies=[Depends(require_admin)],
)
def create_bucket_mapping(
    payload: models.BucketMappingRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.BucketMappingResponse:
    """Create or update bucket mappings for a tenant."""

    mapping = hash_utils.map_backends(
        customer_id=payload.customer_id,
        region_id=payload.region_id,
        logical_name=payload.logical_name,
        backend_ids=payload.backend_ids,
    )

    cursor = conn.cursor()
    for backend_id, backend_bucket in mapping.items():
        cursor.execute(
            """
            INSERT INTO bucket_mappings (customer_id, region_id, logical_name, backend_id, backend_bucket)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(customer_id, logical_name, backend_id)
            DO UPDATE SET region_id=excluded.region_id, backend_bucket=excluded.backend_bucket
            """,
            (payload.customer_id, payload.region_id, payload.logical_name, backend_id, backend_bucket),
        )
    conn.commit()
    return models.BucketMappingResponse(
        customer_id=payload.customer_id,
        logical_name=payload.logical_name,
        region_id=payload.region_id,
        backend_mapping=mapping,
    )


@router.get(
    "/buckets/{customer_id}/{logical_name}",
    response_model=models.BucketMappingResponse,
    dependencies=[Depends(require_admin)],
)
def get_bucket_mapping(
    customer_id: str,
    logical_name: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.BucketMappingResponse:
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT region_id, backend_id, backend_bucket
        FROM bucket_mappings
        WHERE customer_id = ? AND logical_name = ?
        """,
        (customer_id, logical_name),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Bucket mapping not found")

    backend_map = {row["backend_id"]: row["backend_bucket"] for row in rows}
    region_id = rows[0]["region_id"]
    return models.BucketMappingResponse(
        customer_id=customer_id,
        logical_name=logical_name,
        region_id=region_id,
        backend_mapping=backend_map,
    )


@router.post(
    "/objects",
    response_model=models.ObjectMetadataResponse,
    dependencies=[Depends(require_admin)],
)
def create_object_metadata(
    payload: models.ObjectMetadataRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.ObjectMetadataResponse:
    """Store metadata for an object, referencing the hashed bucket mapping."""
    cursor = conn.cursor()
    mapping = cursor.execute(
        """
        SELECT id, backend_bucket
        FROM bucket_mappings
        WHERE customer_id = ? AND logical_name = ? AND backend_id = ?
        """,
        (payload.customer_id, payload.logical_name, payload.backend_id),
    ).fetchone()
    if mapping is None:
        raise HTTPException(status_code=404, detail="Bucket mapping not found")

    cursor.execute(
        """
        INSERT INTO object_metadata
        (bucket_mapping_id, object_key, size, etag, encrypted_key, residency, replica_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            mapping["id"],
            payload.object_key,
            payload.size,
            payload.etag,
            payload.encrypted_key,
            payload.residency,
            payload.replica_count,
        ),
    )
    conn.commit()
    new_id = cursor.lastrowid
    stored = cursor.execute(
        "SELECT created_at FROM object_metadata WHERE id = ?", (new_id,)
    ).fetchone()

    jobs_created: list[models.ReplicationJobResponse] = []
    for target in payload.targets or []:
        job_row = insert_replication_job(conn, new_id, target)
        jobs_created.append(
            models.ReplicationJobResponse(
                id=job_row["id"],
                object_id=job_row["object_metadata_id"],
                target_backend=job_row["target_backend"],
                status=job_row["status"],
                attempts=job_row["attempts"],
                last_error=job_row["last_error"],
                customer_id=job_row["customer_id"],
                logical_name=job_row["logical_name"],
                created_at=job_row["created_at"],
            )
        )
    return models.ObjectMetadataResponse(
        id=new_id,
        customer_id=payload.customer_id,
        logical_name=payload.logical_name,
        backend_id=payload.backend_id,
        backend_bucket=mapping["backend_bucket"],
        object_key=payload.object_key,
        size=payload.size,
        etag=payload.etag,
        encrypted_key=payload.encrypted_key,
        residency=payload.residency,
        replica_count=payload.replica_count,
        created_at=stored["created_at"] if stored else "",
        jobs_created=jobs_created,
    )


@router.get(
    "/objects/{customer_id}/{logical_name}",
    response_model=models.ObjectListResponse,
    dependencies=[Depends(require_admin)],
)
def list_object_metadata(
    customer_id: str,
    logical_name: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.ObjectListResponse:
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT om.id, om.object_key, om.size, om.etag, om.encrypted_key, om.residency,
               om.replica_count, om.created_at, bm.backend_id, bm.backend_bucket
        FROM object_metadata om
        JOIN bucket_mappings bm ON om.bucket_mapping_id = bm.id
        WHERE bm.customer_id = ? AND bm.logical_name = ?
        """,
        (customer_id, logical_name),
    ).fetchall()

    objects = []
    for row in rows:
        objects.append(
            models.ObjectMetadataResponse(
                id=row["id"],
                customer_id=customer_id,
                logical_name=logical_name,
                backend_id=row["backend_id"],
                backend_bucket=row["backend_bucket"],
                object_key=row["object_key"],
                size=row["size"],
                etag=row["etag"],
                encrypted_key=row["encrypted_key"],
                residency=row["residency"],
                replica_count=row["replica_count"],
                created_at=row["created_at"],
            )
        )

    return models.ObjectListResponse(
        customer_id=customer_id,
        logical_name=logical_name,
        objects=objects,
    )


def _row_to_job_response(row: sqlite3.Row) -> models.ReplicationJobResponse:
    return models.ReplicationJobResponse(
        id=row["id"],
        object_id=row["object_metadata_id"],
        source_backend=row["source_backend_id"],
        target_backend=row["target_backend"],
        status=row["status"],
        attempts=row["attempts"],
        last_error=row["last_error"],
        customer_id=row["customer_id"],
        logical_name=row["logical_name"],
        created_at=row["created_at"],
    )


@router.post(
    "/jobs",
    response_model=models.ReplicationJobResponse,
    dependencies=[Depends(require_admin)],
)
def create_replication_job(
    payload: models.ReplicationJobRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.ReplicationJobResponse:
    row = insert_replication_job(conn, payload.object_id, payload.target_backend)
    return _row_to_job_response(row)


@router.get(
    "/jobs",
    response_model=models.ReplicationJobListResponse,
    dependencies=[Depends(require_admin)],
)
def list_replication_jobs_endpoint(
    status: Optional[str] = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.ReplicationJobListResponse:
    rows = list_replication_jobs(conn, status=status)
    return models.ReplicationJobListResponse(jobs=[_row_to_job_response(row) for row in rows])


@router.post(
    "/credentials",
    response_model=models.TenantCredentialResponse,
    dependencies=[Depends(require_admin)],
)
def create_tenant_credentials(
    payload: models.TenantCredentialRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> models.TenantCredentialResponse:
    upsert_tenant_credentials(conn, payload.customer_id, payload.access_key, payload.secret_key)
    row = fetch_tenant_by_access_key(conn, payload.access_key)
    return models.TenantCredentialResponse(
        customer_id=row["customer_id"],
        access_key=row["access_key"],
        created_at=row["created_at"],
    )


@router.get(
    "/credentials/{access_key}",
    response_model=models.TenantCredentialResponse,
    dependencies=[Depends(require_admin)],
)
def get_tenant_credentials(access_key: str, conn: sqlite3.Connection = Depends(get_db)):
    row = fetch_tenant_by_access_key(conn, access_key)
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")
    return models.TenantCredentialResponse(
        customer_id=row["customer_id"],
        access_key=row["access_key"],
        created_at=row["created_at"],
    )
