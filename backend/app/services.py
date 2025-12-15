"""
Service layer for interacting with S3 and the snapshot store.

These helpers encapsulate boto3 usage (synchronous by design) and snapshot
sanity checks so FastAPI routes can stay thin.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Tuple

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import HTTPException
import logging

from .config import (
    SNAPSHOTS_DIR,
    MAX_SNAPSHOT_BUCKETS,
    MAX_SNAPSHOT_FILES,
    MAX_FILES_PER_BUCKET,
)
from .models import (
    BucketDetails,
    BucketInfo,
    BucketVersions,
    DiscoverySnapshot,
    FileInfo,
    SnapshotBucket,
    SnapshotMetadata,
    SnapshotFile,
    S3Credentials,
    VersionInfo,
)

logger = logging.getLogger(__name__)


def _create_s3_client(credentials: S3Credentials):
    return boto3.client(
        "s3",
        aws_access_key_id=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        endpoint_url=credentials.endpoint_url,
        region_name=credentials.region if credentials.region != "default" else None,
    )


def list_buckets(credentials: S3Credentials) -> List[BucketInfo]:
    """
    Return all buckets accessible with the provided credentials, raising
    HTTP errors that map to FastAPI responses.
    """
    try:
        s3_client = _create_s3_client(credentials)
        response = s3_client.list_buckets()
        buckets = []
        for bucket in response.get("Buckets", []):
            buckets.append(
                BucketInfo(
                    name=bucket["Name"],
                    creation_date=bucket.get("CreationDate", "").isoformat()
                    if bucket.get("CreationDate")
                    else None,
                )
            )
        logger.info("Successfully listed %s buckets", len(buckets))
        return buckets
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "InvalidAccessKeyId":
            raise HTTPException(status_code=401, detail="Invalid access key")
        if error_code == "SignatureDoesNotMatch":
            raise HTTPException(status_code=401, detail="Invalid secret key")
        raise HTTPException(status_code=400, detail=f"S3 error: {str(e)}")
    except Exception as exc:  # pragma: no cover - unexpected boto error
        logger.exception("Error listing buckets")
        raise HTTPException(status_code=500, detail=f"Server error: {str(exc)}")


def get_bucket_details(bucket_name: str, credentials: S3Credentials) -> BucketDetails:
    try:
        s3_client = _create_s3_client(credentials)
        try:
            versioning_response = s3_client.get_bucket_versioning(Bucket=bucket_name)
            versioning_status = versioning_response.get("Status", "Disabled")
        except Exception:
            versioning_status = "Unknown"

        files: List[FileInfo] = []
        total_size = 0
        continuation_token = None

        while True:
            if continuation_token:
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name, ContinuationToken=continuation_token
                )
            else:
                response = s3_client.list_objects_v2(Bucket=bucket_name)

            for obj in response.get("Contents", []):
                files.append(
                    FileInfo(
                        key=obj["Key"],
                        size=obj["Size"],
                        last_modified=obj["LastModified"].isoformat(),
                        etag=obj["ETag"].strip('"'),
                    )
                )
                total_size += obj["Size"]

            if response.get("IsTruncated"):
                continuation_token = response.get("NextContinuationToken")
            else:
                break

        return BucketDetails(
            name=bucket_name,
            files=files,
            total_size=total_size,
            file_count=len(files),
            versioning_status=versioning_status,
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_message = e.response["Error"]["Message"]
        logger.error(
            "S3 ClientError for bucket %s: %s - %s",
            bucket_name,
            error_code,
            error_message,
        )
        if error_code == "NoSuchBucket":
            raise HTTPException(status_code=404, detail="Bucket not found")
        if error_code == "AccessDenied":
            raise HTTPException(status_code=403, detail="Access denied to bucket")
        raise HTTPException(
            status_code=400, detail=f"S3 error: {error_code} - {error_message}"
        )
    except Exception as exc:  # pragma: no cover - unexpected boto error
        logger.exception("Error getting bucket details for %s", bucket_name)
        raise HTTPException(status_code=500, detail=f"Server error: {str(exc)}")


def get_bucket_versions(bucket_name: str, credentials: S3Credentials) -> BucketVersions:
    try:
        s3_client = _create_s3_client(credentials)
        versioning_response = s3_client.get_bucket_versioning(Bucket=bucket_name)
        versioning_status = versioning_response.get("Status", "Disabled")

        if versioning_status not in ["Enabled", "Suspended"]:
            return BucketVersions(
                name=bucket_name, versioning_status=versioning_status, versions=[]
            )

        versions: List[VersionInfo] = []
        key_marker = None
        version_id_marker = None

        while True:
            if key_marker:
                response = s3_client.list_object_versions(
                    Bucket=bucket_name,
                    KeyMarker=key_marker,
                    VersionIdMarker=version_id_marker,
                )
            else:
                response = s3_client.list_object_versions(Bucket=bucket_name)

            for version in response.get("Versions", []):
                versions.append(
                    VersionInfo(
                        key=version["Key"],
                        version_id=version["VersionId"],
                        size=version["Size"],
                        last_modified=version["LastModified"].isoformat(),
                        etag=version["ETag"].strip('"'),
                        is_latest=version.get("IsLatest", False),
                        is_delete_marker=False,
                    )
                )

            for marker in response.get("DeleteMarkers", []):
                versions.append(
                    VersionInfo(
                        key=marker["Key"],
                        version_id=marker["VersionId"],
                        size=0,
                        last_modified=marker["LastModified"].isoformat(),
                        etag="",
                        is_latest=marker.get("IsLatest", False),
                        is_delete_marker=True,
                    )
                )

            if response.get("IsTruncated"):
                key_marker = response.get("NextKeyMarker")
                version_id_marker = response.get("NextVersionIdMarker")
            else:
                break

        return BucketVersions(
            name=bucket_name, versioning_status=versioning_status, versions=versions
        )

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "NoSuchBucket":
            raise HTTPException(status_code=404, detail="Bucket not found")
        if error_code == "AccessDenied":
            raise HTTPException(
                status_code=403, detail="Access denied to bucket versioning"
            )
        raise HTTPException(status_code=400, detail=f"S3 error: {str(e)}")
    except Exception as exc:  # pragma: no cover - unexpected boto error
        logger.exception("Error getting bucket versions")
        raise HTTPException(status_code=500, detail=f"Server error: {str(exc)}")


def _sanitize_snapshot_buckets(
    buckets: List[SnapshotBucket],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Clip snapshot payloads to avoid unbounded persistence.

    Returns sanitized bucket entries plus aggregate size/file totals.
    """
    sanitized: List[Dict[str, Any]] = []
    total_files = 0
    total_size = 0
    remaining_files_budget = MAX_SNAPSHOT_FILES

    for bucket in buckets[:MAX_SNAPSHOT_BUCKETS]:
        if remaining_files_budget <= 0:
            logger.info(
                "Snapshot truncated because MAX_SNAPSHOT_FILES=%s exhausted",
                MAX_SNAPSHOT_FILES,
            )
            break

        allowed_files = min(len(bucket.files), MAX_FILES_PER_BUCKET, remaining_files_budget)
        selected_files = bucket.files[:allowed_files]
        bucket_total_size = 0

        safe_files: List[Dict[str, Any]] = []
        for file in selected_files:
            safe_size = max(0, file.size)
            bucket_total_size += safe_size
            safe_files.append(
                {
                    "key": file.key,
                    "size": safe_size,
                    "last_modified": file.last_modified,
                    "etag": file.etag,
                    "version_id": file.version_id,
                    "is_latest": file.is_latest,
                }
            )

        sanitized.append(
            {
                "name": bucket.name,
                "files": safe_files,
                "file_count": len(safe_files),
                "total_size": bucket_total_size,
                "versioning_status": bucket.versioning_status or "Unknown",
            }
        )

        total_files += len(safe_files)
        total_size += bucket_total_size
        remaining_files_budget -= len(safe_files)

    if len(buckets) > MAX_SNAPSHOT_BUCKETS:
        logger.info(
            "Snapshot truncated because MAX_SNAPSHOT_BUCKETS=%s exceeded",
            MAX_SNAPSHOT_BUCKETS,
        )

    return sanitized, total_size, total_files


