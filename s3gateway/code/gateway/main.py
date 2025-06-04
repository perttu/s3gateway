#!/usr/bin/env python3
"""
S3 Gateway Service
A sovereign S3 gateway that routes requests to real S3 backends based on 
data sovereignty requirements and logs metadata to PostgreSQL.
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import asyncio
from io import BytesIO

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import pandas as pd
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://s3gateway:s3gateway_pass@localhost:5433/s3gateway")
S3PROXY_URL = os.getenv("S3PROXY_URL", "http://localhost:8080")
PROVIDERS_FILE = os.getenv("PROVIDERS_FILE", "/app/providers_flat.csv")
S3_BACKENDS_CONFIG = os.getenv("S3_BACKENDS_CONFIG", "/app/config/s3_backends.json")

# Configuration constants
HARDCODED_BUCKET = "2025-datatransfer"

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# FastAPI app
app = FastAPI(
    title="S3 Gateway Service",
    description="A sovereign S3 gateway with immutable storage and local metadata authority",
    version="2.1.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global data
providers_df = None
s3_backends = {}
backends_config = None

def generate_version_id() -> str:
    """Generate a custom version ID for our metadata system"""
    # Using timestamp + random component for uniqueness and sortability
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_part = str(uuid.uuid4()).replace('-', '')[:8]
    return f"v{timestamp}-{random_part}"

def check_bucket_immutability(db: Session, bucket_name: str) -> bool:
    """Check if a bucket has immutability (object lock) enabled"""
    try:
        query = text("""
            SELECT object_lock_enabled, versioning_enabled 
            FROM buckets 
            WHERE bucket_name = :bucket_name 
            LIMIT 1
        """)
        result = db.execute(query, {'bucket_name': bucket_name}).fetchone()
        
        if result:
            return result.object_lock_enabled, result.versioning_enabled
        return False, False
        
    except Exception as e:
        logger.error(f"Failed to check bucket immutability: {e}")
        return False, False

def check_object_exists_in_metadata(db: Session, bucket_name: str, object_key: str) -> Optional[Dict]:
    """Check if object exists in local metadata and is not deleted"""
    try:
        query = text("""
            SELECT o.id, o.version_id, o.is_delete_marker, o.size_bytes, o.content_type, 
                   o.etag, o.last_modified, o.primary_zone_code, b.versioning_enabled
            FROM objects o
            JOIN buckets b ON o.bucket_id = b.id
            WHERE b.bucket_name = :bucket_name AND o.object_key = :object_key
            AND o.is_delete_marker = false
            ORDER BY o.created_at DESC
            LIMIT 1
        """)
        
        result = db.execute(query, {
            'bucket_name': bucket_name,
            'object_key': object_key
        }).fetchone()
        
        if result:
            return {
                'id': result.id,
                'version_id': result.version_id,
                'is_delete_marker': result.is_delete_marker,
                'size_bytes': result.size_bytes,
                'content_type': result.content_type,
                'etag': result.etag,
                'last_modified': result.last_modified,
                'primary_zone_code': result.primary_zone_code,
                'versioning_enabled': result.versioning_enabled
            }
        return None
        
    except Exception as e:
        logger.error(f"Failed to check object in metadata: {e}")
        return None

def list_objects_from_metadata(db: Session, bucket_name: str, prefix: str = "") -> List[Dict]:
    """List objects from local metadata, excluding deleted ones"""
    try:
        where_clause = "AND o.object_key LIKE :prefix" if prefix else ""
        
        query = text(f"""
            SELECT DISTINCT ON (o.object_key) 
                   o.object_key, o.size_bytes, o.content_type, o.etag, 
                   o.last_modified, o.storage_class, o.version_id
            FROM objects o
            JOIN buckets b ON o.bucket_id = b.id
            WHERE b.bucket_name = :bucket_name 
            AND o.is_delete_marker = false
            {where_clause}
            ORDER BY o.object_key, o.created_at DESC
        """)
        
        params = {'bucket_name': bucket_name}
        if prefix:
            params['prefix'] = f"{prefix}%"
            
        result = db.execute(query, params)
        
        objects = []
        for row in result:
            objects.append({
                'Key': row.object_key,
                'Size': row.size_bytes,
                'LastModified': row.last_modified.isoformat() if row.last_modified else '',
                'ETag': f'"{row.etag}"' if row.etag else '""',
                'StorageClass': row.storage_class or 'STANDARD'
            })
        
        return objects
        
    except Exception as e:
        logger.error(f"Failed to list objects from metadata: {e}")
        return []

class S3Backend:
    """Wrapper for S3 backend client"""
    
    def __init__(self, config: Dict):
        self.name = config['name']
        self.provider = config['provider']
        self.zone_code = config['zone_code']
        self.region = config['region']
        self.enabled = config.get('enabled', True)
        self.is_primary = config.get('is_primary', False)
        
        # Create boto3 client
        client_config = {
            'aws_access_key_id': config['access_key'],
            'aws_secret_access_key': config['secret_key'],
            'region_name': config['region']
        }
        
        if config.get('endpoint_url'):
            client_config['endpoint_url'] = config['endpoint_url']
            
        self.client = boto3.client('s3', **client_config)
        logger.info(f"Initialized S3 backend: {self.name} ({self.provider})")
    
    async def create_bucket(self, bucket_name: str) -> Dict:
        """Create bucket in this backend"""
        try:
            if self.region == 'us-east-1':
                # us-east-1 doesn't need CreateBucketConfiguration
                self.client.create_bucket(Bucket=bucket_name)
            else:
                self.client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': self.region}
                )
            
            logger.info(f"Created bucket {bucket_name} in {self.name}")
            return {"status": "success", "backend": self.name}
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'BucketAlreadyOwnedByYou':
                logger.info(f"Bucket {bucket_name} already exists in {self.name}")
                return {"status": "exists", "backend": self.name}
            else:
                logger.error(f"Failed to create bucket {bucket_name} in {self.name}: {e}")
                return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def put_object(self, bucket_name: str, object_key: str, body: bytes, content_type: str = None, version_id: str = None) -> Dict:
        """Upload object to this backend with custom version tracking"""
        try:
            # Use our custom version ID as part of the key to ensure backend uniqueness
            backend_key = f"{object_key}#{version_id}" if version_id else object_key
            
            put_args = {
                'Bucket': bucket_name,
                'Key': backend_key,
                'Body': body,
                'Metadata': {
                    'gateway-version-id': version_id or 'none',
                    'original-key': object_key
                }
            }
            
            if content_type:
                put_args['ContentType'] = content_type
            
            response = self.client.put_object(**put_args)
            
            logger.info(f"Uploaded {object_key} (version {version_id}) to {bucket_name} in {self.name}")
            return {
                "status": "success", 
                "backend": self.name,
                "etag": response.get('ETag', '').strip('"'),
                "size": len(body),
                "backend_key": backend_key,
                "gateway_version_id": version_id
            }
            
        except ClientError as e:
            logger.error(f"Failed to upload {object_key} to {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def get_object(self, bucket_name: str, object_key: str, version_id: str = None) -> Dict:
        """Get object from this backend using version-specific key"""
        try:
            # Use the versioned key format
            backend_key = f"{object_key}#{version_id}" if version_id else object_key
            
            response = self.client.get_object(Bucket=bucket_name, Key=backend_key)
            
            return {
                "status": "success",
                "backend": self.name,
                "body": response['Body'].read(),
                "content_type": response.get('ContentType', 'binary/octet-stream'),
                "etag": response.get('ETag', '').strip('"'),
                "last_modified": response.get('LastModified'),
                "size": response.get('ContentLength', 0)
            }
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                return {"status": "not_found", "backend": self.name}
            else:
                logger.error(f"Failed to get {object_key} from {self.name}: {e}")
                return {"status": "error", "backend": self.name, "error": str(e)}
    
    async def list_objects(self, bucket_name: str, prefix: str = "") -> Dict:
        """List objects in bucket - for debugging backend state only"""
        try:
            response = self.client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=prefix,
                MaxKeys=1000
            )
            
            objects = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    # Parse our versioned keys
                    key = obj['Key']
                    if '#' in key:
                        original_key, version_id = key.split('#', 1)
                    else:
                        original_key, version_id = key, 'none'
                        
                    objects.append({
                        'Key': original_key,
                        'BackendKey': key,
                        'VersionId': version_id,
                        'LastModified': obj['LastModified'].isoformat(),
                        'ETag': obj['ETag'].strip('"'),
                        'Size': obj['Size'],
                        'StorageClass': obj.get('StorageClass', 'STANDARD')
                    })
            
            return {
                "status": "success",
                "backend": self.name,
                "objects": objects,
                "is_truncated": response.get('IsTruncated', False)
            }
            
        except ClientError as e:
            logger.error(f"Failed to list objects in {bucket_name} from {self.name}: {e}")
            return {"status": "error", "backend": self.name, "error": str(e)}

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def load_s3_backends():
    """Load S3 backend configuration"""
    global s3_backends, backends_config
    
    try:
        with open(S3_BACKENDS_CONFIG, 'r') as f:
            backends_config = json.load(f)
        
        s3_backends = {}
        for backend_config in backends_config['backends']:
            if backend_config.get('enabled', True):
                backend = S3Backend(backend_config)
                s3_backends[backend.name] = backend
        
        logger.info(f"Loaded {len(s3_backends)} S3 backends")
        return True
        
    except Exception as e:
        logger.error(f"Failed to load S3 backends: {e}")
        return False

def load_providers():
    """Load providers from CSV file"""
    global providers_df
    try:
        providers_df = pd.read_csv(PROVIDERS_FILE)
        # Replace NaN values with empty strings to avoid JSON serialization issues
        providers_df = providers_df.fillna("")
        logger.info(f"Loaded {len(providers_df)} providers from {PROVIDERS_FILE}")
        return providers_df
    except Exception as e:
        logger.error(f"Failed to load providers: {e}")
        return pd.DataFrame()

def log_operation(db: Session, operation_type: str, bucket_name: str = None, 
                 object_key: str = None, status_code: int = 200, 
                 request: Request = None, response_data: Dict = None):
    """Log S3 operation to database"""
    try:
        # Temporarily simplified logging to avoid database issues
        logger.info(f"S3 Operation: {operation_type} - Bucket: {bucket_name} - Object: {object_key} - Status: {status_code}")
        
        # For now, skip database logging until schema issues are fully resolved
        # This allows the core S3 functionality to work without database errors
        return
        
        # Original logging code (commented out until database issues are fixed):
        # log_entry = {
        #     'operation_type': operation_type,
        #     'bucket_name': bucket_name,
        #     'object_key': object_key,
        #     'status_code': status_code,
        #     'request_id': str(uuid.uuid4()),
        #     'user_agent': request.headers.get('user-agent') if request else None,
        #     'source_ip': request.client.host if request else None,
        #     'request_headers': json.dumps(dict(request.headers)) if request else None,
        #     'response_headers': json.dumps(response_data) if response_data else None,
        #     'replication_info': json.dumps(response_data.get('replication_info')) if response_data and response_data.get('replication_info') else None,
        #     'created_at': datetime.utcnow()
        # }
        # 
        # query = text("""
        #     INSERT INTO operations_log 
        #     (operation_type, bucket_name, object_key, status_code, request_id, 
        #      user_agent, source_ip, request_headers, response_headers, replication_info, created_at)
        #     VALUES 
        #     (:operation_type, :bucket_name, :object_key, :status_code, :request_id,
        #      :user_agent, :source_ip, :request_headers, :response_headers, 
        #      :replication_info, :created_at)
        # """)
        # 
        # db.execute(query, log_entry)
        # db.commit()
        
    except Exception as e:
        logger.error(f"Failed to log operation: {e}")
        # Don't rollback since we're not doing database operations

