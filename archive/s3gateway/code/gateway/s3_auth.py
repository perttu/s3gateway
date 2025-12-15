#!/usr/bin/env python3
"""
S3 Authentication and Authorization System
Implements AWS SigV4 signature validation and credential-based access control.
"""

import hashlib
import hmac
import logging
import secrets
import re
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from urllib.parse import quote, unquote, parse_qs
import base64

logger = logging.getLogger(__name__)


class S3AuthError(Exception):
    """S3 authentication and authorization errors"""
    pass


class S3Credentials:
    """S3 access credentials"""
    def __init__(self, access_key_id: str, secret_access_key: str, 
                 user_id: str, user_name: str, is_active: bool = True,
                 permissions: Dict = None, created_at: datetime = None):
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.user_id = user_id
        self.user_name = user_name
        self.is_active = is_active
        self.permissions = permissions or {}
        self.created_at = created_at or datetime.utcnow()


class S3CredentialManager:
    """Manages S3 credentials (access keys and secret keys)"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def generate_access_key_id(self) -> str:
        """Generate AWS-style access key ID (20 chars, starts with AKIA)"""
        # AWS access keys start with AKIA followed by 16 alphanumeric chars
        suffix = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(16))
        return f"AKIA{suffix}"
    
    def generate_secret_access_key(self) -> str:
        """Generate AWS-style secret access key (40 chars, base64-like)"""
        # AWS secret keys are 40 characters, base64-like
        chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        return ''.join(secrets.choice(chars) for _ in range(40))
    
    def create_credentials(self, user_name: str, user_email: str = None, 
                         permissions: Dict = None) -> S3Credentials:
        """Create new S3 credentials for a user"""
        try:
            from sqlalchemy import text
            
            # Generate credentials
            access_key_id = self.generate_access_key_id()
            secret_access_key = self.generate_secret_access_key()
            
            # Ensure access key is unique
            while self.get_credentials_by_access_key(access_key_id):
                access_key_id = self.generate_access_key_id()
            
            # Create user ID
            user_id = f"user-{secrets.token_hex(8)}"
            
            # Default permissions if none provided
            if permissions is None:
                permissions = {
                    "s3:GetObject": ["*"],
                    "s3:PutObject": ["*"],
                    "s3:DeleteObject": ["*"],
                    "s3:ListBucket": ["*"],
                    "s3:CreateBucket": ["*"],
                    "s3:DeleteBucket": ["*"],
                    "s3:GetBucketTagging": ["*"],
                    "s3:PutBucketTagging": ["*"],
                    "s3:DeleteBucketTagging": ["*"],
                    "s3:GetObjectTagging": ["*"],
                    "s3:PutObjectTagging": ["*"],
                    "s3:DeleteObjectTagging": ["*"]
                }
            
            # Store credentials in database
            query = text("""
                INSERT INTO s3_credentials 
                (access_key_id, secret_access_key, user_id, user_name, user_email, 
                 permissions, is_active, created_at)
                VALUES 
                (:access_key_id, :secret_access_key, :user_id, :user_name, :user_email,
                 :permissions, :is_active, CURRENT_TIMESTAMP)
            """)
            
            self.db.execute(query, {
                'access_key_id': access_key_id,
                'secret_access_key': secret_access_key,
                'user_id': user_id,
                'user_name': user_name,
                'user_email': user_email,
                'permissions': json.dumps(permissions),
                'is_active': True
            })
            self.db.commit()
            
            logger.info(f"Created S3 credentials for user {user_name} (ID: {user_id})")
            
            return S3Credentials(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                user_id=user_id,
                user_name=user_name,
                permissions=permissions
            )
            
        except Exception as e:
            logger.error(f"Failed to create credentials: {e}")
            self.db.rollback()
            raise S3AuthError(f"Failed to create credentials: {e}")
    
    def get_credentials_by_access_key(self, access_key_id: str) -> Optional[S3Credentials]:
        """Get credentials by access key ID"""
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT access_key_id, secret_access_key, user_id, user_name, 
                       permissions, is_active, created_at
                FROM s3_credentials 
                WHERE access_key_id = :access_key_id
            """)
            
            result = self.db.execute(query, {'access_key_id': access_key_id}).fetchone()
            
            if not result:
                return None
            
            return S3Credentials(
                access_key_id=result[0],
                secret_access_key=result[1],
                user_id=result[2],
                user_name=result[3],
                permissions=json.loads(result[4] or "{}"),
                is_active=result[5],
                created_at=result[6]
            )
            
        except Exception as e:
            logger.error(f"Failed to get credentials: {e}")
            return None
    
    def list_user_credentials(self, user_id: str = None) -> List[Dict]:
        """List credentials (optionally filtered by user)"""
        try:
            from sqlalchemy import text
            
            if user_id:
                query = text("""
                    SELECT access_key_id, user_id, user_name, is_active, created_at
                    FROM s3_credentials 
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                """)
                result = self.db.execute(query, {'user_id': user_id})
            else:
                query = text("""
                    SELECT access_key_id, user_id, user_name, is_active, created_at
                    FROM s3_credentials 
                    ORDER BY created_at DESC
                """)
                result = self.db.execute(query)
            
            credentials = []
            for row in result:
                credentials.append({
                    'access_key_id': row[0],
                    'user_id': row[1],
                    'user_name': row[2],
                    'is_active': row[3],
                    'created_at': row[4].isoformat() if row[4] else None
                })
            
            return credentials
            
        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            return []
    
    def deactivate_credentials(self, access_key_id: str) -> bool:
        """Deactivate credentials (soft delete)"""
        try:
            from sqlalchemy import text
            
            query = text("""
                UPDATE s3_credentials 
                SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE access_key_id = :access_key_id
            """)
            
            result = self.db.execute(query, {'access_key_id': access_key_id})
            self.db.commit()
            
            if result.rowcount > 0:
                logger.info(f"Deactivated credentials: {access_key_id}")
                return True
            else:
                logger.warning(f"Credentials not found: {access_key_id}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to deactivate credentials: {e}")
            self.db.rollback()
            return False


