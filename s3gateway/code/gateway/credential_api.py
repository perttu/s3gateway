#!/usr/bin/env python3
"""
S3 Credential Management API
Provides endpoints for creating, managing, and revoking S3 credentials.
"""

import json
import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from datetime import datetime

from s3_auth import S3CredentialManager, S3Credentials, S3AuthError

logger = logging.getLogger(__name__)


class CreateCredentialRequest(BaseModel):
    user_name: str
    user_email: Optional[EmailStr] = None
    permissions: Optional[Dict] = None


class CreateCredentialResponse(BaseModel):
    access_key_id: str
    secret_access_key: str
    user_id: str
    user_name: str
    permissions: Dict
    message: str


class CredentialInfo(BaseModel):
    access_key_id: str
    user_id: str
    user_name: str
    is_active: bool
    created_at: str
    last_used_at: Optional[str] = None


class CredentialListResponse(BaseModel):
    credentials: List[CredentialInfo]
    count: int


class UpdatePermissionsRequest(BaseModel):
    permissions: Dict


def create_credential_router(credential_manager: S3CredentialManager) -> APIRouter:
    """Create FastAPI router for credential management endpoints"""
    
    router = APIRouter(prefix="/api/credentials", tags=["credentials"])
    
    @router.post("/create", response_model=CreateCredentialResponse)
    async def create_credentials(request: CreateCredentialRequest):
        """Create new S3 credentials for a user"""
        try:
            credentials = credential_manager.create_credentials(
                user_name=request.user_name,
                user_email=request.user_email,
                permissions=request.permissions
            )
            
            return CreateCredentialResponse(
                access_key_id=credentials.access_key_id,
                secret_access_key=credentials.secret_access_key,
                user_id=credentials.user_id,
                user_name=credentials.user_name,
                permissions=credentials.permissions,
                message=f"Credentials created successfully for {request.user_name}"
            )
            
        except S3AuthError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error creating credentials: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.get("/list", response_model=CredentialListResponse)
    async def list_credentials(user_id: Optional[str] = None):
        """List S3 credentials (optionally filtered by user)"""
        try:
            credentials_list = credential_manager.list_user_credentials(user_id)
            
            credentials_info = []
            for cred in credentials_list:
                credentials_info.append(CredentialInfo(
                    access_key_id=cred['access_key_id'],
                    user_id=cred['user_id'],
                    user_name=cred['user_name'],
                    is_active=cred['is_active'],
                    created_at=cred['created_at'] or "",
                    last_used_at=None  # TODO: implement last used tracking
                ))
            
            return CredentialListResponse(
                credentials=credentials_info,
                count=len(credentials_info)
            )
            
        except Exception as e:
            logger.error(f"Error listing credentials: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.get("/{access_key_id}")
    async def get_credential_info(access_key_id: str):
        """Get information about specific credentials (without secret key)"""
        try:
            credentials = credential_manager.get_credentials_by_access_key(access_key_id)
            
            if not credentials:
                raise HTTPException(status_code=404, detail="Credentials not found")
            
            return {
                "access_key_id": credentials.access_key_id,
                "user_id": credentials.user_id,
                "user_name": credentials.user_name,
                "is_active": credentials.is_active,
                "permissions": credentials.permissions,
                "created_at": credentials.created_at.isoformat() if credentials.created_at else None
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting credential info: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.put("/{access_key_id}/permissions")
    async def update_permissions(access_key_id: str, request: UpdatePermissionsRequest):
        """Update permissions for specific credentials"""
        try:
            # Get existing credentials
            credentials = credential_manager.get_credentials_by_access_key(access_key_id)
            if not credentials:
                raise HTTPException(status_code=404, detail="Credentials not found")
            
            # Update permissions in database
            from sqlalchemy import text
            
            query = text("""
                UPDATE s3_credentials 
                SET permissions = :permissions, updated_at = CURRENT_TIMESTAMP
                WHERE access_key_id = :access_key_id
            """)
            
            result = credential_manager.db.execute(query, {
                'access_key_id': access_key_id,
                'permissions': json.dumps(request.permissions)
            })
            credential_manager.db.commit()
            
            if result.rowcount == 0:
                raise HTTPException(status_code=404, detail="Credentials not found")
            
            return {
                "message": f"Permissions updated for {access_key_id}",
                "access_key_id": access_key_id,
                "permissions": request.permissions
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating permissions: {e}")
            credential_manager.db.rollback()
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.delete("/{access_key_id}")
    async def deactivate_credentials(access_key_id: str):
        """Deactivate (soft delete) S3 credentials"""
        try:
            success = credential_manager.deactivate_credentials(access_key_id)
            
            if not success:
                raise HTTPException(status_code=404, detail="Credentials not found")
            
            return {
                "message": f"Credentials {access_key_id} deactivated successfully",
                "access_key_id": access_key_id,
                "status": "deactivated"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deactivating credentials: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.post("/generate-demo")
    async def generate_demo_credentials():
        """Generate demo credentials for testing (development only)"""
        try:
            # Create demo credentials with limited permissions
            demo_permissions = {
                "s3:GetObject": ["demo-*", "test-*"],
                "s3:PutObject": ["demo-*", "test-*"],
                "s3:DeleteObject": ["demo-*", "test-*"],
                "s3:ListBucket": ["demo-*", "test-*"],
                "s3:CreateBucket": ["demo-*", "test-*"],
                "s3:DeleteBucket": ["demo-*", "test-*"],
                "s3:GetBucketTagging": ["demo-*", "test-*"],
                "s3:PutBucketTagging": ["demo-*", "test-*"],
                "s3:DeleteBucketTagging": ["demo-*", "test-*"],
                "s3:GetObjectTagging": ["demo-*", "test-*"],
                "s3:PutObjectTagging": ["demo-*", "test-*"],
                "s3:DeleteObjectTagging": ["demo-*", "test-*"]
            }
            
            credentials = credential_manager.create_credentials(
                user_name="Demo User",
                user_email="demo@example.com",
                permissions=demo_permissions
            )
            
            return {
                "message": "Demo credentials created successfully",
                "access_key_id": credentials.access_key_id,
                "secret_access_key": credentials.secret_access_key,
                "user_id": credentials.user_id,
                "permissions": credentials.permissions,
                "warning": "These are demo credentials with limited permissions"
            }
            
        except Exception as e:
            logger.error(f"Error creating demo credentials: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    @router.get("/user/{user_id}/buckets")
    async def list_user_buckets(user_id: str):
        """List buckets owned by a specific user"""
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT bucket_name, created_at, zone_code, region
                FROM buckets 
                WHERE owner_user_id = :user_id
                ORDER BY created_at DESC
            """)
            
            result = credential_manager.db.execute(query, {'user_id': user_id})
            
            buckets = []
            for row in result:
                buckets.append({
                    'bucket_name': row[0],
                    'created_at': row[1].isoformat() if row[1] else None,
                    'zone_code': row[2],
                    'region': row[3]
                })
            
            return {
                "user_id": user_id,
                "buckets": buckets,
                "count": len(buckets)
            }
            
        except Exception as e:
            logger.error(f"Error listing user buckets: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")
    
    return router


class CredentialManagerService:
    """Service for managing S3 credentials across the application"""
    
    def __init__(self, db_session):
        self.credential_manager = S3CredentialManager(db_session)
        self.router = create_credential_router(self.credential_manager)
    
    def get_router(self) -> APIRouter:
        """Get the FastAPI router for credential endpoints"""
        return self.router
    
    def get_manager(self) -> S3CredentialManager:
        """Get the credential manager instance"""
        return self.credential_manager


if __name__ == "__main__":
    # Test the credential API
    print("🔑 Testing S3 Credential API")
    print("=============================")
    
    # This would normally be run within FastAPI
    print("✅ S3 credential API module loaded successfully")
    print("")
    print("Available endpoints:")
    print("  POST /api/credentials/create - Create new credentials")
    print("  GET  /api/credentials/list - List all credentials")
    print("  GET  /api/credentials/{access_key_id} - Get credential info")
    print("  PUT  /api/credentials/{access_key_id}/permissions - Update permissions")
    print("  DELETE /api/credentials/{access_key_id} - Deactivate credentials")
    print("  POST /api/credentials/generate-demo - Generate demo credentials")
    print("  GET  /api/credentials/user/{user_id}/buckets - List user buckets") 