@app.on_event("startup")
async def startup_event():
    """Initialize application"""
    logger.info("Starting S3 Gateway Service with real backends...")
    load_providers()
    
    if not load_s3_backends():
        logger.warning("Failed to load S3 backends - some features may not work")

# API Endpoints (must come before S3 routes)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    backend_status = {}
    for name, backend in s3_backends.items():
        backend_status[name] = {
            "enabled": backend.enabled,
            "provider": backend.provider,
            "zone": backend.zone_code
        }
    
    return {
        "status": "healthy", 
        "service": "s3-gateway",
        "backends": backend_status,
        "backend_count": len(s3_backends)
    }

@app.get("/providers")
async def list_providers():
    """List available providers"""
    global providers_df
    if providers_df is None:
        load_providers()
    
    return {
        "providers": providers_df.to_dict('records') if providers_df is not None else [],
        "count": len(providers_df) if providers_df is not None else 0
    }

@app.get("/backends")
async def list_backends():
    """List configured S3 backends"""
    backend_info = []
    for name, backend in s3_backends.items():
        backend_info.append({
            "name": backend.name,
            "provider": backend.provider,
            "zone_code": backend.zone_code,
            "region": backend.region,
            "enabled": backend.enabled,
            "is_primary": backend.is_primary
        })
    
    return {"backends": backend_info, "count": len(backend_info)}