class S3SignatureValidator:
    """Validates AWS Signature Version 4 (SigV4) signatures"""
    
    def __init__(self, credential_manager: S3CredentialManager):
        self.credential_manager = credential_manager
    
    def validate_request(self, method: str, path: str, query_string: str, 
                        headers: Dict[str, str], body: bytes = b"") -> Tuple[bool, Optional[S3Credentials], str]:
        """
        Validate S3 request signature
        Returns: (is_valid, credentials, error_message)
        """
        try:
            # Check for Authorization header
            auth_header = headers.get('authorization') or headers.get('Authorization')
            if not auth_header:
                return False, None, "Missing Authorization header"
            
            # Parse Authorization header
            if not auth_header.startswith('AWS4-HMAC-SHA256'):
                return False, None, "Unsupported signature version"
            
            # Extract components from Authorization header
            # Format: AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20230101/us-east-1/s3/aws4_request, SignedHeaders=host;range;x-amz-date, Signature=fe5f80f77d5fa3beca038a248ff027d0445342fe2855ddc963176630326f1024
            auth_parts = self._parse_authorization_header(auth_header)
            if not auth_parts:
                return False, None, "Invalid Authorization header format"
            
            access_key_id = auth_parts['access_key_id']
            credential_scope = auth_parts['credential_scope']
            signed_headers = auth_parts['signed_headers']
            signature = auth_parts['signature']
            
            # Get credentials
            credentials = self.credential_manager.get_credentials_by_access_key(access_key_id)
            if not credentials:
                return False, None, "Invalid access key"
            
            if not credentials.is_active:
                return False, None, "Access key is inactive"
            
            # Get required headers
            x_amz_date = headers.get('x-amz-date') or headers.get('X-Amz-Date')
            if not x_amz_date:
                return False, None, "Missing X-Amz-Date header"
            
            # Validate timestamp (within 15 minutes)
            if not self._validate_timestamp(x_amz_date):
                return False, None, "Request timestamp too old or too far in future"
            
            # Calculate expected signature
            expected_signature = self._calculate_signature(
                method, path, query_string, headers, body,
                credentials.secret_access_key, x_amz_date, 
                credential_scope, signed_headers
            )
            
            # Compare signatures
            if signature == expected_signature:
                return True, credentials, ""
            else:
                logger.warning(f"Signature mismatch for {access_key_id}")
                logger.debug(f"Expected: {expected_signature}, Got: {signature}")
                return False, None, "Signature mismatch"
                
        except Exception as e:
            logger.error(f"Signature validation error: {e}")
            return False, None, f"Signature validation error: {e}"
    
    def _parse_authorization_header(self, auth_header: str) -> Optional[Dict[str, str]]:
        """Parse AWS4-HMAC-SHA256 Authorization header"""
        try:
            # Remove the AWS4-HMAC-SHA256 prefix
            auth_content = auth_header[len('AWS4-HMAC-SHA256 '):].strip()
            
            # Parse key=value pairs
            parts = {}
            for part in auth_content.split(', '):
                if '=' in part:
                    key, value = part.split('=', 1)
                    parts[key.strip()] = value.strip()
            
            # Extract credential components
            credential = parts.get('Credential', '')
            if '/' not in credential:
                return None
            
            credential_parts = credential.split('/')
            if len(credential_parts) < 5:
                return None
            
            access_key_id = credential_parts[0]
            credential_scope = '/'.join(credential_parts[1:])
            
            return {
                'access_key_id': access_key_id,
                'credential_scope': credential_scope,
                'signed_headers': parts.get('SignedHeaders', ''),
                'signature': parts.get('Signature', '')
            }
            
        except Exception as e:
            logger.error(f"Failed to parse authorization header: {e}")
            return None
    
    def _validate_timestamp(self, x_amz_date: str) -> bool:
        """Validate request timestamp is within acceptable range"""
        try:
            # Parse timestamp: 20230101T120000Z
            request_time = datetime.strptime(x_amz_date, '%Y%m%dT%H%M%SZ')
            current_time = datetime.utcnow()
            
            # Allow 15 minutes before and after
            time_diff = abs((current_time - request_time).total_seconds())
            return time_diff <= 900  # 15 minutes
            
        except Exception as e:
            logger.error(f"Failed to validate timestamp: {e}")
            return False
    
    def _calculate_signature(self, method: str, path: str, query_string: str,
                           headers: Dict[str, str], body: bytes,
                           secret_key: str, x_amz_date: str,
                           credential_scope: str, signed_headers: str) -> str:
        """Calculate AWS SigV4 signature"""
        try:
            # Step 1: Create canonical request
            canonical_request = self._create_canonical_request(
                method, path, query_string, headers, body, signed_headers
            )
            
            # Step 2: Create string to sign
            string_to_sign = self._create_string_to_sign(
                x_amz_date, credential_scope, canonical_request
            )
            
            # Step 3: Calculate signing key
            date_stamp = x_amz_date[:8]  # YYYYMMDD
            signing_key = self._get_signature_key(secret_key, date_stamp, 'us-east-1', 's3')
            
            # Step 4: Calculate signature
            signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
            
            return signature
            
        except Exception as e:
            logger.error(f"Failed to calculate signature: {e}")
            return ""
    
    def _create_canonical_request(self, method: str, path: str, query_string: str,
                                headers: Dict[str, str], body: bytes, signed_headers: str) -> str:
        """Create canonical request for signature calculation"""
        
        # Canonical URI
        canonical_uri = quote(path, safe='/~')
        
        # Canonical query string
        canonical_query_string = self._create_canonical_query_string(query_string)
        
        # Canonical headers
        canonical_headers = self._create_canonical_headers(headers, signed_headers)
        
        # Payload hash
        payload_hash = hashlib.sha256(body).hexdigest()
        
        # Combine all parts
        canonical_request = f"{method}\n{canonical_uri}\n{canonical_query_string}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
        
        return canonical_request
    
    def _create_canonical_query_string(self, query_string: str) -> str:
        """Create canonical query string"""
        if not query_string:
            return ""
        
        # Parse and sort query parameters
        params = []
        for param in query_string.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                params.append((quote(key, safe=''), quote(value, safe='')))
            else:
                params.append((quote(param, safe=''), ''))
        
        params.sort()
        return '&'.join(f"{key}={value}" for key, value in params)
    
    def _create_canonical_headers(self, headers: Dict[str, str], signed_headers: str) -> str:
        """Create canonical headers"""
        header_names = signed_headers.split(';')
        canonical_headers = []
        
        for header_name in header_names:
            header_value = None
            # Find header (case-insensitive)
            for key, value in headers.items():
                if key.lower() == header_name.lower():
                    header_value = value
                    break
            
            if header_value is not None:
                # Normalize header value
                normalized_value = ' '.join(header_value.split())
                canonical_headers.append(f"{header_name.lower()}:{normalized_value}")
        
        return '\n'.join(canonical_headers) + '\n'
    
    def _create_string_to_sign(self, x_amz_date: str, credential_scope: str, canonical_request: str) -> str:
        """Create string to sign"""
        algorithm = 'AWS4-HMAC-SHA256'
        request_hash = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        
        string_to_sign = f"{algorithm}\n{x_amz_date}\n{credential_scope}\n{request_hash}"
        return string_to_sign
    
    def _get_signature_key(self, secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
        """Derive signing key"""
        def sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()
        
        k_date = sign(f"AWS4{secret_key}".encode('utf-8'), date_stamp)
        k_region = sign(k_date, region)
        k_service = sign(k_region, service)
        k_signing = sign(k_service, "aws4_request")
        
        return k_signing


class S3AuthorizationManager:
    """Manages S3 resource permissions and access control"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def check_bucket_permission(self, credentials: S3Credentials, bucket_name: str, action: str) -> bool:
        """Check if user has permission to perform action on bucket"""
        try:
            # Check if user owns the bucket
            if self._is_bucket_owner(credentials.user_id, bucket_name):
                return True
            
            # Check explicit permissions
            user_permissions = credentials.permissions
            
            # Check specific action permission
            if action in user_permissions:
                allowed_resources = user_permissions[action]
                if '*' in allowed_resources or bucket_name in allowed_resources:
                    return True
            
            # Check wildcard permissions
            action_prefix = action.split(':')[0] + ':*'
            if action_prefix in user_permissions:
                allowed_resources = user_permissions[action_prefix]
                if '*' in allowed_resources or bucket_name in allowed_resources:
                    return True
            
            logger.warning(f"Permission denied: {credentials.user_id} -> {action} on {bucket_name}")
            return False
            
        except Exception as e:
            logger.error(f"Error checking bucket permission: {e}")
            return False
    
    def check_object_permission(self, credentials: S3Credentials, bucket_name: str, 
                              object_key: str, action: str) -> bool:
        """Check if user has permission to perform action on object"""
        try:
            # Check if user owns the bucket (bucket owners can access all objects)
            if self._is_bucket_owner(credentials.user_id, bucket_name):
                return True
            
            # Check explicit permissions
            user_permissions = credentials.permissions
            resource_path = f"{bucket_name}/{object_key}"
            
            # Check specific action permission
            if action in user_permissions:
                allowed_resources = user_permissions[action]
                if '*' in allowed_resources or bucket_name in allowed_resources or resource_path in allowed_resources:
                    return True
            
            # Check wildcard permissions
            action_prefix = action.split(':')[0] + ':*'
            if action_prefix in user_permissions:
                allowed_resources = user_permissions[action_prefix]
                if '*' in allowed_resources or bucket_name in allowed_resources or resource_path in allowed_resources:
                    return True
            
            logger.warning(f"Permission denied: {credentials.user_id} -> {action} on {bucket_name}/{object_key}")
            return False
            
        except Exception as e:
            logger.error(f"Error checking object permission: {e}")
            return False
    
    def _is_bucket_owner(self, user_id: str, bucket_name: str) -> bool:
        """Check if user owns the bucket"""
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT 1 FROM buckets 
                WHERE bucket_name = :bucket_name AND owner_user_id = :user_id
            """)
            
            result = self.db.execute(query, {
                'bucket_name': bucket_name,
                'user_id': user_id
            }).fetchone()
            
            return result is not None
            
        except Exception as e:
            logger.error(f"Error checking bucket ownership: {e}")
            return False
    
    def assign_bucket_ownership(self, user_id: str, bucket_name: str) -> bool:
        """Assign bucket ownership to user"""
        try:
            from sqlalchemy import text
            
            query = text("""
                UPDATE buckets 
                SET owner_user_id = :user_id, updated_at = CURRENT_TIMESTAMP
                WHERE bucket_name = :bucket_name
            """)
            
            result = self.db.execute(query, {
                'user_id': user_id,
                'bucket_name': bucket_name
            })
            self.db.commit()
            
            if result.rowcount > 0:
                logger.info(f"Assigned bucket {bucket_name} to user {user_id}")
                return True
            else:
                logger.warning(f"Bucket not found: {bucket_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error assigning bucket ownership: {e}")
            self.db.rollback()
            return False


