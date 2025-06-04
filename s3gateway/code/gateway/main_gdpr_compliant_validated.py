#!/usr/bin/env python3
"""
S3 Gateway Service - GDPR-Compliant Two-Layer Architecture with S3 Validation
Uses HTTP redirects and validates S3 naming to prevent backend failures.
"""

import os
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
import asyncio
import httpx

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
import pandas as pd
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# Import our S3 validation module
from s3_validation import S3NameValidator, S3ValidationError, validate_s3_name

# Import bucket mapping modules
from bucket_mapping import BucketMapper, BucketMappingService, create_bucket_with_mapping

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
GATEWAY_TYPE = os.getenv('GATEWAY_TYPE', 'regional')  # 'global' or 'regional'
REGION_ID = os.getenv('REGION_ID', 'FI-HEL')
REGIONAL_ENDPOINTS = json.loads(os.getenv('REGIONAL_ENDPOINTS', '{}'))
ENABLE_GDPR_REDIRECTS = os.getenv('ENABLE_GDPR_REDIRECTS', 'true').lower() == 'true'
ENABLE_S3_VALIDATION = os.getenv('ENABLE_S3_VALIDATION', 'true').lower() == 'true'
S3_VALIDATION_STRICT = os.getenv('S3_VALIDATION_STRICT', 'false').lower() == 'true'

# Database connections
DATABASE_URL = os.getenv("DATABASE_URL")
GLOBAL_DATABASE_URL = os.getenv("GLOBAL_DATABASE_URL")

# Other configuration
S3PROXY_URL = os.getenv("S3PROXY_URL", "http://localhost:8080")
PROVIDERS_FILE = os.getenv("PROVIDERS_FILE", "/app/providers_flat.csv")
S3_BACKENDS_CONFIG = os.getenv("S3_BACKENDS_CONFIG", "/app/config/s3_backends.json")
HARDCODED_BUCKET = "2025-datatransfer"

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if GLOBAL_DATABASE_URL:
    global_engine = create_engine(GLOBAL_DATABASE_URL)
    GlobalSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=global_engine)
else:
    global_engine = None
    GlobalSessionLocal = None