@app.get("/bucket-config")
async def get_bucket_config():
    """Get information about the hardcoded bucket configuration"""
    return {
        "hardcoded_bucket": HARDCODED_BUCKET,
        "note": "All uploads will go to this bucket regardless of the bucket name in the request",
        "backends_count": len(s3_backends),
        "backends": [{"name": backend.name, "provider": backend.provider} for backend in s3_backends.values()]
    }

@app.post("/initialize-bucket")
async def initialize_hardcoded_bucket(db: Session = Depends(get_db)):
    """Create the hardcoded bucket in all backends"""
    
    if not s3_backends:
        raise HTTPException(status_code=503, detail="No S3 backends configured")
    
    results = {}
    success_count = 0
    
    # Create bucket in all backends
    for backend_name, backend in s3_backends.items():
        result = await backend.create_bucket(HARDCODED_BUCKET)
        results[backend_name] = result
        
        if result['status'] in ['success', 'exists']:
            success_count += 1
    
    # Store bucket metadata
    try:
        for backend_name, backend in s3_backends.items():
            if results[backend_name]['status'] in ['success', 'exists']:
                query = text("""
                    INSERT INTO buckets (bucket_name, zone_code, region, metadata, created_at)
                    VALUES (:bucket_name, :zone_code, :region, :metadata, :created_at)
                    ON CONFLICT (bucket_name, provider_id) DO NOTHING
                """)
                
                db.execute(query, {
                    'bucket_name': HARDCODED_BUCKET,
                    'zone_code': backend.zone_code,
                    'region': backend.region,
                    'metadata': json.dumps(results[backend_name]),
                    'created_at': datetime.utcnow()
                })
        
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to store bucket metadata: {e}")
        db.rollback()
    
    response_data = {
        "bucket_name": HARDCODED_BUCKET,
        "results": results,
        "success_count": success_count,
        "total_backends": len(s3_backends)
    }
    
    if success_count == 0:
        raise HTTPException(status_code=500, detail="Failed to create bucket in any backend")
    
    return response_data

