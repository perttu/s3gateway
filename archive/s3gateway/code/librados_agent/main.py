#!/usr/bin/env python3
"""
Librados Agent Service
A service that provides S3-like operations over librados (Ceph) for the S3 Gateway.
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import asyncio
from io import BytesIO
import hashlib

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import rados
import rbd

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
CEPH_CONF_FILE = os.getenv("CEPH_CONF_FILE", "/etc/ceph/ceph.conf")
CEPH_KEYRING_FILE = os.getenv("CEPH_KEYRING_FILE", "/etc/ceph/ceph.client.admin.keyring")
CEPH_USER = os.getenv("CEPH_USER", "admin")
CEPH_POOL = os.getenv("CEPH_POOL", "s3gateway")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8090"))

# FastAPI app
app = FastAPI(
    title="Librados Agent Service",
    description="A librados agent that provides S3-like operations over Ceph for the S3 Gateway",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LibradosClient:
    """Wrapper for librados operations"""
    
    def __init__(self):
        self.cluster = None
        self.ioctx = None
        self.connected = False
        
    async def connect(self):
        """Connect to Ceph cluster"""
        try:
            # Initialize cluster connection
            self.cluster = rados.Rados(
                conffile=CEPH_CONF_FILE,
                conf=dict(keyring=CEPH_KEYRING_FILE),
                name=f"client.{CEPH_USER}"
            )
            
            logger.info(f"Connecting to Ceph cluster with config: {CEPH_CONF_FILE}")
            self.cluster.connect()
            
            # Create pool if it doesn't exist
            pools = self.cluster.list_pools()
            if CEPH_POOL not in pools:
                logger.info(f"Creating pool: {CEPH_POOL}")
                self.cluster.create_pool(CEPH_POOL)
            
            # Open IO context for the pool
            self.ioctx = self.cluster.open_ioctx(CEPH_POOL)
            self.connected = True
            
            logger.info(f"Successfully connected to Ceph cluster, using pool: {CEPH_POOL}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Ceph cluster: {e}")
            self.connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from Ceph cluster"""
        try:
            if self.ioctx:
                self.ioctx.close()
            if self.cluster:
                self.cluster.shutdown()
            self.connected = False
            logger.info("Disconnected from Ceph cluster")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
    
    def _get_object_key(self, bucket_name: str, object_key: str, version_id: str = None) -> str:
        """Generate Ceph object key from S3 bucket/object/version"""
        if version_id:
            return f"{bucket_name}/{object_key}#{version_id}"
        return f"{bucket_name}/{object_key}"
    
    def _get_metadata_key(self, bucket_name: str, object_key: str = None) -> str:
        """Generate metadata key for bucket or object"""
        if object_key:
            return f"_meta/{bucket_name}/{object_key}"
        return f"_meta/{bucket_name}/"
    
    async def create_bucket(self, bucket_name: str, metadata: Dict = None) -> Dict:
        """Create a bucket (logical container in Ceph)"""
        try:
            if not self.connected:
                return {"status": "error", "error": "Not connected to Ceph cluster"}
            
            # Store bucket metadata
            bucket_meta_key = self._get_metadata_key(bucket_name)
            bucket_metadata = {
                "bucket_name": bucket_name,
                "created_at": datetime.utcnow().isoformat(),
                "versioning_enabled": metadata.get("versioning_enabled", False) if metadata else False,
                "object_lock_enabled": metadata.get("object_lock_enabled", False) if metadata else False
            }
            
            self.ioctx.write_full(bucket_meta_key, json.dumps(bucket_metadata).encode())
            
            logger.info(f"Created bucket: {bucket_name}")
            return {"status": "success", "bucket_name": bucket_name}
            
        except rados.ObjectExists:
            logger.info(f"Bucket {bucket_name} already exists")
            return {"status": "exists", "bucket_name": bucket_name}
        except Exception as e:
            logger.error(f"Failed to create bucket {bucket_name}: {e}")
            return {"status": "error", "error": str(e)}
    
    async def put_object(self, bucket_name: str, object_key: str, data: bytes, 
                        content_type: str = None, version_id: str = None, 
                        metadata: Dict = None) -> Dict:
        """Store an object in Ceph"""
        try:
            if not self.connected:
                return {"status": "error", "error": "Not connected to Ceph cluster"}
            
            # Generate object key
            ceph_key = self._get_object_key(bucket_name, object_key, version_id)
            
            # Store object data
            self.ioctx.write_full(ceph_key, data)
            
            # Calculate ETag (MD5 hash)
            etag = hashlib.md5(data).hexdigest()
            
            # Store object metadata
            object_metadata = {
                "bucket_name": bucket_name,
                "object_key": object_key,
                "version_id": version_id,
                "size": len(data),
                "content_type": content_type or "binary/octet-stream",
                "etag": etag,
                "last_modified": datetime.utcnow().isoformat(),
                "ceph_key": ceph_key,
                "custom_metadata": metadata or {}
            }
            
            meta_key = self._get_metadata_key(bucket_name, f"{object_key}#{version_id}" if version_id else object_key)
            self.ioctx.write_full(meta_key, json.dumps(object_metadata).encode())
            
            logger.info(f"Stored object: {bucket_name}/{object_key} (version: {version_id})")
            return {
                "status": "success",
                "bucket_name": bucket_name,
                "object_key": object_key,
                "version_id": version_id,
                "etag": etag,
                "size": len(data),
                "ceph_key": ceph_key
            }
            
        except Exception as e:
            logger.error(f"Failed to put object {bucket_name}/{object_key}: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_object(self, bucket_name: str, object_key: str, version_id: str = None) -> Dict:
        """Retrieve an object from Ceph"""
        try:
            if not self.connected:
                return {"status": "error", "error": "Not connected to Ceph cluster"}
            
            # Generate object key
            ceph_key = self._get_object_key(bucket_name, object_key, version_id)
            
            # Read object data
            try:
                size, mtime = self.ioctx.stat(ceph_key)
                data = self.ioctx.read(ceph_key)
            except rados.ObjectNotFound:
                return {"status": "not_found", "bucket_name": bucket_name, "object_key": object_key}
            
            # Read object metadata
            meta_key = self._get_metadata_key(bucket_name, f"{object_key}#{version_id}" if version_id else object_key)
            try:
                meta_data = self.ioctx.read(meta_key)
                metadata = json.loads(meta_data.decode())
            except rados.ObjectNotFound:
                # Create basic metadata if not found
                metadata = {
                    "bucket_name": bucket_name,
                    "object_key": object_key,
                    "version_id": version_id,
                    "size": len(data),
                    "content_type": "binary/octet-stream",
                    "etag": hashlib.md5(data).hexdigest(),
                    "last_modified": datetime.fromtimestamp(mtime).isoformat()
                }
            
            logger.info(f"Retrieved object: {bucket_name}/{object_key}")
            return {
                "status": "success",
                "bucket_name": bucket_name,
                "object_key": object_key,
                "data": data,
                "metadata": metadata
            }
            
        except Exception as e:
            logger.error(f"Failed to get object {bucket_name}/{object_key}: {e}")
            return {"status": "error", "error": str(e)}
    
    async def delete_object(self, bucket_name: str, object_key: str, version_id: str = None) -> Dict:
        """Delete an object from Ceph"""
        try:
            if not self.connected:
                return {"status": "error", "error": "Not connected to Ceph cluster"}
            
            # Generate object key
            ceph_key = self._get_object_key(bucket_name, object_key, version_id)
            
            # Delete object data
            try:
                self.ioctx.remove_object(ceph_key)
            except rados.ObjectNotFound:
                return {"status": "not_found", "bucket_name": bucket_name, "object_key": object_key}
            
            # Delete object metadata
            meta_key = self._get_metadata_key(bucket_name, f"{object_key}#{version_id}" if version_id else object_key)
            try:
                self.ioctx.remove_object(meta_key)
            except rados.ObjectNotFound:
                pass  # Metadata not found, that's ok
            
            logger.info(f"Deleted object: {bucket_name}/{object_key}")
            return {
                "status": "success",
                "bucket_name": bucket_name,
                "object_key": object_key,
                "version_id": version_id
            }
            
        except Exception as e:
            logger.error(f"Failed to delete object {bucket_name}/{object_key}: {e}")
            return {"status": "error", "error": str(e)}
    
    async def list_objects(self, bucket_name: str, prefix: str = "", max_keys: int = 1000) -> Dict:
        """List objects in a bucket"""
        try:
            if not self.connected:
                return {"status": "error", "error": "Not connected to Ceph cluster"}
            
            # List all objects with bucket prefix
            bucket_prefix = f"{bucket_name}/"
            objects = []
            
            for obj in self.ioctx.list_objects():
                if obj.key.startswith(bucket_prefix) and not obj.key.startswith("_meta/"):
                    # Extract object key from full key
                    object_key = obj.key[len(bucket_prefix):]
                    
                    # Apply prefix filter
                    if prefix and not object_key.startswith(prefix):
                        continue
                    
                    # Get object stats
                    try:
                        size, mtime = self.ioctx.stat(obj.key)
                        objects.append({
                            "key": object_key,
                            "size": size,
                            "last_modified": datetime.fromtimestamp(mtime).isoformat(),
                            "etag": "\"unknown\"",  # Would need to read metadata for accurate ETag
                            "storage_class": "STANDARD"
                        })
                    except rados.ObjectNotFound:
                        continue
                    
                    if len(objects) >= max_keys:
                        break
            
            logger.info(f"Listed {len(objects)} objects in bucket: {bucket_name}")
            return {
                "status": "success",
                "bucket_name": bucket_name,
                "objects": objects,
                "is_truncated": len(objects) >= max_keys
            }
            
        except Exception as e:
            logger.error(f"Failed to list objects in bucket {bucket_name}: {e}")
            return {"status": "error", "error": str(e)}

# Global librados client
rados_client = LibradosClient()

@app.on_event("startup")
async def startup_event():
    """Initialize librados connection"""
    logger.info("Starting Librados Agent Service...")
    success = await rados_client.connect()
    if not success:
        logger.error("Failed to connect to Ceph cluster on startup")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup librados connection"""
    logger.info("Shutting down Librados Agent Service...")
    await rados_client.disconnect()

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy" if rados_client.connected else "unhealthy",
        "service": "librados-agent",
        "pool": CEPH_POOL,
        "connected": rados_client.connected
    }

# Agent protocol endpoints
@app.post("/api/buckets/{bucket_name}")
async def create_bucket(bucket_name: str, metadata: Dict = None):
    """Create a bucket"""
    result = await rados_client.create_bucket(bucket_name, metadata)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])
    return result

@app.put("/api/buckets/{bucket_name}/objects/{object_key:path}")
async def put_object(
    bucket_name: str, 
    object_key: str, 
    request: Request,
    version_id: str = None,
    content_type: str = None
):
    """Store an object"""
    try:
        data = await request.body()
        metadata = dict(request.headers)
        
        result = await rados_client.put_object(
            bucket_name, object_key, data, content_type, version_id, metadata
        )
        
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["error"])
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/buckets/{bucket_name}/objects/{object_key:path}")
async def get_object(bucket_name: str, object_key: str, version_id: str = None):
    """Retrieve an object"""
    result = await rados_client.get_object(bucket_name, object_key, version_id)
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])
    elif result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Object not found")
    
    # Return the object data as streaming response
    metadata = result["metadata"]
    return StreamingResponse(
        BytesIO(result["data"]),
        media_type=metadata.get("content_type", "binary/octet-stream"),
        headers={
            "ETag": f'"{metadata.get("etag", "")}"',
            "Last-Modified": metadata.get("last_modified", ""),
            "Content-Length": str(metadata.get("size", 0))
        }
    )

@app.delete("/api/buckets/{bucket_name}/objects/{object_key:path}")
async def delete_object(bucket_name: str, object_key: str, version_id: str = None):
    """Delete an object"""
    result = await rados_client.delete_object(bucket_name, object_key, version_id)
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])
    elif result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Object not found")
    
    return result

@app.get("/api/buckets/{bucket_name}/objects")
async def list_objects(bucket_name: str, prefix: str = "", max_keys: int = 1000):
    """List objects in a bucket"""
    result = await rados_client.list_objects(bucket_name, prefix, max_keys)
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result

@app.get("/api/status")
async def get_status():
    """Get agent status and connection info"""
    return {
        "service": "librados-agent",
        "version": "1.0.0",
        "connected": rados_client.connected,
        "pool": CEPH_POOL,
        "config_file": CEPH_CONF_FILE,
        "user": CEPH_USER
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=AGENT_PORT,
        log_level="info"
    ) 