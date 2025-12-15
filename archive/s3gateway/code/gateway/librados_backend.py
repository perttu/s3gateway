#!/usr/bin/env python3
"""
Librados Backend for S3 Gateway
Communicates with librados agents via HTTP API to provide Ceph storage backend
"""

import json
import logging
from typing import Optional, Dict, Any, List
import httpx
import asyncio

logger = logging.getLogger(__name__)

class LibradosBackend:
    """Backend for communicating with librados agents"""
    
    def __init__(self, config: Dict):
        self.name = config['name']
        self.provider = config['provider']
        self.zone_code = config['zone_code']
        self.region = config['region']
        self.enabled = config.get('enabled', True)
        self.is_primary = config.get('is_primary', False)
        self.agent_url = config['agent_url']
        self.pool = config.get('pool', 's3gateway')
        
        # HTTP client for agent communication
        self.client = httpx.AsyncClient(
            base_url=self.agent_url,
            timeout=30.0
        )
        
        logger.info(f"Initialized Librados backend: {self.name} ({self.provider}) -> {self.agent_url}")
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    async def create_bucket(self, bucket_name: str, metadata: Dict = None) -> Dict:
        """Create bucket via librados agent"""
        try:
            payload = metadata or {}
            response = await self.client.post(
                f"/api/buckets/{bucket_name}",
                json=payload
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Created bucket {bucket_name} in {self.name}")
                return {"status": "success", "backend": self.name, "result": result}
            else:
                logger.error(f"Failed to create bucket {bucket_name} in {self.name}: {response.text}")
                return {"status": "error", "backend": self.name, "error": response.text}
                
        except Exception as e:
            logger.error(f"Failed to create bucket {bucket_name} in {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def put_object(self, bucket_name: str, object_key: str, body: bytes, 
                        content_type: str = None, version_id: str = None) -> Dict:
        """Upload object via librados agent"""
        try:
            headers = {}
            if content_type:
                headers['content-type'] = content_type
            
            params = {}
            if version_id:
                params['version_id'] = version_id
            if content_type:
                params['content_type'] = content_type
            
            response = await self.client.put(
                f"/api/buckets/{bucket_name}/objects/{object_key}",
                content=body,
                headers=headers,
                params=params
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Uploaded {object_key} (version {version_id}) to {bucket_name} in {self.name}")
                return {
                    "status": "success",
                    "backend": self.name,
                    "etag": result.get('etag', ''),
                    "size": result.get('size', len(body)),
                    "gateway_version_id": version_id,
                    "ceph_key": result.get('ceph_key'),
                    "result": result
                }
            else:
                logger.error(f"Failed to upload {object_key} to {self.name}: {response.text}")
                return {"status": "error", "backend": self.name, "error": response.text}
                
        except Exception as e:
            logger.error(f"Failed to upload {object_key} to {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def get_object(self, bucket_name: str, object_key: str, version_id: str = None) -> Dict:
        """Get object via librados agent"""
        try:
            params = {}
            if version_id:
                params['version_id'] = version_id
            
            response = await self.client.get(
                f"/api/buckets/{bucket_name}/objects/{object_key}",
                params=params
            )
            
            if response.status_code == 200:
                # Agent returns the object data directly with headers
                return {
                    "status": "success",
                    "backend": self.name,
                    "body": response.content,
                    "content_type": response.headers.get('content-type', 'binary/octet-stream'),
                    "etag": response.headers.get('etag', '').strip('"'),
                    "last_modified": response.headers.get('last-modified'),
                    "size": int(response.headers.get('content-length', 0))
                }
            elif response.status_code == 404:
                return {"status": "not_found", "backend": self.name}
            else:
                logger.error(f"Failed to get {object_key} from {self.name}: {response.text}")
                return {"status": "error", "backend": self.name, "error": response.text}
                
        except Exception as e:
            logger.error(f"Failed to get {object_key} from {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def delete_object(self, bucket_name: str, object_key: str, version_id: str = None) -> Dict:
        """Delete object via librados agent"""
        try:
            params = {}
            if version_id:
                params['version_id'] = version_id
            
            response = await self.client.delete(
                f"/api/buckets/{bucket_name}/objects/{object_key}",
                params=params
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Deleted {object_key} from {bucket_name} in {self.name}")
                return {
                    "status": "success",
                    "backend": self.name,
                    "result": result
                }
            elif response.status_code == 404:
                return {"status": "not_found", "backend": self.name}
            else:
                logger.error(f"Failed to delete {object_key} from {self.name}: {response.text}")
                return {"status": "error", "backend": self.name, "error": response.text}
                
        except Exception as e:
            logger.error(f"Failed to delete {object_key} from {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def list_objects(self, bucket_name: str, prefix: str = "") -> Dict:
        """List objects via librados agent"""
        try:
            params = {}
            if prefix:
                params['prefix'] = prefix
            
            response = await self.client.get(
                f"/api/buckets/{bucket_name}/objects",
                params=params
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Convert to S3-compatible format
                objects = []
                for obj in result.get('objects', []):
                    objects.append({
                        'Key': obj['key'],
                        'LastModified': obj['last_modified'],
                        'ETag': f'"{obj.get("etag", "unknown")}"',
                        'Size': obj['size'],
                        'StorageClass': obj.get('storage_class', 'STANDARD')
                    })
                
                return {
                    "status": "success",
                    "backend": self.name,
                    "objects": objects,
                    "is_truncated": result.get('is_truncated', False)
                }
            else:
                logger.error(f"Failed to list objects in {bucket_name} from {self.name}: {response.text}")
                return {"status": "error", "backend": self.name, "error": response.text}
                
        except Exception as e:
            logger.error(f"Failed to list objects in {bucket_name} from {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def health_check(self) -> Dict:
        """Check health of librados agent"""
        try:
            response = await self.client.get("/health", timeout=5.0)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "status": "healthy",
                    "backend": self.name,
                    "agent_connected": result.get('connected', False),
                    "pool": result.get('pool'),
                    "result": result
                }
            else:
                return {
                    "status": "unhealthy", 
                    "backend": self.name,
                    "error": f"HTTP {response.status_code}"
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": self.name, 
                "error": str(e)
            }
    
    async def get_status(self) -> Dict:
        """Get detailed status from librados agent"""
        try:
            response = await self.client.get("/api/status", timeout=5.0)
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "status": "success",
                    "backend": self.name,
                    "result": result
                }
            else:
                return {
                    "status": "error",
                    "backend": self.name,
                    "error": f"HTTP {response.status_code}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "backend": self.name,
                "error": str(e)
            } 