# Replica Management Endpoints

@app.get("/api/replicas/status")
async def get_replication_status(db: Session = Depends(get_db), bucket: str = None, needs_sync: bool = None):
    """Get replication status for objects"""
    try:
        where_clauses = []
        params = {}
        
        if bucket:
            where_clauses.append("bucket_name = :bucket")
            params['bucket'] = bucket
            
        if needs_sync is not None:
            if needs_sync:
                where_clauses.append("current_replica_count < required_replica_count")
            else:
                where_clauses.append("current_replica_count >= required_replica_count")
        
        where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        
        # Use direct table query since view might not exist
        query = text(f"""
            SELECT o.id as object_id, o.object_key, b.bucket_name, o.primary_zone_code, 
                   o.required_replica_count, o.current_replica_count, o.sync_status,
                   CASE 
                       WHEN o.current_replica_count < o.required_replica_count THEN 'needs_sync'
                       WHEN o.current_replica_count = o.required_replica_count THEN 'complete'
                       WHEN o.current_replica_count > o.required_replica_count THEN 'over_replicated'
                   END as replication_status
            FROM objects o
            JOIN buckets b ON o.bucket_id = b.id
            {where_clause}
            ORDER BY o.object_key
        """)
        
        result = db.execute(query, params)
        replicas = [dict(row) for row in result]
        
        return {"replicas": replicas, "count": len(replicas)}
        
    except Exception as e:
        logger.error(f"Failed to fetch replication status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch replication status")

