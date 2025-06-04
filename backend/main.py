from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import logging
import json
import os
from datetime import datetime
from pathlib import Path
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create snapshots directory
SNAPSHOTS_DIR = Path("snapshots")
SNAPSHOTS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="S3 Service Discovery API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class S3Credentials(BaseModel):
    access_key: str
    secret_key: str
    region: str = "default"
    endpoint_url: str

class BucketInfo(BaseModel):
    name: str
    creation_date: Optional[str]

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
    id: str
    timestamp: str
    endpoint: str
    region: str
    buckets: List[Dict[str, Any]]
    total_size: int
    total_files: int

class SnapshotMetadata(BaseModel):
    id: str
    timestamp: str
    endpoint: str
    region: str
    bucket_count: int
    total_files: int
    total_size: int
    filename: str

@app.post("/discover/buckets", response_model=List[BucketInfo])
async def list_buckets(credentials: S3Credentials):
    """List all buckets accessible with the provided credentials"""
    try:
        # Create S3 client with provided credentials
        s3_client = boto3.client(
            's3',
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            endpoint_url=credentials.endpoint_url,
            region_name=credentials.region if credentials.region != "default" else None
        )
        
        # List buckets
        response = s3_client.list_buckets()
        
        buckets = []
        for bucket in response.get('Buckets', []):
            buckets.append(BucketInfo(
                name=bucket['Name'],
                creation_date=bucket.get('CreationDate', '').isoformat() if bucket.get('CreationDate') else None
            ))
        
        logger.info(f"Successfully listed {len(buckets)} buckets")
        return buckets
        
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidAccessKeyId':
            raise HTTPException(status_code=401, detail="Invalid access key")
        elif error_code == 'SignatureDoesNotMatch':
            raise HTTPException(status_code=401, detail="Invalid secret key")
        else:
            raise HTTPException(status_code=400, detail=f"S3 error: {str(e)}")
    except Exception as e:
        logger.error(f"Error listing buckets: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.post("/discover/bucket/{bucket_name}", response_model=BucketDetails)
async def get_bucket_details(bucket_name: str, credentials: S3Credentials):
    """Get details of a specific bucket including file list"""
    try:
        # Create S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            endpoint_url=credentials.endpoint_url,
            region_name=credentials.region if credentials.region != "default" else None
        )
        
        # Check versioning status
        versioning_status = None
        try:
            versioning_response = s3_client.get_bucket_versioning(Bucket=bucket_name)
            versioning_status = versioning_response.get('Status', 'Disabled')
        except:
            versioning_status = 'Unknown'
        
        # List objects in bucket
        files = []
        total_size = 0
        continuation_token = None
        
        while True:
            if continuation_token:
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name,
                    ContinuationToken=continuation_token
                )
            else:
                response = s3_client.list_objects_v2(Bucket=bucket_name)
            
            for obj in response.get('Contents', []):
                files.append(FileInfo(
                    key=obj['Key'],
                    size=obj['Size'],
                    last_modified=obj['LastModified'].isoformat(),
                    etag=obj['ETag'].strip('"')
                ))
                total_size += obj['Size']
            
            # Check if there are more objects
            if response.get('IsTruncated'):
                continuation_token = response.get('NextContinuationToken')
            else:
                break
        
        return BucketDetails(
            name=bucket_name,
            files=files,
            total_size=total_size,
            file_count=len(files),
            versioning_status=versioning_status
        )
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"S3 ClientError for bucket {bucket_name}: {error_code} - {error_message}")
        if error_code == 'NoSuchBucket':
            raise HTTPException(status_code=404, detail="Bucket not found")
        elif error_code == 'AccessDenied':
            raise HTTPException(status_code=403, detail="Access denied to bucket")
        else:
            raise HTTPException(status_code=400, detail=f"S3 error: {error_code} - {error_message}")
    except Exception as e:
        logger.error(f"Error getting bucket details for {bucket_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.post("/discover/bucket/{bucket_name}/versions", response_model=BucketVersions)
async def get_bucket_versions(bucket_name: str, credentials: S3Credentials):
    """Get version information for objects in a bucket (if versioning is enabled)"""
    try:
        # Create S3 client
        s3_client = boto3.client(
            's3',
            aws_access_key_id=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            endpoint_url=credentials.endpoint_url,
            region_name=credentials.region if credentials.region != "default" else None
        )
        
        # Check versioning status
        versioning_response = s3_client.get_bucket_versioning(Bucket=bucket_name)
        versioning_status = versioning_response.get('Status', 'Disabled')
        
        if versioning_status not in ['Enabled', 'Suspended']:
            return BucketVersions(
                name=bucket_name,
                versioning_status=versioning_status,
                versions=[]
            )
        
        # List object versions
        versions = []
        key_marker = None
        version_id_marker = None
        
        while True:
            if key_marker:
                response = s3_client.list_object_versions(
                    Bucket=bucket_name,
                    KeyMarker=key_marker,
                    VersionIdMarker=version_id_marker
                )
            else:
                response = s3_client.list_object_versions(Bucket=bucket_name)
            
            # Process versions
            for version in response.get('Versions', []):
                versions.append(VersionInfo(
                    key=version['Key'],
                    version_id=version['VersionId'],
                    size=version['Size'],
                    last_modified=version['LastModified'].isoformat(),
                    etag=version['ETag'].strip('"'),
                    is_latest=version.get('IsLatest', False),
                    is_delete_marker=False
                ))
            
            # Process delete markers
            for marker in response.get('DeleteMarkers', []):
                versions.append(VersionInfo(
                    key=marker['Key'],
                    version_id=marker['VersionId'],
                    size=0,
                    last_modified=marker['LastModified'].isoformat(),
                    etag='',
                    is_latest=marker.get('IsLatest', False),
                    is_delete_marker=True
                ))
            
            # Check if there are more versions
            if response.get('IsTruncated'):
                key_marker = response.get('NextKeyMarker')
                version_id_marker = response.get('NextVersionIdMarker')
            else:
                break
        
        return BucketVersions(
            name=bucket_name,
            versioning_status=versioning_status,
            versions=versions
        )
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'NoSuchBucket':
            raise HTTPException(status_code=404, detail="Bucket not found")
        elif error_code == 'AccessDenied':
            raise HTTPException(status_code=403, detail="Access denied to bucket versioning")
        else:
            raise HTTPException(status_code=400, detail=f"S3 error: {str(e)}")
    except Exception as e:
        logger.error(f"Error getting bucket versions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.post("/snapshot/save", response_model=SnapshotMetadata)
async def save_snapshot(snapshot: DiscoverySnapshot):
    """Save a discovery snapshot to the backend"""
    try:
        # Generate unique ID and filename
        snapshot_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        filename = f"snapshot_{snapshot.endpoint.replace('://', '_').replace('/', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = SNAPSHOTS_DIR / filename
        
        # Prepare snapshot data
        snapshot_data = {
            "id": snapshot_id,
            "timestamp": timestamp,
            "endpoint": snapshot.endpoint,
            "region": snapshot.region,
            "buckets": snapshot.buckets,
            "total_size": snapshot.total_size,
            "total_files": snapshot.total_files
        }
        
        # Save to file
        with open(filepath, 'w') as f:
            json.dump(snapshot_data, f, indent=2)
        
        logger.info(f"Saved snapshot to {filepath}")
        
        # Return metadata
        return SnapshotMetadata(
            id=snapshot_id,
            timestamp=timestamp,
            endpoint=snapshot.endpoint,
            region=snapshot.region,
            bucket_count=len(snapshot.buckets),
            total_files=snapshot.total_files,
            total_size=snapshot.total_size,
            filename=filename
        )
        
    except Exception as e:
        logger.error(f"Error saving snapshot: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save snapshot: {str(e)}")

@app.get("/snapshot/list", response_model=List[SnapshotMetadata])
async def list_snapshots():
    """List all saved snapshots"""
    try:
        snapshots = []
        
        for filepath in SNAPSHOTS_DIR.glob("snapshot_*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    
                snapshots.append(SnapshotMetadata(
                    id=data.get('id', 'unknown'),
                    timestamp=data.get('timestamp', ''),
                    endpoint=data.get('endpoint', ''),
                    region=data.get('region', ''),
                    bucket_count=len(data.get('buckets', [])),
                    total_files=data.get('total_files', 0),
                    total_size=data.get('total_size', 0),
                    filename=filepath.name
                ))
            except Exception as e:
                logger.error(f"Error reading snapshot {filepath}: {str(e)}")
                continue
        
        # Sort by timestamp (newest first)
        snapshots.sort(key=lambda x: x.timestamp, reverse=True)
        
        return snapshots
        
    except Exception as e:
        logger.error(f"Error listing snapshots: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list snapshots: {str(e)}")

@app.get("/snapshot/{snapshot_id}")
async def get_snapshot(snapshot_id: str):
    """Get a specific snapshot by ID"""
    try:
        # Find snapshot file
        for filepath in SNAPSHOTS_DIR.glob("snapshot_*.json"):
            with open(filepath, 'r') as f:
                data = json.load(f)
                if data.get('id') == snapshot_id:
                    return data
        
        raise HTTPException(status_code=404, detail="Snapshot not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting snapshot: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get snapshot: {str(e)}")

@app.delete("/snapshot/{snapshot_id}")
async def delete_snapshot(snapshot_id: str):
    """Delete a specific snapshot"""
    try:
        # Find and delete snapshot file
        for filepath in SNAPSHOTS_DIR.glob("snapshot_*.json"):
            with open(filepath, 'r') as f:
                data = json.load(f)
                if data.get('id') == snapshot_id:
                    os.remove(filepath)
                    logger.info(f"Deleted snapshot {filepath}")
                    return {"message": "Snapshot deleted successfully"}
        
        raise HTTPException(status_code=404, detail="Snapshot not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting snapshot: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete snapshot: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 