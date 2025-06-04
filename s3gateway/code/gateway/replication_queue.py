#!/usr/bin/env python3
"""
Replication Queue System
Handles background replication operations for S3 objects across multiple backends.
"""

import json
import logging
import asyncio
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass
import threading
import queue
import time

logger = logging.getLogger(__name__)


class ReplicationJobType(Enum):
    ADD_REPLICA = "add_replica"
    REMOVE_REPLICA = "remove_replica"
    DELETE_BUCKET_REPLICA = "delete_bucket_replica"  # Delete entire bucket from a zone
    CLEANUP_EMPTY_BUCKET = "cleanup_empty_bucket"    # Clean up empty backend bucket
    VERIFY_REPLICA = "verify_replica"
    MIGRATE_REPLICA = "migrate_replica"
    SYNC_METADATA = "sync_metadata"


class ReplicationJobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class ReplicationJob:
    """Represents a replication job"""
    job_id: str
    job_type: ReplicationJobType
    customer_id: str
    bucket_name: str
    object_key: str
    source_zone: str
    target_zone: str
    priority: int = 5  # 1=highest, 10=lowest
    retry_count: int = 0
    max_retries: int = 3
    status: ReplicationJobStatus = ReplicationJobStatus.QUEUED
    created_at: datetime = None
    started_at: datetime = None
    completed_at: datetime = None
    error_message: str = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}