@app.get("/api/operations/log")
async def get_operations_log(db: Session = Depends(get_db), limit: int = 100):
    """Get recent operations log"""
    try:
        query = text("""
            SELECT operation_type, bucket_name, object_key, status_code, 
                   request_id, source_ip, replication_info, created_at
            FROM operations_log 
            ORDER BY created_at DESC 
            LIMIT :limit
        """)
        
        result = db.execute(query, {'limit': limit})
        operations = [dict(row) for row in result]
        
        return {"operations": operations, "count": len(operations)}
        
    except Exception as e:
        logger.error(f"Failed to fetch operations log: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch operations log")

# S3 API Real Implementation with Immutability

@app.get("/s3")
@app.get("/s3/{bucket_name}")
async def list_buckets_or_objects(
    request: Request, 
    bucket_name: str = None, 
    db: Session = Depends(get_db)
):
    """S3 ListBuckets or ListObjects operation using local metadata as authority"""
    
    if bucket_name:
        # Always use the hardcoded bucket name
        actual_bucket_name = HARDCODED_BUCKET
        
        # List objects from LOCAL METADATA instead of backends
        objects = list_objects_from_metadata(db, actual_bucket_name)
        
        response_data = {
            "source": "local_metadata",
            "object_count": len(objects),
            "immutable_storage": True
        }
        
        log_operation(db, "ListObjects", actual_bucket_name, None, 200, request, response_data)
        
        # Return S3 XML format
        xml_objects = ""
        for obj in objects:
            xml_objects += f"""
        <Contents>
            <Key>{obj['Key']}</Key>
            <LastModified>{obj['LastModified']}Z</LastModified>
            <ETag>{obj['ETag']}</ETag>
            <Size>{obj['Size']}</Size>
            <StorageClass>{obj['StorageClass']}</StorageClass>
        </Contents>"""
        
        xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>{actual_bucket_name}</Name>
    <Prefix></Prefix>
    <Marker></Marker>
    <MaxKeys>1000</MaxKeys>
    <IsTruncated>false</IsTruncated>{xml_objects}
</ListBucketResult>"""
        
        return Response(content=xml_response, media_type="application/xml")
    
    else:
        # List buckets
        log_operation(db, "ListBuckets", None, None, 200, request, {"backend_used": "all"})
        
        xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<ListAllMyBucketsResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Owner>
        <ID>s3gateway</ID>
        <DisplayName>S3 Gateway</DisplayName>
    </Owner>
    <Buckets>
        <Bucket>
            <Name>{HARDCODED_BUCKET}</Name>
            <CreationDate>{datetime.utcnow().isoformat()}Z</CreationDate>
        </Bucket>
    </Buckets>
</ListAllMyBucketsResult>"""
        
        return Response(content=xml_response, media_type="application/xml")

