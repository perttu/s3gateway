"""
Simple replication queue processor for the S3 proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol
import sqlite3

from .db import (
    fetch_pending_jobs,
    mark_job_success,
    mark_job_failure,
    fetch_bucket_mapping,
)
from . import backend_clients


@dataclass
class ReplicationJob:
    id: int
    object_id: int
    target_backend: str
    source_backend_id: str
    customer_id: str
    logical_name: str
    backend_bucket: str
    object_key: str
    size: int
    etag: str
    residency: str | None
    attempts: int


class JobHandler(Protocol):
    def __call__(self, conn: sqlite3.Connection, job: ReplicationJob) -> None:
        ...


def replicate_job(conn: sqlite3.Connection, job: ReplicationJob) -> None:
    target_mapping = fetch_bucket_mapping(conn, job.customer_id, job.logical_name, job.target_backend)
    if not target_mapping:
        raise ValueError(f"No bucket mapping for {job.target_backend}")

    source_client = backend_clients.get_client(job.source_backend_id)
    target_client = backend_clients.get_client(job.target_backend)

    response = source_client.get_object(Bucket=job.backend_bucket, Key=job.object_key)
    body_stream = response["Body"]
    data = body_stream.read()
    body_stream.close()

    extra: dict = {}
    if "ContentType" in response:
        extra["ContentType"] = response["ContentType"]

    target_client.put_object(
        Bucket=target_mapping["backend_bucket"],
        Key=job.object_key,
        Body=data,
        **extra,
    )


def process_pending_jobs(
    conn: sqlite3.Connection,
    handler: JobHandler | None = None,
    limit: int = 10,
) -> int:
    """
    Fetch pending replication jobs and invoke the handler for each.
    Marks jobs completed/failed automatically based on handler result.
    """
    if handler is None:
        handler = replicate_job
    rows = fetch_pending_jobs(conn, limit=limit)
    processed = 0
    for row in rows:
        job = ReplicationJob(
            id=row["id"],
            object_id=row["object_metadata_id"],
            target_backend=row["target_backend"],
            source_backend_id=row["source_backend_id"],
            customer_id=row["customer_id"],
            logical_name=row["logical_name"],
            backend_bucket=row["backend_bucket"],
            object_key=row["object_key"],
            size=row["size"],
            etag=row["etag"],
            residency=row["residency"],
            attempts=row["attempts"],
        )
        try:
            handler(conn, job)
        except Exception as exc:  # pragma: no cover - handler-defined failure
            mark_job_failure(conn, job.id, str(exc))
        else:
            mark_job_success(conn, job.id)
        processed += 1
    return processed
