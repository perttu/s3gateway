"""
Lightweight SQLite helpers for storing proxy metadata.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional

from . import crypto_utils
from pathlib import Path
from typing import Generator

DATA_PROVIDERS_CSV = (
    Path(__file__).resolve().parents[2] / "data" / "providers" / "providers_flat.csv"
)
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "metadata.db"


def resolve_db_path() -> Path:
    return Path(os.getenv("PROXY_METADATA_DB_PATH", DEFAULT_DB_PATH))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS bucket_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL,
            region_id TEXT NOT NULL,
            logical_name TEXT NOT NULL,
            backend_id TEXT NOT NULL,
            backend_bucket TEXT NOT NULL,
            UNIQUE(customer_id, logical_name, backend_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS object_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bucket_mapping_id INTEGER NOT NULL,
            object_key TEXT NOT NULL,
            size INTEGER NOT NULL,
            etag TEXT NOT NULL,
            encrypted_key TEXT,
            residency TEXT,
            replica_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bucket_mapping_id) REFERENCES bucket_mappings(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_capabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT NOT NULL,
            region_city TEXT NOT NULL,
            zone_code TEXT NOT NULL,
            provider TEXT NOT NULL,
            s3_compatible TEXT,
            object_lock TEXT,
            versioning TEXT,
            iso27001 TEXT,
            veeam_ready TEXT,
            notes TEXT,
            UNIQUE(provider, zone_code)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS replication_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bucket_mapping_id INTEGER NOT NULL,
            object_metadata_id INTEGER NOT NULL,
            source_backend_id TEXT NOT NULL,
            target_backend TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(bucket_mapping_id) REFERENCES bucket_mappings(id),
            FOREIGN KEY(object_metadata_id) REFERENCES object_metadata(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL,
            access_key TEXT NOT NULL,
            secret_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(access_key)
        )
        """
    )
    conn.commit()
    conn.close()


def seed_provider_data() -> None:
    if not DATA_PROVIDERS_CSV.exists():
        return

    import csv

    conn = get_connection()
    cursor = conn.cursor()
    with DATA_PROVIDERS_CSV.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [
            (
                row.get("Country", ""),
                row.get("Region/City", ""),
                row.get("Zone_Code", ""),
                row.get("Provider", ""),
                row.get("S3_Compatible"),
                row.get("Object_Lock"),
                row.get("Versioning"),
                row.get("ISO_27001_GDPR"),
                row.get("Veeam_Ready"),
                row.get("Notes"),
            )
            for row in reader
            if row.get("Zone_Code") and row.get("Provider")
        ]

    cursor.executemany(
        """
        INSERT OR IGNORE INTO provider_capabilities
        (country, region_city, zone_code, provider, s3_compatible, object_lock,
         versioning, iso27001, veeam_ready, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def upsert_tenant_credentials(
    conn: sqlite3.Connection,
    customer_id: str,
    access_key: str,
    secret_key: str,
) -> None:
    cursor = conn.cursor()
    encrypted_secret = crypto_utils.encrypt_secret(secret_key)
    cursor.execute(
        """
        INSERT INTO tenant_credentials (customer_id, access_key, secret_key)
        VALUES (?, ?, ?)
        ON CONFLICT(access_key) DO UPDATE SET customer_id = excluded.customer_id, secret_key = excluded.secret_key
        """,
        (customer_id, access_key, encrypted_secret),
    )
    conn.commit()


def fetch_tenant_by_access_key(
    conn: sqlite3.Connection, access_key: str
) -> Optional[dict]:
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT customer_id, access_key, secret_key, created_at
        FROM tenant_credentials
        WHERE access_key = ?
        """,
        (access_key,),
    ).fetchone()
    if not row:
        return None
    return {
        "customer_id": row["customer_id"],
        "access_key": row["access_key"],
        "secret_key": crypto_utils.decrypt_secret(row["secret_key"]),
        "created_at": row["created_at"],
    }


def fetch_bucket_mapping(
    conn: sqlite3.Connection, customer_id: str, logical_name: str, backend_id: str
) -> sqlite3.Row | None:
    cursor = conn.cursor()
    return cursor.execute(
        """
        SELECT backend_bucket, region_id
        FROM bucket_mappings
        WHERE customer_id = ? AND logical_name = ? AND backend_id = ?
        """,
        (customer_id, logical_name, backend_id),
    ).fetchone()


def insert_replication_job(conn: sqlite3.Connection, object_id: int, target_backend: str) -> sqlite3.Row:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO replication_jobs (bucket_mapping_id, object_metadata_id, source_backend_id, target_backend)
        SELECT bm.id, om.id, bm.backend_id, ?
        FROM object_metadata om
        JOIN bucket_mappings bm ON om.bucket_mapping_id = bm.id
        WHERE om.id = ?
        """,
        (target_backend, object_id),
    )
    if cursor.rowcount == 0:
        raise ValueError("Object metadata not found")
    job_id = cursor.lastrowid
    conn.commit()
    return cursor.execute(
        """
        SELECT r.id, r.object_metadata_id, r.source_backend_id, r.target_backend, r.status, r.attempts,
               r.last_error, r.created_at, bm.customer_id, bm.logical_name
        FROM replication_jobs r
        JOIN bucket_mappings bm ON r.bucket_mapping_id = bm.id
        WHERE r.id = ?
        """,
        (job_id,),
    ).fetchone()


def list_replication_jobs(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    if status:
        return cursor.execute(
            """
            SELECT r.id, r.object_metadata_id, r.source_backend_id, r.target_backend, r.status, r.attempts,
                   r.last_error, r.created_at, bm.customer_id, bm.logical_name
            FROM replication_jobs r
            JOIN bucket_mappings bm ON r.bucket_mapping_id = bm.id
            WHERE r.status = ?
            ORDER BY r.created_at ASC
            """,
            (status,),
        ).fetchall()
    return cursor.execute(
        """
        SELECT r.id, r.object_metadata_id, r.source_backend_id, r.target_backend, r.status, r.attempts,
               r.last_error, r.created_at, bm.customer_id, bm.logical_name
        FROM replication_jobs r
        JOIN bucket_mappings bm ON r.bucket_mapping_id = bm.id
        ORDER BY r.created_at DESC
        """
    ).fetchall()


def fetch_pending_jobs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    return cursor.execute(
        """
        SELECT r.id, r.object_metadata_id, r.source_backend_id, r.target_backend, r.attempts, r.created_at,
               bm.customer_id, bm.logical_name, bm.backend_bucket,
               om.object_key, om.size, om.etag, om.residency
        FROM replication_jobs r
        JOIN bucket_mappings bm ON r.bucket_mapping_id = bm.id
        JOIN object_metadata om ON r.object_metadata_id = om.id
        WHERE r.status = 'pending'
        ORDER BY r.created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def mark_job_success(conn: sqlite3.Connection, job_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE replication_jobs
        SET status = 'completed', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (job_id,),
    )
    conn.commit()


def mark_job_failure(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE replication_jobs
        SET status = 'failed', attempts = attempts + 1, last_error = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (error, job_id),
    )
    conn.commit()