@app.put("/s3/{bucket_name}")
async def create_bucket(
    request: Request,
    bucket_name: str,
    db: Session = Depends(get_db)
):
    """Create the hardcoded bucket in all configured S3 backends"""
    
    if not s3_backends:
        raise HTTPException(status_code=503, detail="No S3 backends configured")
    
    # Always use the hardcoded bucket name
    actual_bucket_name = HARDCODED_BUCKET
    
    results = {}
    success_count = 0
    
    # Create bucket in all backends
    for backend_name, backend in s3_backends.items():
        result = await backend.create_bucket(actual_bucket_name)
        results[backend_name] = result
        
        if result['status'] in ['success', 'exists']:
            success_count += 1
    
    # Store bucket metadata
    try:
        for backend_name, backend in s3_backends.items():
            if results[backend_name]['status'] in ['success', 'exists']:
                query = text("""
                    INSERT INTO buckets (bucket_name, zone_code, region, metadata, created_at)
                    VALUES (:bucket_name, :zone_code, :region, :metadata, :created_at)
                    ON CONFLICT (bucket_name, provider_id) DO NOTHING
                """)
                
                db.execute(query, {
                    'bucket_name': actual_bucket_name,
                    'zone_code': backend.zone_code,
                    'region': backend.region,
                    'metadata': json.dumps(results[backend_name]),
                    'created_at': datetime.utcnow()
                })
        
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to store bucket metadata: {e}")
        db.rollback()
    
    response_data = {
        "results": results,
        "success_count": success_count,
        "total_backends": len(s3_backends),
        "actual_bucket_used": actual_bucket_name,
        "requested_bucket": bucket_name
    }
    
    status_code = 200 if success_count > 0 else 500
    log_operation(db, "CreateBucket", actual_bucket_name, None, status_code, request, response_data)
    
    if success_count == 0:
        raise HTTPException(status_code=500, detail="Failed to create bucket in any backend")
    
    # Return success if at least one backend succeeded
    backend_zones = [backend.zone_code for name, backend in s3_backends.items() 
                    if results[name]['status'] in ['success', 'exists']]
    
    return Response(status_code=200, headers={
        "Location": f"/{actual_bucket_name}",
        "X-Backend-Count": str(success_count),
        "X-Backend-Zones": ",".join(backend_zones),
        "X-Actual-Bucket": actual_bucket_name
    })

@app.get("/s3/{bucket_name}/{object_key:path}")
async def get_object(
    request: Request,
    bucket_name: str,
    object_key: str,
    db: Session = Depends(get_db)
):
    """Get object using local metadata as authority for immutable storage"""
    
    if not s3_backends:
        raise HTTPException(status_code=503, detail="No S3 backends configured")
    
    # Always use the hardcoded bucket name
    actual_bucket_name = HARDCODED_BUCKET
    
    # CHECK LOCAL METADATA FIRST - this is the single source of truth
    metadata = check_object_exists_in_metadata(db, actual_bucket_name, object_key)
    if not metadata:
        log_operation(db, "GetObject", actual_bucket_name, object_key, 404, request, {"error": "not_found_in_metadata"})
        raise HTTPException(status_code=404, detail="Object not found in metadata")
    
    # Try to get from the primary zone specified in metadata
    primary_zone = metadata['primary_zone_code']
    version_id = metadata['version_id']
    
    # Try primary backend first
    primary_backend = None
    for backend in s3_backends.values():
        if backend.zone_code == primary_zone:
            primary_backend = backend
            break
    
    if not primary_backend:
        primary_backend = list(s3_backends.values())[0]  # Fallback
    
    backends_to_try = [primary_backend]
    backends_to_try.extend([b for b in s3_backends.values() if b != primary_backend])
    
    for backend in backends_to_try:
        result = await backend.get_object(actual_bucket_name, object_key, version_id)
        
        if result['status'] == 'success':
            response_data = {
                "backend_used": backend.name,
                "size": result['size'],
                "actual_bucket_used": actual_bucket_name,
                "requested_bucket": bucket_name,
                "version_id": version_id,
                "metadata_authority": True
            }
            
            log_operation(db, "GetObject", actual_bucket_name, object_key, 200, request, response_data)
            
            return Response(
                content=result['body'],
                media_type=result['content_type'],
                headers={
                    "ETag": f'"{result["etag"]}"',
                    "Last-Modified": result['last_modified'].strftime("%a, %d %b %Y %H:%M:%S GMT") if result.get('last_modified') else "",
                    "Content-Length": str(result['size']),
                    "X-Backend-Used": backend.name,
                    "X-Zone": backend.zone_code,
                    "X-Actual-Bucket": actual_bucket_name,
                    "X-Version-Id": version_id,
                    "X-Immutable": "true"
                }
            )
    
    # Object exists in metadata but not found in any backend - data integrity issue
    log_operation(db, "GetObject", actual_bucket_name, object_key, 500, request, {"error": "metadata_backend_mismatch"})
    raise HTTPException(status_code=500, detail="Object exists in metadata but not found in backends")