class ReplicationQueue:
    """Thread-safe priority queue for replication jobs"""
    
    def __init__(self, max_workers: int = 3):
        self.queue = queue.PriorityQueue()
        self.active_jobs = {}  # job_id -> ReplicationJob
        self.completed_jobs = {}  # job_id -> ReplicationJob (last 1000)
        self.max_workers = max_workers
        self.workers = []
        self.running = False
        self.lock = threading.Lock()
        self.db_session_factory = None
        
    def set_database_session_factory(self, session_factory):
        """Set database session factory for workers"""
        self.db_session_factory = session_factory
    
    def start(self):
        """Start the queue workers"""
        if self.running:
            return
            
        self.running = True
        logger.info(f"Starting replication queue with {self.max_workers} workers")
        
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"ReplicationWorker-{i+1}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
    
    def stop(self):
        """Stop the queue workers"""
        logger.info("Stopping replication queue...")
        self.running = False
        
        # Signal workers to stop
        for _ in range(self.max_workers):
            self.queue.put((0, None))  # Sentinel value
            
        # Wait for workers to finish
        for worker in self.workers:
            worker.join(timeout=10)
        
        self.workers.clear()
        logger.info("Replication queue stopped")
    
    def add_job(self, job: ReplicationJob) -> str:
        """Add a replication job to the queue"""
        with self.lock:
            # Priority queue sorts by (priority, insertion_order)
            # Lower priority number = higher priority
            insertion_order = time.time()
            self.queue.put((job.priority, insertion_order, job))
            self.active_jobs[job.job_id] = job
            
        logger.info(f"Added replication job: {job.job_id} ({job.job_type.value})")
        return job.job_id
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get status of a specific job"""
        with self.lock:
            if job_id in self.active_jobs:
                job = self.active_jobs[job_id]
                return {
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "job_type": job.job_type.value,
                    "customer_id": job.customer_id,
                    "bucket_name": job.bucket_name,
                    "object_key": job.object_key,
                    "source_zone": job.source_zone,
                    "target_zone": job.target_zone,
                    "priority": job.priority,
                    "retry_count": job.retry_count,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error_message": job.error_message
                }
            elif job_id in self.completed_jobs:
                job = self.completed_jobs[job_id]
                return {
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "job_type": job.job_type.value,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error_message": job.error_message
                }
        return None
    
    def list_active_jobs(self) -> List[Dict]:
        """List all active jobs"""
        with self.lock:
            return [self.get_job_status(job_id) for job_id in self.active_jobs.keys()]
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a queued job"""
        with self.lock:
            if job_id in self.active_jobs:
                job = self.active_jobs[job_id]
                if job.status == ReplicationJobStatus.QUEUED:
                    job.status = ReplicationJobStatus.CANCELLED
                    job.completed_at = datetime.utcnow()
                    self._move_to_completed(job)
                    return True
        return False
    
    def _worker_loop(self):
        """Main worker loop"""
        worker_name = threading.current_thread().name
        logger.info(f"{worker_name} started")
        
        while self.running:
            try:
                # Get job from queue (blocks until available)
                try:
                    priority, insertion_order, job = self.queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # Check for sentinel value (stop signal)
                if job is None:
                    break
                
                # Process the job
                self._process_job(job, worker_name)
                
            except Exception as e:
                logger.error(f"{worker_name} error: {e}")
                
        logger.info(f"{worker_name} stopped")
    
    def _process_job(self, job: ReplicationJob, worker_name: str):
        """Process a single replication job"""
        logger.info(f"{worker_name} processing job {job.job_id}")
        
        with self.lock:
            job.status = ReplicationJobStatus.RUNNING
            job.started_at = datetime.utcnow()
        
        try:
            # Execute the replication operation
            success = self._execute_replication(job)
            
            with self.lock:
                if success:
                    job.status = ReplicationJobStatus.COMPLETED
                    logger.info(f"Job {job.job_id} completed successfully")
                else:
                    job.retry_count += 1
                    if job.retry_count >= job.max_retries:
                        job.status = ReplicationJobStatus.FAILED
                        logger.error(f"Job {job.job_id} failed after {job.retry_count} retries")
                    else:
                        job.status = ReplicationJobStatus.RETRYING
                        logger.warning(f"Job {job.job_id} failed, retrying ({job.retry_count}/{job.max_retries})")
                        # Re-queue for retry
                        self.queue.put((job.priority + 1, time.time(), job))
                        return
                
                job.completed_at = datetime.utcnow()
                self._move_to_completed(job)
                
        except Exception as e:
            logger.error(f"Job {job.job_id} error: {e}")
            with self.lock:
                job.status = ReplicationJobStatus.FAILED
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                self._move_to_completed(job)
    
    def _execute_replication(self, job: ReplicationJob) -> bool:
        """Execute the actual replication operation"""
        try:
            if job.job_type == ReplicationJobType.ADD_REPLICA:
                return self._add_replica(job)
            elif job.job_type == ReplicationJobType.REMOVE_REPLICA:
                return self._remove_replica(job)
            elif job.job_type == ReplicationJobType.DELETE_BUCKET_REPLICA:
                return self._delete_bucket_replica(job)
            elif job.job_type == ReplicationJobType.CLEANUP_EMPTY_BUCKET:
                return self._cleanup_empty_bucket(job)
            elif job.job_type == ReplicationJobType.VERIFY_REPLICA:
                return self._verify_replica(job)
            elif job.job_type == ReplicationJobType.SYNC_METADATA:
                return self._sync_metadata(job)
            else:
                logger.error(f"Unknown job type: {job.job_type}")
                return False
                
        except Exception as e:
            logger.error(f"Replication execution failed: {e}")
            job.error_message = str(e)
            return False
    
    def _add_replica(self, job: ReplicationJob) -> bool:
        """Add a replica to target zone"""
        logger.info(f"Adding replica for {job.bucket_name}/{job.object_key} to {job.target_zone}")
        
        try:
            # 1. Get bucket mapping to find backend bucket names
            backend_mapping = self._get_bucket_mapping(job.customer_id, job.bucket_name)
            if not backend_mapping:
                logger.error(f"No bucket mapping found for {job.customer_id}:{job.bucket_name}")
                return False
            
            # 2. Get source and target backend configurations
            source_backend_config = self._get_backend_config_for_zone(job.source_zone)
            target_backend_config = self._get_backend_config_for_zone(job.target_zone)
            
            if not source_backend_config or not target_backend_config:
                logger.error(f"Backend configuration not found for zones {job.source_zone} or {job.target_zone}")
                return False
            
            # 3. Get object data from source backend
            source_bucket_name = backend_mapping.get(self._zone_to_backend_id(job.source_zone))
            target_bucket_name = backend_mapping.get(self._zone_to_backend_id(job.target_zone))
            
            if not source_bucket_name or not target_bucket_name:
                logger.error(f"Backend bucket names not found in mapping")
                return False
            
            # 4. Copy object data between backends
            success = self._copy_object_between_backends(
                source_backend_config, source_bucket_name,
                target_backend_config, target_bucket_name,
                job.object_key
            )
            
            if not success:
                logger.error(f"Failed to copy object data from {job.source_zone} to {job.target_zone}")
                return False
            
            logger.info(f"Successfully copied object data to {job.target_zone}")
            
        except Exception as e:
            logger.error(f"Error during object replication: {e}")
            return False
        
        # 5. Update database metadata
        if self.db_session_factory:
            try:
                with self.db_session_factory() as db:
                    from sqlalchemy import text
                    
                    # Update object metadata to include new replica
                    query = text("""
                        UPDATE object_metadata 
                        SET replicas = replicas || :new_replica::jsonb,
                            current_replica_count = current_replica_count + 1,
                            sync_status = 'complete',
                            updated_at = CURRENT_TIMESTAMP
                        WHERE customer_id = :customer_id 
                          AND bucket_name = :bucket_name 
                          AND object_key = :object_key
                    """)
                    
                    new_replica = json.dumps({
                        "provider_id": job.target_zone,
                        "status": "active",
                        "version": "v1",
                        "sync_time": datetime.utcnow().isoformat(),
                        "job_id": job.job_id
                    })
                    
                    db.execute(query, {
                        'customer_id': job.customer_id,
                        'bucket_name': job.bucket_name,
                        'object_key': job.object_key,
                        'new_replica': new_replica
                    })
                    db.commit()
                    
                    logger.info(f"Updated database for replica addition: {job.job_id}")
                    return True
                    
            except Exception as e:
                logger.error(f"Database update failed for add replica: {e}")
                return False
        
        return True
    
    def _remove_replica(self, job: ReplicationJob) -> bool:
        """Remove a replica from target zone"""
        logger.info(f"Removing replica for {job.bucket_name}/{job.object_key} from {job.target_zone}")
        
        try:
            # 1. Get bucket mapping to find backend bucket name
            backend_mapping = self._get_bucket_mapping(job.customer_id, job.bucket_name)
            if not backend_mapping:
                logger.error(f"No bucket mapping found for {job.customer_id}:{job.bucket_name}")
                return False
            
            # 2. Get target backend configuration
            target_backend_config = self._get_backend_config_for_zone(job.target_zone)
            if not target_backend_config:
                logger.error(f"Backend configuration not found for zone {job.target_zone}")
                return False
            
            # 3. Delete object from target backend
            target_bucket_name = backend_mapping.get(self._zone_to_backend_id(job.target_zone))
            if not target_bucket_name:
                logger.error(f"Backend bucket name not found for zone {job.target_zone}")
                return False
            
            success = self._delete_object_from_backend(
                target_backend_config, target_bucket_name, job.object_key
            )
            
            if not success:
                logger.error(f"Failed to delete object from {job.target_zone}")
                return False
            
            logger.info(f"Successfully deleted object from {job.target_zone}")
            
        except Exception as e:
            logger.error(f"Error during object deletion: {e}")
            return False
        
        # 4. Update database metadata
        if self.db_session_factory:
            try:
                with self.db_session_factory() as db:
                    from sqlalchemy import text
                    
                    # Remove replica from object metadata
                    query = text("""
                        UPDATE object_metadata 
                        SET replicas = (
                            SELECT jsonb_agg(replica)
                            FROM jsonb_array_elements(replicas) AS replica
                            WHERE replica->>'provider_id' != :target_zone
                        ),
                        current_replica_count = current_replica_count - 1,
                        updated_at = CURRENT_TIMESTAMP
                        WHERE customer_id = :customer_id 
                          AND bucket_name = :bucket_name 
                          AND object_key = :object_key
                    """)
                    
                    db.execute(query, {
                        'customer_id': job.customer_id,
                        'bucket_name': job.bucket_name,
                        'object_key': job.object_key,
                        'target_zone': job.target_zone
                    })
                    db.commit()
                    
                    logger.info(f"Updated database for replica removal: {job.job_id}")
                    return True
                    
            except Exception as e:
                logger.error(f"Database update failed for remove replica: {e}")
                return False
        
        return True
    
    def _get_bucket_mapping(self, customer_id: str, bucket_name: str) -> Optional[Dict[str, str]]:
        """Get bucket mapping from database"""
        if not self.db_session_factory:
            return None
            
        try:
            with self.db_session_factory() as db:
                from sqlalchemy import text
                
                query = text("""
                    SELECT backend_mapping
                    FROM bucket_mappings 
                    WHERE customer_id = :customer_id AND logical_name = :bucket_name
                """)
                
                result = db.execute(query, {
                    'customer_id': customer_id,
                    'bucket_name': bucket_name
                }).fetchone()
                
                if result:
                    return json.loads(result[0])
                return None
                
        except Exception as e:
            logger.error(f"Failed to get bucket mapping: {e}")
            return None
    
    def _get_backend_config_for_zone(self, zone: str) -> Optional[Dict]:
        """Get S3 backend configuration for a specific zone"""
        # This would load from s3_backends.json or configuration
        # For now, return a mock configuration
        zone_to_backend = {
            'fi-hel-st-1': {
                'endpoint_url': 'https://hel1.your-objectstorage.com',
                'aws_access_key_id': 'your-access-key',
                'aws_secret_access_key': 'your-secret-key',
                'region_name': 'fi-hel'
            },
            'de-fra-st-1': {
                'endpoint_url': 'https://fra1.your-objectstorage.com',
                'aws_access_key_id': 'your-access-key',
                'aws_secret_access_key': 'your-secret-key',
                'region_name': 'de-fra'
            },
            'fr-par-st-1': {
                'endpoint_url': 'https://par1.your-objectstorage.com',
                'aws_access_key_id': 'your-access-key',
                'aws_secret_access_key': 'your-secret-key',
                'region_name': 'fr-par'
            }
        }
        return zone_to_backend.get(zone)
    
    def _zone_to_backend_id(self, zone: str) -> str:
        """Convert zone to backend ID for bucket mapping lookup"""
        if 'st-1' in zone:
            return 'spacetime'
        elif 'uc-1' in zone:
            return 'upcloud'
        elif 'hz-1' in zone:
            return 'hetzner'
        return 'spacetime'  # default
    
    def _copy_object_between_backends(self, source_config: Dict, source_bucket: str,
                                    target_config: Dict, target_bucket: str, object_key: str) -> bool:
        """Copy object data between S3 backends"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            # Create S3 clients for source and target
            source_s3 = boto3.client('s3', **source_config)
            target_s3 = boto3.client('s3', **target_config)
            
            # Get object from source
            logger.info(f"Getting object {object_key} from {source_bucket} on source backend")
            response = source_s3.get_object(Bucket=source_bucket, Key=object_key)
            object_data = response['Body'].read()
            
            # Get object metadata
            metadata = response.get('Metadata', {})
            content_type = response.get('ContentType', 'binary/octet-stream')
            
            # Put object to target
            logger.info(f"Putting object {object_key} to {target_bucket} on target backend")
            target_s3.put_object(
                Bucket=target_bucket,
                Key=object_key,
                Body=object_data,
                ContentType=content_type,
                Metadata=metadata
            )
            
            logger.info(f"Successfully copied {len(object_data)} bytes")
            return True
            
        except ClientError as e:
            logger.error(f"S3 client error during copy: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during copy: {e}")
            return False
    
    def _delete_object_from_backend(self, backend_config: Dict, bucket_name: str, object_key: str) -> bool:
        """Delete object from S3 backend"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            # Create S3 client
            s3_client = boto3.client('s3', **backend_config)
            
            # Delete object
            logger.info(f"Deleting object {object_key} from {bucket_name}")
            s3_client.delete_object(Bucket=bucket_name, Key=object_key)
            
            logger.info(f"Successfully deleted object")
            return True
            
        except ClientError as e:
            # Handle case where object doesn't exist (already deleted)
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info(f"Object {object_key} already deleted or doesn't exist")
                return True
            logger.error(f"S3 client error during deletion: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during deletion: {e}")
            return False
    
    def _verify_replica(self, job: ReplicationJob) -> bool:
        """Verify replica integrity"""
        logger.info(f"Verifying replica for {job.bucket_name}/{job.object_key} in {job.target_zone}")
        
        # TODO: Implement replica verification
        # 1. Check if object exists in target zone
        # 2. Verify checksum/etag matches
        # 3. Update replica status
        
        time.sleep(0.2)  # Simulate work
        return True
    
    def _sync_metadata(self, job: ReplicationJob) -> bool:
        """Sync metadata across replicas"""
        logger.info(f"Syncing metadata for {job.bucket_name}/{job.object_key}")
        
        # TODO: Implement metadata sync
        # 1. Get metadata from primary replica
        # 2. Update all other replicas
        
        time.sleep(0.1)  # Simulate work
        return True
    
    def _move_to_completed(self, job: ReplicationJob):
        """Move job from active to completed (with size limit)"""
        if job.job_id in self.active_jobs:
            del self.active_jobs[job.job_id]
        
        self.completed_jobs[job.job_id] = job
        
        # Keep only last 1000 completed jobs
        if len(self.completed_jobs) > 1000:
            oldest_jobs = sorted(
                self.completed_jobs.items(),
                key=lambda x: x[1].completed_at or datetime.min
            )
            for job_id, _ in oldest_jobs[:100]:  # Remove oldest 100
                del self.completed_jobs[job_id]
    
    def _delete_bucket_replica(self, job: ReplicationJob) -> bool:
        """Delete all objects from a bucket in a specific zone and optionally the bucket itself"""
        logger.info(f"Deleting bucket replica for {job.bucket_name} from {job.target_zone}")
        
        try:
            # 1. Get bucket mapping
            backend_mapping = self._get_bucket_mapping(job.customer_id, job.bucket_name)
            if not backend_mapping:
                logger.error(f"No bucket mapping found for {job.customer_id}:{job.bucket_name}")
                return False
            
            # 2. Get target backend configuration
            target_backend_config = self._get_backend_config_for_zone(job.target_zone)
            if not target_backend_config:
                logger.error(f"Backend configuration not found for zone {job.target_zone}")
                return False
            
            # 3. Get target bucket name
            target_bucket_name = backend_mapping.get(self._zone_to_backend_id(job.target_zone))
            if not target_bucket_name:
                logger.error(f"Backend bucket name not found for zone {job.target_zone}")
                return False
            
            # 4. Delete all objects from the bucket in this zone
            deleted_count = self._delete_all_objects_from_bucket(
                target_backend_config, target_bucket_name
            )
            
            if deleted_count < 0:
                logger.error(f"Failed to delete objects from bucket {target_bucket_name}")
                return False
            
            logger.info(f"Successfully deleted {deleted_count} objects from {target_bucket_name}")
            
            # 5. Optionally delete the empty bucket itself
            delete_bucket = job.metadata.get('delete_bucket', True)
            if delete_bucket:
                bucket_deleted = self._delete_backend_bucket(target_backend_config, target_bucket_name)
                if bucket_deleted:
                    logger.info(f"Successfully deleted backend bucket {target_bucket_name}")
                else:
                    logger.warning(f"Failed to delete backend bucket {target_bucket_name}, but objects were deleted")
            
            # 6. Update database - remove all object replicas for this zone
            if self.db_session_factory:
                try:
                    with self.db_session_factory() as db:
                        from sqlalchemy import text
                        
                        # Update all objects in this bucket to remove replicas from this zone
                        query = text("""
                            UPDATE object_metadata 
                            SET replicas = (
                                SELECT jsonb_agg(replica)
                                FROM jsonb_array_elements(replicas) AS replica
                                WHERE replica->>'provider_id' != :target_zone
                            ),
                            current_replica_count = GREATEST(current_replica_count - 1, 0),
                            updated_at = CURRENT_TIMESTAMP
                            WHERE customer_id = :customer_id 
                              AND bucket_name = :bucket_name
                        """)
                        
                        result = db.execute(query, {
                            'customer_id': job.customer_id,
                            'bucket_name': job.bucket_name,
                            'target_zone': job.target_zone
                        })
                        
                        affected_objects = result.rowcount
                        db.commit()
                        
                        logger.info(f"Updated database metadata for {affected_objects} objects")
                        return True
                        
                except Exception as e:
                    logger.error(f"Database update failed for bucket replica deletion: {e}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error during bucket replica deletion: {e}")
            return False
    
    def _cleanup_empty_bucket(self, job: ReplicationJob) -> bool:
        """Clean up empty backend bucket that no longer has any objects"""
        logger.info(f"Cleaning up empty bucket for {job.bucket_name} in {job.target_zone}")
        
        try:
            # 1. Get bucket mapping
            backend_mapping = self._get_bucket_mapping(job.customer_id, job.bucket_name)
            if not backend_mapping:
                logger.error(f"No bucket mapping found for {job.customer_id}:{job.bucket_name}")
                return False
            
            # 2. Get target backend configuration
            target_backend_config = self._get_backend_config_for_zone(job.target_zone)
            if not target_backend_config:
                logger.error(f"Backend configuration not found for zone {job.target_zone}")
                return False
            
            # 3. Get target bucket name
            target_bucket_name = backend_mapping.get(self._zone_to_backend_id(job.target_zone))
            if not target_bucket_name:
                logger.error(f"Backend bucket name not found for zone {job.target_zone}")
                return False
            
            # 4. Check if bucket is empty
            is_empty = self._is_bucket_empty(target_backend_config, target_bucket_name)
            if not is_empty:
                logger.info(f"Bucket {target_bucket_name} is not empty, skipping cleanup")
                return True
            
            # 5. Delete the empty bucket
            bucket_deleted = self._delete_backend_bucket(target_backend_config, target_bucket_name)
            if bucket_deleted:
                logger.info(f"Successfully cleaned up empty bucket {target_bucket_name}")
                
                # 6. Update bucket mapping status
                if self.db_session_factory:
                    try:
                        with self.db_session_factory() as db:
                            from sqlalchemy import text
                            
                            # Update backend bucket mapping to mark as deleted
                            query = text("""
                                UPDATE backend_bucket_names 
                                SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
                                WHERE customer_id = :customer_id 
                                  AND logical_name = :bucket_name
                                  AND backend_id = :backend_id
                            """)
                            
                            db.execute(query, {
                                'customer_id': job.customer_id,
                                'bucket_name': job.bucket_name,
                                'backend_id': self._zone_to_backend_id(job.target_zone)
                            })
                            db.commit()
                            
                    except Exception as e:
                        logger.error(f"Failed to update bucket mapping status: {e}")
                
                return True
            else:
                logger.error(f"Failed to delete empty bucket {target_bucket_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error during empty bucket cleanup: {e}")
            return False
    
    def _delete_all_objects_from_bucket(self, backend_config: Dict, bucket_name: str) -> int:
        """Delete all objects from a bucket, returns count of deleted objects or -1 on error"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            # Create S3 client
            s3_client = boto3.client('s3', **backend_config)
            
            deleted_count = 0
            continuation_token = None
            
            while True:
                # List objects in bucket
                list_params = {
                    'Bucket': bucket_name,
                    'MaxKeys': 1000
                }
                
                if continuation_token:
                    list_params['ContinuationToken'] = continuation_token
                
                try:
                    response = s3_client.list_objects_v2(**list_params)
                except ClientError as e:
                    if e.response['Error']['Code'] == 'NoSuchBucket':
                        logger.info(f"Bucket {bucket_name} doesn't exist, nothing to delete")
                        return 0
                    raise e
                
                # Get objects to delete
                objects = response.get('Contents', [])
                if not objects:
                    break
                
                # Prepare delete request
                delete_objects = [{'Key': obj['Key']} for obj in objects]
                
                # Delete objects in batch
                delete_response = s3_client.delete_objects(
                    Bucket=bucket_name,
                    Delete={
                        'Objects': delete_objects,
                        'Quiet': True
                    }
                )
                
                # Count successful deletions
                deleted_count += len(delete_objects)
                errors = delete_response.get('Errors', [])
                if errors:
                    for error in errors:
                        logger.warning(f"Failed to delete {error['Key']}: {error['Message']}")
                
                logger.info(f"Deleted batch of {len(delete_objects)} objects from {bucket_name}")
                
                # Check if there are more objects
                if not response.get('IsTruncated', False):
                    break
                
                continuation_token = response.get('NextContinuationToken')
            
            logger.info(f"Successfully deleted {deleted_count} objects from {bucket_name}")
            return deleted_count
            
        except ClientError as e:
            logger.error(f"S3 client error during bulk object deletion: {e}")
            return -1
        except Exception as e:
            logger.error(f"Unexpected error during bulk object deletion: {e}")
            return -1
    
    def _is_bucket_empty(self, backend_config: Dict, bucket_name: str) -> bool:
        """Check if a bucket is empty"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            # Create S3 client
            s3_client = boto3.client('s3', **backend_config)
            
            # List objects with max 1 to check if any exist
            try:
                response = s3_client.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
                return response.get('KeyCount', 0) == 0
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchBucket':
                    logger.info(f"Bucket {bucket_name} doesn't exist")
                    return True
                raise e
                
        except Exception as e:
            logger.error(f"Error checking if bucket is empty: {e}")
            return False
    
    def _delete_backend_bucket(self, backend_config: Dict, bucket_name: str) -> bool:
        """Delete an empty backend bucket"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            # Create S3 client
            s3_client = boto3.client('s3', **backend_config)
            
            # Delete bucket
            try:
                s3_client.delete_bucket(Bucket=bucket_name)
                logger.info(f"Successfully deleted bucket {bucket_name}")
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchBucket':
                    logger.info(f"Bucket {bucket_name} already deleted or doesn't exist")
                    return True
                elif e.response['Error']['Code'] == 'BucketNotEmpty':
                    logger.warning(f"Cannot delete bucket {bucket_name}: not empty")
                    return False
                else:
                    logger.error(f"Failed to delete bucket {bucket_name}: {e}")
                    return False
                    
        except Exception as e:
            logger.error(f"Unexpected error during bucket deletion: {e}")
            return False


class ReplicationManager:
    """High-level manager for replication operations"""
    
    def __init__(self, queue: ReplicationQueue):
        self.queue = queue
    
    def schedule_replica_addition(self, customer_id: str, bucket_name: str, object_key: str,
                                source_zone: str, target_zone: str, priority: int = 5) -> str:
        """Schedule adding a replica"""
        job = ReplicationJob(
            job_id=str(uuid.uuid4()),
            job_type=ReplicationJobType.ADD_REPLICA,
            customer_id=customer_id,
            bucket_name=bucket_name,
            object_key=object_key,
            source_zone=source_zone,
            target_zone=target_zone,
            priority=priority
        )
        return self.queue.add_job(job)
    
    def schedule_replica_removal(self, customer_id: str, bucket_name: str, object_key: str,
                               target_zone: str, priority: int = 7) -> str:
        """Schedule removing a replica"""
        job = ReplicationJob(
            job_id=str(uuid.uuid4()),
            job_type=ReplicationJobType.REMOVE_REPLICA,
            customer_id=customer_id,
            bucket_name=bucket_name,
            object_key=object_key,
            source_zone="",  # Not needed for removal
            target_zone=target_zone,
            priority=priority
        )
        return self.queue.add_job(job)
    
    def schedule_bucket_replica_deletion(self, customer_id: str, bucket_name: str, 
                                       target_zone: str, delete_bucket: bool = True, 
                                       priority: int = 6) -> str:
        """Schedule deletion of entire bucket replica from a zone"""
        job = ReplicationJob(
            job_id=str(uuid.uuid4()),
            job_type=ReplicationJobType.DELETE_BUCKET_REPLICA,
            customer_id=customer_id,
            bucket_name=bucket_name,
            object_key="",  # Not applicable for bucket operations
            source_zone="",
            target_zone=target_zone,
            priority=priority,
            metadata={"delete_bucket": delete_bucket}
        )
        return self.queue.add_job(job)
    
    def schedule_bucket_cleanup(self, customer_id: str, bucket_name: str, 
                              target_zone: str, priority: int = 8) -> str:
        """Schedule cleanup of empty bucket"""
        job = ReplicationJob(
            job_id=str(uuid.uuid4()),
            job_type=ReplicationJobType.CLEANUP_EMPTY_BUCKET,
            customer_id=customer_id,
            bucket_name=bucket_name,
            object_key="",
            source_zone="",
            target_zone=target_zone,
            priority=priority
        )
        return self.queue.add_job(job)
    
    def process_replica_count_change(self, customer_id: str, bucket_name: str, object_key: str,
                                   current_zones: List[str], target_zones: List[str]) -> List[str]:
        """Process replica count change based on zone lists"""
        job_ids = []
        
        # Determine what needs to be added or removed
        current_set = set(current_zones)
        target_set = set(target_zones)
        
        # Add new replicas
        zones_to_add = target_set - current_set
        for zone in zones_to_add:
            if current_zones:  # Use first current zone as source
                source_zone = current_zones[0]
            else:
                source_zone = target_zones[0]  # Use first target as source
            
            job_id = self.schedule_replica_addition(
                customer_id, bucket_name, object_key, source_zone, zone
            )
            job_ids.append(job_id)
        
        # Remove old replicas
        zones_to_remove = current_set - target_set
        for zone in zones_to_remove:
            job_id = self.schedule_replica_removal(
                customer_id, bucket_name, object_key, zone
            )
            job_ids.append(job_id)
        
        return job_ids
    
    def process_bucket_replica_count_change(self, customer_id: str, bucket_name: str,
                                          current_zones: List[str], target_zones: List[str],
                                          bulk_operations: bool = True) -> List[str]:
        """Process replica count change for entire bucket (all objects at once)"""
        job_ids = []
        
        # Determine what needs to be added or removed
        current_set = set(current_zones)
        target_set = set(target_zones)
        
        # Add new replicas - need to replicate all objects
        zones_to_add = target_set - current_set
        for zone in zones_to_add:
            if current_zones:
                source_zone = current_zones[0]
            else:
                source_zone = target_zones[0]
            
            if bulk_operations:
                # Schedule bucket-level replication job (would need implementation)
                logger.info(f"Would schedule bulk bucket replication to {zone}")
                # For now, fall back to object-level operations
                # This would require getting all objects and scheduling individual jobs
            else:
                # Individual object operations handled by caller
                logger.info(f"Individual object replication to {zone} handled separately")
        
        # Remove old replicas - delete entire bucket replica
        zones_to_remove = current_set - target_set
        for zone in zones_to_remove:
            if bulk_operations:
                # Schedule bucket deletion job
                job_id = self.schedule_bucket_replica_deletion(
                    customer_id, bucket_name, zone, delete_bucket=True, priority=6
                )
                job_ids.append(job_id)
                logger.info(f"Scheduled bucket replica deletion for zone {zone}")
            else:
                # Individual object deletions handled by caller
                logger.info(f"Individual object deletion from {zone} handled separately")
        
        return job_ids
    
    def get_object_count_in_bucket(self, customer_id: str, bucket_name: str) -> int:
        """Get count of objects in a bucket for deciding between bulk vs individual operations"""
        if not self.queue.db_session_factory:
            return 0
            
        try:
            with self.queue.db_session_factory() as db:
                from sqlalchemy import text
                
                query = text("""
                    SELECT COUNT(*) 
                    FROM object_metadata 
                    WHERE customer_id = :customer_id AND bucket_name = :bucket_name
                """)
                
                result = db.execute(query, {
                    'customer_id': customer_id,
                    'bucket_name': bucket_name
                }).fetchone()
                
                return result[0] if result else 0
                
        except Exception as e:
            logger.error(f"Failed to get object count: {e}")
            return 0


# Global replication queue instance
replication_queue = ReplicationQueue()
replication_manager = ReplicationManager(replication_queue)


if __name__ == "__main__":
    # Test the replication queue
    print("🔄 Testing Replication Queue System")
    print("==================================")
    
    # Start the queue
    replication_queue.start()
    
    try:
        # Add some test jobs
        jobs = []
        
        # Test replica addition
        job1 = ReplicationJob(
            job_id=str(uuid.uuid4()),
            job_type=ReplicationJobType.ADD_REPLICA,
            customer_id="test-customer",
            bucket_name="test-bucket",
            object_key="test-object.txt",
            source_zone="fi-hel-st-1",
            target_zone="de-fra-st-1",
            priority=3
        )
        jobs.append(replication_queue.add_job(job1))
        
        # Test replica removal
        job2 = ReplicationJob(
            job_id=str(uuid.uuid4()),
            job_type=ReplicationJobType.REMOVE_REPLICA,
            customer_id="test-customer",
            bucket_name="test-bucket",
            object_key="test-object.txt",
            source_zone="",
            target_zone="fr-par-st-1",
            priority=5
        )
        jobs.append(replication_queue.add_job(job2))
        
        print(f"Added {len(jobs)} test jobs")
        
        # Wait for jobs to complete
        time.sleep(3)
        
        # Check job statuses
        for job_id in jobs:
            status = replication_queue.get_job_status(job_id)
            print(f"Job {job_id}: {status['status']} ({status['job_type']})")
        
        # List active jobs
        active = replication_queue.list_active_jobs()
        print(f"Active jobs: {len(active)}")
        
    finally:
        # Stop the queue
        replication_queue.stop()
    
    print("✅ Replication queue test completed") 