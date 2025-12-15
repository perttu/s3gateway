"""
Shared Pydantic models describing request/response payloads.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class S3Credentials(BaseModel):
    access_key: str
    secret_key: str
    region: str = "default"
    endpoint_url: str


class BucketInfo(BaseModel):
    name: str
    creation_date: Optional[str]


class SnapshotFile(BaseModel):
    key: str
    size: int
    last_modified: Optional[str] = None
    etag: Optional[str] = None
    version_id: Optional[str] = None
    is_latest: Optional[bool] = True


class SnapshotBucket(BaseModel):
    name: str
    files: List[SnapshotFile] = Field(default_factory=list)
    versioning_status: Optional[str] = None


class FileInfo(BaseModel):
    key: str
    size: int
    last_modified: str
    etag: str
    version_id: Optional[str] = None
    is_latest: Optional[bool] = True


class BucketDetails(BaseModel):
    name: str
    files: List[FileInfo]
    total_size: int
    file_count: int
    versioning_status: Optional[str] = None


class VersionInfo(BaseModel):
    key: str
    version_id: str
    size: int
    last_modified: str
    etag: str
    is_latest: bool
    is_delete_marker: bool


class BucketVersions(BaseModel):
    name: str
    versioning_status: str
    versions: List[VersionInfo]


class DiscoverySnapshot(BaseModel):
    endpoint: str
    region: str
    buckets: List[SnapshotBucket]
    total_size: Optional[int] = None
    total_files: Optional[int] = None


class SnapshotMetadata(BaseModel):
    id: str
    timestamp: str
    endpoint: str
    region: str
    bucket_count: int
    total_files: int
    total_size: int
    filename: str


class ReplicationJobRequest(BaseModel):
    object_id: int
    target_backend: str


class ReplicationJobResponse(BaseModel):
    id: int
    object_id: int
    source_backend: str
    target_backend: str
    status: str
    attempts: int
    last_error: Optional[str] = None
    customer_id: str
    logical_name: str
    created_at: str


class ReplicationJobListResponse(BaseModel):
    jobs: List[ReplicationJobResponse]


class TenantCredentialRequest(BaseModel):
    customer_id: str
    access_key: str
    secret_key: str


class TenantCredentialResponse(BaseModel):
    customer_id: str
    access_key: str
    created_at: str


class BucketMappingRequest(BaseModel):
    customer_id: str
    region_id: str
    logical_name: str
    backend_ids: List[str]


class BucketMappingResponse(BaseModel):
    customer_id: str
    region_id: str
    logical_name: str
    backend_mapping: Dict[str, str]


class ObjectMetadataRequest(BaseModel):
    customer_id: str
    logical_name: str
    backend_id: str
    object_key: str
    size: int
    etag: str
    encrypted_key: Optional[str] = None
    residency: Optional[str] = None
    replica_count: Optional[int] = None
    targets: Optional[List[str]] = None


class ObjectMetadataResponse(BaseModel):
    id: int
    customer_id: str
    logical_name: str
    backend_id: str
    backend_bucket: str
    object_key: str
    size: int
    etag: str
    encrypted_key: Optional[str] = None
    residency: Optional[str] = None
    replica_count: Optional[int] = None
    created_at: str
    jobs_created: List[ReplicationJobResponse] = Field(default_factory=list)


class ObjectListResponse(BaseModel):
    customer_id: str
    logical_name: str
    objects: List[ObjectMetadataResponse]