@app.put("/s3/{bucket_name}/{object_key:path}")
async def put_object(
    request: Request,
    bucket_name: str,
    object_key: str,
    db: Session = Depends(get_db)
):
    """Upload object with versioning and immutability support"""
    
    if not s3_backends:
        raise HTTPException(status_code=503, detail="No S3 backends configured")
    
    # Always use the hardcoded bucket name
    actual_bucket_name = HARDCODED_BUCKET
    
    # Check bucket immutability settings
    is_immutable, versioning_enabled = check_bucket_immutability(db, actual_bucket_name)
    
    # Generate our own version ID for consistent versioning across backends
    version_id = generate_version_id()
    
    # Read request body
    body = await request.body()
    content_type = request.headers.get('content-type', 'binary/octet-stream')
    
    results = {}
    success_count = 0
    
    # First ensure the hardcoded bucket exists in all backends
    for backend_name, backend in s3_backends.items():
        bucket_result = await backend.create_bucket(actual_bucket_name)
        logger.info(f"Bucket creation result for {backend_name}: {bucket_result}")
    
    # Upload to all backends with our version ID
    for backend_name, backend in s3_backends.items():
        result = await backend.put_object(actual_bucket_name, object_key, body, content_type, version_id)
        results[backend_name] = result
        
        if result['status'] == 'success':
            success_count += 1
            logger.info(f"Successfully uploaded {object_key} (version {version_id}) to {backend_name}")
        else:
            logger.error(f"Failed to upload {object_key} to {backend_name}: {result}")
    
    # Store object metadata with version tracking
    try:
        primary_result = None
        replica_zones = []
        
        for backend_name, backend in s3_backends.items():
            if results[backend_name]['status'] == 'success':
                if backend.is_primary:
                    primary_result = results[backend_name]
                    primary_zone = backend.zone_code
                else:
                    replica_zones.append(backend.zone_code)
        
        if not primary_result:
            # If no primary, use first successful result
            for backend_name, backend in s3_backends.items():
                if results[backend_name]['status'] == 'success':
                    primary_result = results[backend_name]
                    primary_zone = backend.zone_code
                    break
        
        # Insert object metadata with our version ID
        object_query = text("""
            INSERT INTO objects (object_key, bucket_id, size_bytes, etag, content_type, 
                               primary_zone_code, replica_zones, required_replica_count, 
                               current_replica_count, sync_status, version_id, 
                               is_delete_marker, created_at)
            SELECT :object_key, b.id, :size_bytes, :etag, :content_type, 
                   :primary_zone, :replica_zones, :required_replicas, :current_replicas, 
                   'complete', :version_id, false, :created_at
            FROM buckets b WHERE b.bucket_name = :bucket_name
            RETURNING id
        """)
        
        result = db.execute(object_query, {
            'object_key': object_key,
            'bucket_name': actual_bucket_name,
            'size_bytes': len(body),
            'etag': primary_result['etag'] if primary_result else 'unknown',
            'content_type': content_type,
            'primary_zone': primary_zone if primary_result else 'unknown',
            'replica_zones': replica_zones,
            'required_replicas': len(s3_backends),
            'current_replicas': success_count,
            'version_id': version_id,
            'created_at': datetime.utcnow()
        })
        
        object_id = result.fetchone()[0]
        db.commit()
        
    except Exception as e:
        logger.error(f"Failed to store object metadata: {e}")
        db.rollback()
    
    response_data = {
        "results": results,
        "success_count": success_count,
        "total_backends": len(s3_backends),
        "replication_complete": success_count == len(s3_backends),
        "actual_bucket_used": actual_bucket_name,
        "requested_bucket": bucket_name,
        "version_id": version_id,
        "immutable": is_immutable,
        "versioning_enabled": versioning_enabled
    }
    
    status_code = 200 if success_count > 0 else 500
    log_operation(db, "PutObject", actual_bucket_name, object_key, status_code, request, response_data)
    
    if success_count == 0:
        raise HTTPException(status_code=500, detail=f"Failed to upload to any backend in bucket {actual_bucket_name}")
    
    # Return success with replication info
    backend_zones = [backend.zone_code for name, backend in s3_backends.items() 
                    if results[name]['status'] == 'success']
    
    return Response(
        status_code=200,
        headers={
            "ETag": f'"{primary_result["etag"]}"' if primary_result else '"unknown"',
            "X-Replication-Count": str(success_count),
            "X-Backend-Zones": ",".join(backend_zones),
            "X-Replication-Status": "complete" if success_count == len(s3_backends) else "partial",
            "X-Actual-Bucket": actual_bucket_name,
            "X-Requested-Bucket": bucket_name,
            "X-Version-Id": version_id,
            "X-Immutable": str(is_immutable).lower(),
            "X-Versioning": str(versioning_enabled).lower()
        }
    )