class S3AuthMiddleware:
    """Authentication middleware for S3 requests"""
    
    def __init__(self, credential_manager: S3CredentialManager):
        self.credential_manager = credential_manager
        self.signature_validator = S3SignatureValidator(credential_manager)
        self.authorization_manager = S3AuthorizationManager(credential_manager.db)
    
    def authenticate_request(self, method: str, path: str, query_string: str,
                           headers: Dict[str, str], body: bytes = b"") -> Tuple[bool, Optional[S3Credentials], str]:
        """
        Authenticate S3 request
        Returns: (is_authenticated, credentials, error_message)
        """
        return self.signature_validator.validate_request(method, path, query_string, headers, body)
    
    def authorize_request(self, credentials: S3Credentials, method: str, path: str, 
                         query_string: str) -> Tuple[bool, str]:
        """
        Authorize S3 request
        Returns: (is_authorized, error_message)
        """
        try:
            # Parse S3 action from method and path
            action = self._determine_s3_action(method, path, query_string)
            bucket_name, object_key = self._parse_s3_path(path)
            
            if not bucket_name:
                return False, "Invalid S3 path"
            
            # Check authorization
            if object_key:
                # Object-level operation
                authorized = self.authorization_manager.check_object_permission(
                    credentials, bucket_name, object_key, action
                )
            else:
                # Bucket-level operation
                authorized = self.authorization_manager.check_bucket_permission(
                    credentials, bucket_name, action
                )
            
            if authorized:
                return True, ""
            else:
                return False, f"Access denied for action {action}"
                
        except Exception as e:
            logger.error(f"Authorization error: {e}")
            return False, f"Authorization error: {e}"
    
    def _determine_s3_action(self, method: str, path: str, query_string: str) -> str:
        """Determine S3 action from HTTP method and path"""
        _, object_key = self._parse_s3_path(path)
        
        # Check for specific query parameters that indicate special operations
        if 'tagging' in query_string:
            if method == 'GET':
                return 's3:GetObjectTagging' if object_key else 's3:GetBucketTagging'
            elif method == 'PUT':
                return 's3:PutObjectTagging' if object_key else 's3:PutBucketTagging'
            elif method == 'DELETE':
                return 's3:DeleteObjectTagging' if object_key else 's3:DeleteBucketTagging'
        
        # Standard operations
        if object_key:
            if method == 'GET':
                return 's3:GetObject'
            elif method == 'PUT':
                return 's3:PutObject'
            elif method == 'DELETE':
                return 's3:DeleteObject'
        else:
            if method == 'GET':
                return 's3:ListBucket'
            elif method == 'PUT':
                return 's3:CreateBucket'
            elif method == 'DELETE':
                return 's3:DeleteBucket'
        
        return 's3:Unknown'
    
    def _parse_s3_path(self, path: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse S3 path into bucket name and object key"""
        # Remove /s3/ prefix if present
        if path.startswith('/s3/'):
            path = path[4:]
        elif path.startswith('/s3'):
            path = path[3:]
        
        if path.startswith('/'):
            path = path[1:]
        
        if not path:
            return None, None
        
        parts = path.split('/', 1)
        bucket_name = parts[0]
        object_key = parts[1] if len(parts) > 1 else None
        
        return bucket_name, object_key


if __name__ == "__main__":
    # Test the S3 authentication system
    print("🔐 Testing S3 Authentication System")
    print("====================================")
    
    # Test credential generation
    manager = S3CredentialManager(None)
    
    access_key = manager.generate_access_key_id()
    secret_key = manager.generate_secret_access_key()
    
    print(f"Generated Access Key: {access_key}")
    print(f"Generated Secret Key: {secret_key}")
    print(f"Access Key format valid: {access_key.startswith('AKIA') and len(access_key) == 20}")
    print(f"Secret Key format valid: {len(secret_key) == 40}")
    
    # Test signature validation
    validator = S3SignatureValidator(manager)
    
    # Test authorization
    print("✅ S3 authentication test completed") 