def persist_snapshot(snapshot: DiscoverySnapshot) -> SnapshotMetadata:
    """
    Sanitize and persist a snapshot payload, returning metadata about the
    stored file.
    """
    sanitized_buckets, total_size, total_files = _sanitize_snapshot_buckets(
        snapshot.buckets
    )
    snapshot_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    safe_endpoint = snapshot.endpoint.replace("://", "_").replace("/", "_")
    filename = f"snapshot_{safe_endpoint}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = SNAPSHOTS_DIR / filename

    snapshot_data = {
        "id": snapshot_id,
        "timestamp": timestamp,
        "endpoint": snapshot.endpoint,
        "region": snapshot.region,
        "buckets": sanitized_buckets,
        "total_size": total_size,
        "total_files": total_files,
    }

    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(snapshot_data, handle, indent=2)

    logger.info("Saved snapshot to %s", filepath)

    return SnapshotMetadata(
        id=snapshot_id,
        timestamp=timestamp,
        endpoint=snapshot.endpoint,
        region=snapshot.region,
        bucket_count=len(sanitized_buckets),
        total_files=total_files,
        total_size=total_size,
        filename=filename,
    )


def read_snapshot_files() -> List[SnapshotMetadata]:
    """
    Return metadata for every snapshot stored on disk, newest first.
    """
    snapshots: List[SnapshotMetadata] = []
    for filepath in SNAPSHOTS_DIR.glob("snapshot_*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            snapshots.append(
                SnapshotMetadata(
                    id=data.get("id", "unknown"),
                    timestamp=data.get("timestamp", ""),
                    endpoint=data.get("endpoint", ""),
                    region=data.get("region", ""),
                    bucket_count=len(data.get("buckets", [])),
                    total_files=data.get("total_files", 0),
                    total_size=data.get("total_size", 0),
                    filename=filepath.name,
                )
            )
        except Exception as exc:  # pragma: no cover - I/O errors should not crash
            logger.error("Error reading snapshot %s: %s", filepath, exc)
            continue

    snapshots.sort(key=lambda meta: meta.timestamp, reverse=True)
    return snapshots


def load_snapshot(snapshot_id: str) -> Dict[str, Any]:
    """
    Load the snapshot payload with the given ID.
    """
    for filepath in SNAPSHOTS_DIR.glob("snapshot_*.json"):
        with open(filepath, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if data.get("id") == snapshot_id:
                return data
    raise HTTPException(status_code=404, detail="Snapshot not found")


def delete_snapshot(snapshot_id: str) -> None:
    """
    Remove the snapshot file matching the requested ID.
    """
    for filepath in SNAPSHOTS_DIR.glob("snapshot_*.json"):
        with open(filepath, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if data.get("id") == snapshot_id:
                os.remove(filepath)
                logger.info("Deleted snapshot %s", filepath)
                return
    raise HTTPException(status_code=404, detail="Snapshot not found")