@app.delete("/s3/{bucket_name}/{object_key:path}")
async def delete_object(
    request: Request,
    bucket_name: str,
    object_key: str,
    db: Session = Depends(get_db)
):
    """IMMUTABLE DELETE: Only mark as deleted in metadata, NEVER delete from backends"""
    
    # Always use the hardcoded bucket name
    actual_bucket_name = HARDCODED_BUCKET
    
    # Check bucket immutability settings
    is_immutable, versioning_enabled = check_bucket_immutability(db, actual_bucket_name)
    
    # Check if object exists in metadata
    metadata = check_object_exists_in_metadata(db, actual_bucket_name, object_key)
    if not metadata:
        log_operation(db, "DeleteObject", actual_bucket_name, object_key, 404, request, {"error": "not_found_in_metadata"})
        raise HTTPException(status_code=404, detail="Object not found")
    
    if is_immutable:
        # IMMUTABLE STORAGE: Create delete marker in metadata, keep backend data
        delete_version_id = generate_version_id()
        
        try:
            # Create delete marker in metadata
            delete_query = text("""
                INSERT INTO objects (object_key, bucket_id, size_bytes, etag, content_type, 
                                   primary_zone_code, replica_zones, required_replica_count, 
                                   current_replica_count, sync_status, version_id, 
                                   is_delete_marker, created_at)
                SELECT :object_key, b.id, 0, 'delete-marker', 'application/x-delete-marker', 
                       :primary_zone, :replica_zones, :required_replicas, :current_replicas, 
                       'complete', :version_id, true, :created_at
                FROM buckets b WHERE b.bucket_name = :bucket_name
            """)
            
            db.execute(delete_query, {
                'object_key': object_key,
                'bucket_name': actual_bucket_name,
                'primary_zone': metadata['primary_zone_code'],
                'replica_zones': [],
                'required_replicas': 0,
                'current_replicas': 0,
                'version_id': delete_version_id,
                'created_at': datetime.utcnow()
            })
            
            db.commit()
            
            response_data = {
                "immutable_delete": True,
                "delete_marker_created": True,
                "delete_version_id": delete_version_id,
                "original_version_id": metadata['version_id'],
                "backend_data_preserved": True,
                "actual_bucket_used": actual_bucket_name,
                "requested_bucket": bucket_name
            }
            
            log_operation(db, "DeleteObject", actual_bucket_name, object_key, 200, request, response_data)
            
            return Response(
                status_code=204,
                headers={
                    "X-Delete-Marker": "true",
                    "X-Delete-Version-Id": delete_version_id,
                    "X-Immutable": "true",
                    "X-Backend-Data-Preserved": "true",
                    "X-Actual-Bucket": actual_bucket_name
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to create delete marker: {e}")
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to create delete marker")
    
    else:
        # Non-immutable bucket: This shouldn't happen with our hardcoded bucket
        # but we'll handle it for completeness
        log_operation(db, "DeleteObject", actual_bucket_name, object_key, 403, request, {"error": "immutability_required"})
        raise HTTPException(status_code=403, detail="Delete operations require immutable storage mode")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    ) 