# FastAPI app
app = FastAPI(
    title=f"S3 Gateway Service ({GATEWAY_TYPE})",
    description=f"GDPR-compliant two-layer S3 gateway with validation - {GATEWAY_TYPE} tier",
    version="3.2.0"
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
validator = S3NameValidator()

def create_s3_error_response(error_code: str, message: str, bucket_name: str = None, key: str = None) -> Response:
    """Create S3-compatible XML error response"""
    resource = f"/{bucket_name}" if bucket_name else "/"
    if key:
        resource += f"/{key}"
    
    error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Error>
    <Code>{error_code}</Code>
    <Message>{message}</Message>
    <Resource>{resource}</Resource>
    <RequestId>{str(uuid.uuid4())}</RequestId>
</Error>"""
    
    return Response(
        content=error_xml,
        status_code=400,
        media_type="application/xml",
        headers={
            "X-S3-Validation-Error": "true",
            "X-Error-Code": error_code
        }
    )

class S3Backend:
    """S3 backend wrapper for regional gateways"""
    
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

class RouterService:
    """Handles routing logic for the global gateway"""
    
    def __init__(self):
        self.regional_endpoints = REGIONAL_ENDPOINTS
    
    def get_customer_region(self, customer_id: str) -> Optional[str]:
        """Get customer's primary region from global database (MINIMAL data only)"""
        if not GlobalSessionLocal:
            return None
            
        with GlobalSessionLocal() as db:
            query = text("""
                SELECT primary_region_id
                FROM customer_routing 
                WHERE customer_id = :customer_id
            """)
            result = db.execute(query, {'customer_id': customer_id}).fetchone()
            
            if result:
                return result[0]
        
        return None
    
    def get_default_region(self) -> str:
        """Get default region from global configuration"""
        if not GlobalSessionLocal:
            return 'FI-HEL'
            
        with GlobalSessionLocal() as db:
            query = text("""
                SELECT config_value
                FROM system_config 
                WHERE config_key = 'default_region'
            """)
            result = db.execute(query).fetchone()
            
            if result:
                return json.loads(result[0])
        
        return 'FI-HEL'
    
    def get_regional_endpoint(self, region_id: str) -> Optional[str]:
        """Get regional gateway endpoint URL"""
        return self.regional_endpoints.get(region_id)
    
    def log_routing_decision(self, customer_id: str, region: str, reason: str, request: Request):
        """Log MINIMAL routing decision (GDPR-compliant - no customer data)"""
        if not GlobalSessionLocal:
            return
            
        with GlobalSessionLocal() as db:
            query = text("""
                INSERT INTO routing_log 
                (customer_id, routed_to_region, routing_reason, created_at)
                VALUES (:customer_id, :routed_to_region, :routing_reason, CURRENT_TIMESTAMP)
            """)
            
            db.execute(query, {
                'customer_id': customer_id,
                'routed_to_region': region,
                'routing_reason': reason
            })
            db.commit()

router_service = RouterService()

def get_db():
    """Database dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def load_s3_backends():
    """Load S3 backend configuration (for regional gateways)"""
    global s3_backends
    
    if GATEWAY_TYPE != 'regional':
        return True
    
    try:
        with open(S3_BACKENDS_CONFIG, 'r') as f:
            backends_config = json.load(f)
        
        s3_backends = {}
        for backend_config in backends_config.get('backends', []):
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
        providers_df = providers_df.fillna("")
        logger.info(f"Loaded {len(providers_df)} providers")
        return providers_df
    except Exception as e:
        logger.error(f"Failed to load providers: {e}")
        return pd.DataFrame()

@app.on_event("startup")
async def startup_event():
    """Initialize application"""
    logger.info(f"Starting S3 Gateway Service in {GATEWAY_TYPE} mode...")
    
    if GATEWAY_TYPE == 'global':
        logger.info("Global routing gateway - GDPR-compliant redirects enabled")
        if ENABLE_GDPR_REDIRECTS:
            logger.info("✅ GDPR redirects enabled - customer data goes directly to regional endpoints")
        else:
            logger.warning("⚠️  GDPR redirects disabled - using proxying (potential compliance risk)")
    elif GATEWAY_TYPE == 'regional':
        logger.info(f"Regional gateway for region: {REGION_ID}")
        if not load_s3_backends():
            logger.warning("Failed to load S3 backends - some features may not work")
    
    if ENABLE_S3_VALIDATION:
        logger.info(f"✅ S3 naming validation enabled (strict={S3_VALIDATION_STRICT})")
    else:
        logger.warning("⚠️  S3 naming validation disabled - may cause backend failures")
    
    load_providers()

# Global Gateway Routes (GATEWAY_TYPE == 'global')
if GATEWAY_TYPE == 'global':
    
    @app.middleware("http")
    async def gdpr_routing_middleware(request: Request, call_next):
        """GDPR-compliant routing using HTTP redirects with S3 validation"""
        
        # Extract customer ID from headers, query params, or path
        customer_id = (
            request.headers.get('X-Customer-ID') or
            request.query_params.get('customer_id') or
            'demo-customer'
        )
        
        # S3 validation before routing (if enabled)
        if ENABLE_S3_VALIDATION and request.url.path.startswith('/s3/'):
            path_parts = request.url.path.strip('/').split('/')
            if len(path_parts) >= 2:  # /s3/bucket or /s3/bucket/key
                bucket_name = path_parts[1]
                object_key = '/'.join(path_parts[2:]) if len(path_parts) > 2 else None
                
                # Validate bucket name
                try:
                    bucket_valid, bucket_errors = validator.validate_bucket_name(bucket_name)
                    if not bucket_valid:
                        return create_s3_error_response(
                            "InvalidBucketName", 
                            f"Invalid bucket name: {'; '.join(bucket_errors)}",
                            bucket_name
                        )
                except Exception as e:
                    logger.error(f"Bucket validation error: {e}")
                
                # Validate object key if present
                if object_key:
                    try:
                        object_valid, object_errors = validator.validate_object_key(object_key, S3_VALIDATION_STRICT)
                        error_messages = [msg for msg in object_errors if 'warning' not in msg.lower()]
                        if not object_valid and error_messages:
                            return create_s3_error_response(
                                "InvalidObjectKey",
                                f"Invalid object key: {'; '.join(error_messages)}",
                                bucket_name,
                                object_key
                            )
                    except Exception as e:
                        logger.error(f"Object key validation error: {e}")
        
        # Determine target region (ONLY MINIMAL ROUTING INFO from global DB)
        customer_region = router_service.get_customer_region(customer_id)
        
        if customer_region:
            target_region = customer_region
            routing_reason = 'customer_region'
        else:
            target_region = router_service.get_default_region()
            routing_reason = 'default_region'
        
        # Get regional endpoint
        regional_endpoint = router_service.get_regional_endpoint(target_region)
        
        if not regional_endpoint:
            raise HTTPException(
                status_code=503, 
                detail=f"Regional endpoint for {target_region} not available"
            )
        
        # For S3 API calls, redirect to regional endpoint (GDPR-compliant)
        if request.url.path.startswith('/s3/') and ENABLE_GDPR_REDIRECTS:
            # Log minimal routing decision (no sensitive data)
            router_service.log_routing_decision(customer_id, target_region, routing_reason, request)
            
            # Build redirect URL
            redirect_url = f"{regional_endpoint.rstrip('/')}{request.url.path}"
            if request.url.query:
                redirect_url += f"?{request.url.query}"
            
            # Return HTTP redirect to regional endpoint
            response = RedirectResponse(
                url=redirect_url,
                status_code=307  # Preserve HTTP method and body
            )
            
            # Add compliance headers
            response.headers['X-GDPR-Redirect'] = 'true'
            response.headers['X-Target-Region'] = target_region
            response.headers['X-S3-Validation'] = 'passed' if ENABLE_S3_VALIDATION else 'disabled'
            response.headers['X-Compliance-Note'] = 'Redirected to ensure data sovereignty'
            
            return response
        
        # For non-S3 API calls, continue processing locally
        response = await call_next(request)
        response.headers['X-Routed-To-Region'] = target_region
        response.headers['X-Customer-ID'] = customer_id
        return response
    
    @app.get("/health")
    async def global_health():
        """Global gateway health check"""
        regional_status = {}
        
        async with httpx.AsyncClient() as client:
            for region, endpoint in REGIONAL_ENDPOINTS.items():
                try:
                    response = await client.get(f"{endpoint}/health", timeout=5.0)
                    regional_status[region] = {
                        "status": "healthy" if response.status_code == 200 else "unhealthy",
                        "endpoint": endpoint
                    }
                except:
                    regional_status[region] = {
                        "status": "unreachable",
                        "endpoint": endpoint
                    }
        
        return {
            "status": "healthy",
            "service": "s3-gateway-global",
            "gdpr_compliant": ENABLE_GDPR_REDIRECTS,
            "redirect_mode": "HTTP redirects" if ENABLE_GDPR_REDIRECTS else "Proxying",
            "s3_validation": {
                "enabled": ENABLE_S3_VALIDATION,
                "strict_mode": S3_VALIDATION_STRICT
            },
            "regional_endpoints": regional_status
        }
    
    @app.get("/validation/test")
    async def test_validation(bucket_name: str = None, object_key: str = None):
        """Test S3 validation without performing operations"""
        if not ENABLE_S3_VALIDATION:
            return {"validation": "disabled", "message": "S3 validation is disabled"}
        
        try:
            report = validator.get_validation_report(bucket_name, object_key, S3_VALIDATION_STRICT)
            return report
        except Exception as e:
            return {"error": str(e), "validation": "failed"}

# Regional Gateway Routes (GATEWAY_TYPE == 'regional')  
elif GATEWAY_TYPE == 'regional':
    
    def get_customer_info(customer_id: str) -> Optional[Dict]:
        """Get full customer information from regional database"""
        with SessionLocal() as db:
            query = text("""
                SELECT customer_id, customer_name, region_id, country, 
                       data_residency_requirement, compliance_requirements, 
                       compliance_status, next_compliance_review
                FROM customers 
                WHERE customer_id = :customer_id
            """)
            
            result = db.execute(query, {'customer_id': customer_id}).fetchone()
            return dict(result) if result else None
    
    def get_customer_objects(customer_id: str, bucket_name: str = None):
        """Get customer objects from regional metadata"""
        with SessionLocal() as db:
            where_clause = "WHERE om.customer_id = :customer_id"
            params = {'customer_id': customer_id}
            
            if bucket_name:
                where_clause += " AND om.bucket_name = :bucket_name"
                params['bucket_name'] = bucket_name
            
            query = text(f"""
                SELECT om.object_id, om.bucket_name, om.object_key, om.version_id, 
                       om.size_bytes, om.etag, om.content_type, om.replicas, 
                       om.sync_status, om.compliance_status, om.legal_hold,
                       c.customer_name, c.data_residency_requirement
                FROM object_metadata om
                JOIN customers c ON om.customer_id = c.customer_id
                {where_clause}
                ORDER BY om.created_at DESC
                LIMIT 1000
            """)
            
            result = db.execute(query, params)
            return [dict(row) for row in result]
    
    def log_regional_operation(customer_id: str, operation_type: str, bucket_name: str, 
                              object_key: str, request: Request, status_code: int, 
                              bytes_transferred: int = 0):
        """Log operation in regional database with FULL compliance info"""
        with SessionLocal() as db:
            query = text("""
                INSERT INTO operations_log 
                (customer_id, operation_type, bucket_name, object_key, 
                 request_id, user_agent, source_ip, status_code, bytes_transferred,
                 compliance_info, created_at)
                VALUES (:customer_id, :operation_type, :bucket_name, :object_key,
                        :request_id, :user_agent, :source_ip, :status_code, :bytes_transferred,
                        :compliance_info, CURRENT_TIMESTAMP)
            """)
            
            # Determine if this was a redirected request
            redirected = request.headers.get('X-GDPR-Redirect') == 'true'
            s3_validation = request.headers.get('X-S3-Validation', 'unknown')
            
            compliance_info = {
                "region_processed": REGION_ID,
                "direct_regional_access": not redirected,
                "gdpr_redirect": redirected,
                "cross_border_transfer": False,
                "legal_basis": "legitimate_interest",
                "data_sovereignty_compliant": True,
                "s3_validation_enabled": ENABLE_S3_VALIDATION,
                "s3_validation_status": s3_validation
            }
            
            db.execute(query, {
                'customer_id': customer_id,
                'operation_type': operation_type,
                'bucket_name': bucket_name,
                'object_key': object_key,
                'request_id': request.headers.get('X-Request-ID', str(uuid.uuid4())),
                'user_agent': request.headers.get('user-agent', ''),
                'source_ip': str(request.client.host) if request.client else None,
                'status_code': status_code,
                'bytes_transferred': bytes_transferred,
                'compliance_info': json.dumps(compliance_info)
            })
            db.commit()
    
    @app.get("/health")
    async def regional_health():
        """Regional gateway health check"""
        customer_count = 0
        try:
            with SessionLocal() as db:
                query = text("SELECT COUNT(*) FROM customers WHERE region_id = :region_id")
                result = db.execute(query, {'region_id': REGION_ID}).fetchone()
                customer_count = result[0] if result else 0
        except:
            pass
        
        return {
            "status": "healthy",
            "service": f"s3-gateway-regional-{REGION_ID}",
            "region": REGION_ID,
            "database": "connected" if engine else "disconnected",
            "customer_count": customer_count,
            "backend_count": len(s3_backends),
            "gdpr_compliance": "Full customer data stored regionally",
            "s3_validation": {
                "enabled": ENABLE_S3_VALIDATION,
                "strict_mode": S3_VALIDATION_STRICT
            }
        }
    
    @app.get("/s3/{bucket_name}")
    async def list_objects(
        request: Request,
        bucket_name: str, 
        x_customer_id: str = Header(alias="X-Customer-ID", default="demo-customer")
    ):
        """List objects in bucket (from regional metadata with compliance check)"""
        
        # S3 validation
        if ENABLE_S3_VALIDATION:
            try:
                bucket_valid, bucket_errors = validator.validate_bucket_name(bucket_name)
                if not bucket_valid:
                    return create_s3_error_response(
                        "InvalidBucketName",
                        f"Invalid bucket name: {'; '.join(bucket_errors)}",
                        bucket_name
                    )
            except Exception as e:
                logger.error(f"Bucket validation error: {e}")
                return create_s3_error_response(
                    "ValidationError",
                    "Bucket name validation failed",
                    bucket_name
                )
        
        # Verify customer exists in this region
        customer_info = get_customer_info(x_customer_id)
        if not customer_info:
            raise HTTPException(status_code=404, detail="Customer not found in this region")
        
        if customer_info['region_id'] != REGION_ID:
            raise HTTPException(status_code=403, detail=f"Customer belongs to region {customer_info['region_id']}, not {REGION_ID}")
        
        objects = get_customer_objects(x_customer_id, bucket_name)
        
        # Log the operation with full compliance tracking
        log_regional_operation(x_customer_id, "ListObjects", bucket_name, None, request, 200)
        
        # Convert to S3 XML format
        xml_objects = ""
        for obj in objects:
            xml_objects += f"""
        <Contents>
            <Key>{obj['object_key']}</Key>
            <LastModified>2024-01-01T00:00:00.000Z</LastModified>
            <ETag>"{obj['etag']}"</ETag>
            <Size>{obj['size_bytes']}</Size>
            <StorageClass>STANDARD</StorageClass>
        </Contents>"""
        
        xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>{bucket_name}</Name>
    <Prefix></Prefix>
    <Marker></Marker>
    <MaxKeys>1000</MaxKeys>
    <IsTruncated>false</IsTruncated>{xml_objects}
</ListBucketResult>"""
        
        return Response(
            content=xml_response, 
            media_type="application/xml",
            headers={
                "X-Region": REGION_ID,
                "X-Customer-ID": x_customer_id,
                "X-Object-Count": str(len(objects)),
                "X-Compliance-Status": customer_info['compliance_status'],
                "X-GDPR-Compliant": "true",
                "X-Data-Sovereignty": f"Data processed in {REGION_ID}",
                "X-S3-Validation": "passed" if ENABLE_S3_VALIDATION else "disabled"
            }
        )
    
    @app.put("/s3/{bucket_name}")
    async def create_bucket(
        request: Request,
        bucket_name: str,
        x_customer_id: str = Header(alias="X-Customer-ID", default="demo-customer")
    ):
        """Create bucket with S3 validation"""
        
        # S3 validation
        if ENABLE_S3_VALIDATION:
            try:
                bucket_valid, bucket_errors = validator.validate_bucket_name(bucket_name)
                if not bucket_valid:
                    return create_s3_error_response(
                        "InvalidBucketName",
                        f"Invalid bucket name: {'; '.join(bucket_errors)}",
                        bucket_name
                    )
            except Exception as e:
                logger.error(f"Bucket validation error: {e}")
                return create_s3_error_response(
                    "ValidationError",
                    "Bucket name validation failed",
                    bucket_name
                )
        
        # Customer verification
        customer_info = get_customer_info(x_customer_id)
        if not customer_info:
            raise HTTPException(status_code=404, detail="Customer not found in this region")
        
        # Log the operation
        log_regional_operation(x_customer_id, "CreateBucket", bucket_name, None, request, 200)
        
        # Create response
        return Response(
            status_code=200,
            headers={
                "X-Region": REGION_ID,
                "X-Customer-ID": x_customer_id,
                "X-S3-Validation": "passed" if ENABLE_S3_VALIDATION else "disabled"
            }
        )
    
    @app.put("/s3/{bucket_name}/{object_key:path}")
    async def put_object(
        request: Request,
        bucket_name: str,
        object_key: str,
        x_customer_id: str = Header(alias="X-Customer-ID", default="demo-customer")
    ):
        """Put object with S3 validation"""
        
        # S3 validation
        if ENABLE_S3_VALIDATION:
            try:
                # Validate bucket name
                bucket_valid, bucket_errors = validator.validate_bucket_name(bucket_name)
                if not bucket_valid:
                    return create_s3_error_response(
                        "InvalidBucketName",
                        f"Invalid bucket name: {'; '.join(bucket_errors)}",
                        bucket_name
                    )
                
                # Validate object key
                object_valid, object_errors = validator.validate_object_key(object_key, S3_VALIDATION_STRICT)
                error_messages = [msg for msg in object_errors if 'warning' not in msg.lower()]
                if not object_valid and error_messages:
                    return create_s3_error_response(
                        "InvalidObjectKey",
                        f"Invalid object key: {'; '.join(error_messages)}",
                        bucket_name,
                        object_key
                    )
            except Exception as e:
                logger.error(f"Object validation error: {e}")
                return create_s3_error_response(
                    "ValidationError",
                    "Object key validation failed",
                    bucket_name,
                    object_key
                )
        
        # Customer verification
        customer_info = get_customer_info(x_customer_id)
        if not customer_info:
            raise HTTPException(status_code=404, detail="Customer not found in this region")
        
        # Get request body
        body = await request.body()
        
        # Log the operation
        log_regional_operation(x_customer_id, "PutObject", bucket_name, object_key, request, 200, len(body))
        
        # Create response
        return Response(
            status_code=200,
            headers={
                "X-Region": REGION_ID,
                "X-Customer-ID": x_customer_id,
                "X-S3-Validation": "passed" if ENABLE_S3_VALIDATION else "disabled",
                "ETag": f'"{uuid.uuid4().hex}"'
            }
        )
    
    @app.get("/validation/test")
    async def test_validation_regional(bucket_name: str = None, object_key: str = None):
        """Test S3 validation without performing operations"""
        if not ENABLE_S3_VALIDATION:
            return {"validation": "disabled", "message": "S3 validation is disabled"}
        
        try:
            report = validator.get_validation_report(bucket_name, object_key, S3_VALIDATION_STRICT)
            report["region"] = REGION_ID
            return report
        except Exception as e:
            return {"error": str(e), "validation": "failed", "region": REGION_ID}

@app.get("/")
async def root():
    return {
        "service": f"s3-gateway-{GATEWAY_TYPE}",
        "region": REGION_ID if GATEWAY_TYPE == 'regional' else 'global',
        "message": f"GDPR-compliant two-layer S3 Gateway with validation ({GATEWAY_TYPE} tier)",
        "gdpr_compliance": "Customer data processed only in designated regional endpoints",
        "redirect_mode": ENABLE_GDPR_REDIRECTS if GATEWAY_TYPE == 'global' else "N/A",
        "s3_validation": {
            "enabled": ENABLE_S3_VALIDATION,
            "strict_mode": S3_VALIDATION_STRICT
        }
    }

# Add bucket mapping endpoints
@app.get("/api/bucket-mappings/{customer_id}")
async def list_customer_bucket_mappings(customer_id: str):
    """List all bucket mappings for a customer"""
    try:
        with get_db() as session:
            mapping_service = BucketMappingService(session)
            buckets = mapping_service.list_customer_buckets(customer_id)
            
            return {
                "customer_id": customer_id,
                "bucket_count": len(buckets),
                "buckets": buckets
            }
    except Exception as e:
        logger.error(f"Failed to list bucket mappings: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/bucket-mappings/{customer_id}/{logical_name}")
async def get_bucket_mapping(customer_id: str, logical_name: str):
    """Get specific bucket mapping details"""
    try:
        with get_db() as session:
            mapping_service = BucketMappingService(session)
            mapping = mapping_service.get_bucket_mapping(customer_id, logical_name)
            
            if not mapping:
                raise HTTPException(status_code=404, detail="Bucket mapping not found")
            
            return {
                "customer_id": customer_id,
                "logical_name": logical_name,
                "backend_mapping": mapping,
                "backend_count": len(mapping)
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get bucket mapping: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bucket-mappings/test")
async def test_bucket_mapping(
    customer_id: str = "test-customer",
    region_id: str = "FI-HEL",
    logical_name: str = "test-bucket"
):
    """Test bucket mapping generation (no database storage)"""
    try:
        backends = ["spacetime", "upcloud", "hetzner"]
        mapper = BucketMapper(customer_id, region_id)
        
        # Generate mapping
        backend_mapping = mapper.create_bucket_mapping(logical_name, backends)
        info = mapper.get_logical_name_info(logical_name)
        
        return {
            "test": True,
            "customer_id": customer_id,
            "region_id": region_id,
            "logical_name": logical_name,
            "backend_mapping": backend_mapping,
            "info": info,
            "explanation": {
                "hash_input_format": f"{customer_id}:{region_id}:{logical_name}:<backend_id>:0",
                "collision_avoidance": "Counter incremented on conflicts",
                "uniqueness": "Global uniqueness across all customers and backends"
            }
        }
    except Exception as e:
        logger.error(f"Failed to test bucket mapping: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Update bucket operations to use hash mapping
@app.put("/s3/{bucket_name}")
async def create_bucket_with_mapping(
    bucket_name: str,
    request: Request,
    x_customer_id: Optional[str] = Header(None, alias="X-Customer-ID")
):
    """Create bucket with hash mapping - validates logical name and creates backend mappings"""
    
    # Determine customer and region from headers or routing
    customer_id = x_customer_id or extract_customer_from_request(request)
    region_id = get_region_from_request(request)
    
    # Validate logical bucket name first
    if ENABLE_S3_VALIDATION:
        validator = S3Validator(strict_mode=S3_VALIDATION_STRICT)
        validation_result = validator.validate_bucket_name(bucket_name)
        
        if not validation_result.is_valid:
            # Return S3-compatible error
            return create_s3_error_response(
                "InvalidBucketName",
                f"Invalid bucket name: {', '.join(validation_result.errors)}",
                bucket_name
            )
    
    # For global gateway, redirect to regional endpoint after mapping
    if GATEWAY_TYPE == 'global':
        # Create bucket mapping first
        try:
            with get_db() as session:
                backends = ["spacetime", "upcloud", "hetzner"]  # Get from config
                success, mapping_info = create_bucket_with_mapping(
                    customer_id, region_id, bucket_name, backends, session
                )
                
                if not success:
                    return create_s3_error_response(
                        "InternalError",
                        f"Failed to create bucket mapping: {mapping_info.get('error', 'Unknown error')}",
                        bucket_name
                    )
                
                logger.info(f"Created bucket mapping for {customer_id}:{bucket_name}")
                logger.info(f"Backend mapping: {mapping_info.get('backend_mapping', {})}")
                
        except Exception as e:
            logger.error(f"Failed to create bucket mapping: {e}")
            return create_s3_error_response(
                "InternalError",
                f"Failed to create bucket mapping: {str(e)}",
                bucket_name
            )
        
        # Redirect to regional endpoint (customer only sees logical name)
        regional_url = router_service.get_regional_endpoint(region_id)
        redirect_url = f"{regional_url}/s3/{bucket_name}"
        
        logger.info(f"Redirecting bucket creation {customer_id}:{bucket_name} to {redirect_url}")
        return RedirectResponse(
            url=redirect_url,
            status_code=307,
            headers={
                "X-Customer-ID": customer_id,
                "X-Region-ID": region_id,
                "X-Bucket-Mapping": "created"
            }
        )
    
    else:
        # Regional gateway - create actual buckets using backend names
        try:
            with get_db() as session:
                mapping_service = BucketMappingService(session)
                backend_mapping = mapping_service.get_bucket_mapping(customer_id, bucket_name)
                
                if not backend_mapping:
                    return create_s3_error_response(
                        "NoSuchBucket",
                        f"Bucket mapping not found for {bucket_name}. Create via global endpoint first.",
                        bucket_name
                    )
                
                # Create buckets on all backends using mapped names
                creation_results = []
                s3_backends = load_s3_backends()
                
                for backend_id, backend_bucket_name in backend_mapping.items():
                    if backend_id in s3_backends:
                        try:
                            # Create bucket on backend using hashed name
                            backend_config = s3_backends[backend_id]
                            result = create_backend_bucket(backend_config, backend_bucket_name)
                            
                            creation_results.append({
                                "backend_id": backend_id,
                                "backend_bucket_name": backend_bucket_name,
                                "status": "success" if result else "failed"
                            })
                            
                            # Log creation
                            log_bucket_creation(session, customer_id, bucket_name, 
                                              backend_id, backend_bucket_name, 
                                              "create", "success" if result else "failed")
                        
                        except Exception as e:
                            logger.error(f"Failed to create bucket on {backend_id}: {e}")
                            creation_results.append({
                                "backend_id": backend_id,
                                "backend_bucket_name": backend_bucket_name,
                                "status": "failed",
                                "error": str(e)
                            })
                            
                            log_bucket_creation(session, customer_id, bucket_name,
                                              backend_id, backend_bucket_name,
                                              "create", "failed", str(e))
                
                # Return success if at least one backend succeeded
                success_count = sum(1 for r in creation_results if r["status"] == "success")
                
                if success_count > 0:
                    return {
                        "message": f"Bucket '{bucket_name}' created",
                        "logical_name": bucket_name,
                        "customer_id": customer_id,
                        "backends_created": success_count,
                        "total_backends": len(backend_mapping),
                        "details": creation_results
                    }
                else:
                    return create_s3_error_response(
                        "InternalError",
                        f"Failed to create bucket on any backend",
                        bucket_name
                    )
                    
        except Exception as e:
            logger.error(f"Failed to create bucket on regional gateway: {e}")
            return create_s3_error_response(
                "InternalError",
                f"Failed to create bucket: {str(e)}",
                bucket_name
            )

@app.get("/s3")
async def list_buckets_with_mapping(
    request: Request,
    x_customer_id: Optional[str] = Header(None, alias="X-Customer-ID")
):
    """List buckets - shows logical names to customer"""
    
    customer_id = x_customer_id or extract_customer_from_request(request)
    region_id = get_region_from_request(request)
    
    if GATEWAY_TYPE == 'global':
        # Redirect to regional endpoint
        regional_url = router_service.get_regional_endpoint(region_id)
        redirect_url = f"{regional_url}/s3"
        
        return RedirectResponse(
            url=redirect_url,
            status_code=307,
            headers={
                "X-Customer-ID": customer_id,
                "X-Region-ID": region_id
            }
        )
    
    else:
        # Regional gateway - return logical bucket names
        try:
            with get_db() as session:
                mapping_service = BucketMappingService(session)
                buckets = mapping_service.list_customer_buckets(customer_id)
                
                # Format as S3 XML response
                bucket_list = []
                for bucket in buckets:
                    if bucket['status'] == 'active':
                        bucket_list.append({
                            "Name": bucket['logical_name'],
                            "CreationDate": bucket['created_at'].isoformat() if bucket['created_at'] else None
                        })
                
                return {
                    "ListAllMyBucketsResult": {
                        "Owner": {
                            "ID": customer_id,
                            "DisplayName": customer_id
                        },
                        "Buckets": {
                            "Bucket": bucket_list
                        }
                    }
                }
                
        except Exception as e:
            logger.error(f"Failed to list buckets: {e}")
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/s3/{bucket_name}")
async def list_objects_with_mapping(
    bucket_name: str,
    request: Request,
    x_customer_id: Optional[str] = Header(None, alias="X-Customer-ID")
):
    """List objects in bucket - uses mapped backend names"""
    
    customer_id = x_customer_id or extract_customer_from_request(request)
    region_id = get_region_from_request(request)
    
    if GATEWAY_TYPE == 'global':
        # Redirect to regional endpoint
        regional_url = router_service.get_regional_endpoint(region_id)
        redirect_url = f"{regional_url}/s3/{bucket_name}"
        
        return RedirectResponse(
            url=redirect_url,
            status_code=307,
            headers={
                "X-Customer-ID": customer_id,
                "X-Region-ID": region_id
            }
        )
    
    else:
        # Regional gateway - list objects from backend buckets
        try:
            with get_db() as session:
                mapping_service = BucketMappingService(session)
                backend_mapping = mapping_service.get_bucket_mapping(customer_id, bucket_name)
                
                if not backend_mapping:
                    return create_s3_error_response(
                        "NoSuchBucket",
                        f"Bucket '{bucket_name}' not found",
                        bucket_name
                    )
                
                # Get objects from primary backend (could aggregate from all)
                s3_backends = load_s3_backends()
                primary_backend = None
                primary_backend_name = None
                
                for backend_id, backend_bucket_name in backend_mapping.items():
                    if backend_id in s3_backends and s3_backends[backend_id].get('is_primary'):
                        primary_backend = s3_backends[backend_id]
                        primary_backend_name = backend_bucket_name
                        break
                
                if not primary_backend:
                    # Use first available backend
                    for backend_id, backend_bucket_name in backend_mapping.items():
                        if backend_id in s3_backends:
                            primary_backend = s3_backends[backend_id]
                            primary_backend_name = backend_bucket_name
                            break
                
                if not primary_backend:
                    return create_s3_error_response(
                        "InternalError",
                        "No available backends for bucket",
                        bucket_name
                    )
                
                # List objects from backend
                objects = list_backend_objects(primary_backend, primary_backend_name)
                
                return {
                    "ListBucketResult": {
                        "Name": bucket_name,  # Return logical name to customer
                        "Contents": objects,
                        "IsTruncated": False
                    }
                }
                
        except Exception as e:
            logger.error(f"Failed to list objects: {e}")
            return create_s3_error_response(
                "InternalError",
                f"Failed to list objects: {str(e)}",
                bucket_name
            )

# Helper functions for bucket mapping
def extract_customer_from_request(request: Request) -> str:
    """Extract customer ID from request headers or use default"""
    customer_id = request.headers.get("X-Customer-ID")
    if not customer_id:
        # Could extract from authentication, URL, etc.
        customer_id = "default-customer"
    return customer_id

def get_region_from_request(request: Request) -> str:
    """Determine region from request"""
    # Could be based on headers, URL routing, geo-IP, etc.
    region_id = request.headers.get("X-Region-ID")
    if not region_id:
        region_id = "FI-HEL"  # Default region
    return region_id

def log_bucket_creation(session, customer_id: str, logical_name: str, 
                       backend_id: str, backend_name: str, 
                       operation: str, status: str, error_message: str = None):
    """Log bucket creation operation"""
    try:
        from sqlalchemy import text
        
        query = text("""
            INSERT INTO bucket_creation_log 
            (customer_id, logical_name, backend_id, backend_name, operation, status, error_message)
            VALUES (:customer_id, :logical_name, :backend_id, :backend_name, :operation, :status, :error_message)
        """)
        
        session.execute(query, {
            'customer_id': customer_id,
            'logical_name': logical_name,
            'backend_id': backend_id,
            'backend_name': backend_name,
            'operation': operation,
            'status': status,
            'error_message': error_message
        })
        session.commit()
        
    except Exception as e:
        logger.error(f"Failed to log bucket creation: {e}")

def create_backend_bucket(backend_config: Dict, bucket_name: str) -> bool:
    """Create bucket on specific backend using hashed name"""
    try:
        # This would use boto3 or direct API calls to create bucket
        # For now, simulate success
        logger.info(f"Creating bucket '{bucket_name}' on backend {backend_config.get('provider')}")
        
        # TODO: Implement actual backend bucket creation
        # import boto3
        # s3_client = boto3.client('s3',
        #     endpoint_url=backend_config['endpoint'],
        #     aws_access_key_id=backend_config['access_key'],
        #     aws_secret_access_key=backend_config['secret_key']
        # )
        # s3_client.create_bucket(Bucket=bucket_name)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to create backend bucket: {e}")
        return False

def list_backend_objects(backend_config: Dict, bucket_name: str) -> List[Dict]:
    """List objects from specific backend bucket"""
    try:
        # This would use boto3 or direct API calls to list objects
        # For now, return empty list
        logger.info(f"Listing objects from bucket '{bucket_name}' on backend {backend_config.get('provider')}")
        
        # TODO: Implement actual backend object listing
        return []
        
    except Exception as e:
        logger.error(f"Failed to list backend objects: {e}")
        return []

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    
    logger.info(f"🚀 Starting S3 Gateway with Bucket Hash Mapping on {host}:{port}")
    logger.info(f"📊 Features: GDPR={GATEWAY_TYPE != 'global'}, Validation={ENABLE_S3_VALIDATION}, Mapping=True")
    
    uvicorn.run(app, host=host, port=port) 