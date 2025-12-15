"""
FastAPI entrypoint for the S3 discovery service.

Routes delegate business logic to app.services so this module focuses on HTTP
concerns (CORS, serialization, background thread usage).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
import logging

from app.config import ALLOWED_ORIGINS
from app.models import (
    BucketDetails,
    BucketInfo,
    BucketVersions,
    DiscoverySnapshot,
    S3Credentials,
    SnapshotMetadata,
)
from app import services
from app import proxy_meta, proxy_router
from app.db import init_db, seed_provider_data
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="S3 Service Discovery API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    if os.getenv("PROXY_DB_INIT_DISABLED") == "1":
        return
    init_db()
    seed_provider_data()

app.include_router(proxy_meta.router)
app.include_router(proxy_router.router)


@app.post("/discover/buckets", response_model=list[BucketInfo])
async def list_buckets(credentials: S3Credentials):
    """List every bucket accessible with the provided credentials."""
    return await run_in_threadpool(services.list_buckets, credentials)


@app.post("/discover/bucket/{bucket_name}", response_model=BucketDetails)
async def get_bucket_details(bucket_name: str, credentials: S3Credentials):
    """Return object listings and summary data for a single bucket."""
    return await run_in_threadpool(
        services.get_bucket_details,
        bucket_name,
        credentials,
    )


@app.post("/discover/bucket/{bucket_name}/versions", response_model=BucketVersions)
async def get_bucket_versions(bucket_name: str, credentials: S3Credentials):
    """Return version history for a bucket (if versioning is enabled)."""
    return await run_in_threadpool(
        services.get_bucket_versions,
        bucket_name,
        credentials,
    )


@app.post("/snapshot/save", response_model=SnapshotMetadata)
async def save_snapshot(snapshot: DiscoverySnapshot):
    """
    Persist discovery results.

    Snapshot persistence truncates large payloads using MAX_SNAPSHOT_BUCKETS,
    MAX_SNAPSHOT_FILES, and MAX_FILES_PER_BUCKET environment variables. See
    README for the documented defaults.
    """
    return services.persist_snapshot(snapshot)


@app.get("/snapshot/list", response_model=list[SnapshotMetadata])
async def list_snapshots():
    """List stored snapshots (newest first)."""
    return services.read_snapshot_files()


@app.get("/snapshot/{snapshot_id}")
async def get_snapshot(snapshot_id: str):
    """Return a stored snapshot payload."""
    return services.load_snapshot(snapshot_id)


@app.delete("/snapshot/{snapshot_id}")
async def delete_snapshot(snapshot_id: str):
    """Delete a stored snapshot."""
    services.delete_snapshot(snapshot_id)
    return {"message": "Snapshot deleted successfully"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
