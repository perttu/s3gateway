#!/usr/bin/env python3
"""
S3 Gateway Service - Two-Layer Architecture
Supports both global routing gateway and regional compliance gateway modes.
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
from fastapi.responses import JSONResponse
import pandas as pd
import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
GATEWAY_TYPE = os.getenv('GATEWAY_TYPE', 'regional')  # 'global' or 'regional'
REGION_ID = os.getenv('REGION_ID', 'FI-HEL')
REGIONAL_ENDPOINTS = json.loads(os.getenv('REGIONAL_ENDPOINTS', '{}'))

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
    description=f"Two-layer S3 gateway - {GATEWAY_TYPE} tier with compliance support",
    version="3.0.0"
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
    
    async def create_bucket(self, bucket_name: str) -> Dict:
        """Create bucket in this backend"""
        try:
            if self.region == 'us-east-1':
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
        """Upload object to this backend"""
        try:
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
        """Get object from this backend"""
        try:
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
                return {"status": "error", "backend": self.name, "error": str(e)}

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
        """Log routing decision to global database (minimal info only)"""
        if not GlobalSessionLocal:
            return
            
        with GlobalSessionLocal() as db:
            query = text("""
                INSERT INTO routing_log 
                (customer_id, source_ip, requested_endpoint, routed_to_region, 
                 routed_to_endpoint, routing_reason, user_agent)
                VALUES (:customer_id, :source_ip, :requested_endpoint, :routed_to_region,
                        :routed_to_endpoint, :routing_reason, :user_agent)
            """)
            
            db.execute(query, {
                'customer_id': customer_id,
                'source_ip': str(request.client.host) if request.client else None,
                'requested_endpoint': str(request.url),
                'routed_to_region': region,
                'routed_to_endpoint': self.get_regional_endpoint(region),
                'routing_reason': reason,
                'user_agent': request.headers.get('user-agent', '')
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
    
    if GATEWAY_TYPE == 'regional':
        logger.info(f"Regional gateway for region: {REGION_ID}")
        if not load_s3_backends():
            logger.warning("Failed to load S3 backends - some features may not work")
    else:
        logger.info("Global routing gateway")
    
    load_providers()

# Global Gateway Routes (GATEWAY_TYPE == 'global')
if GATEWAY_TYPE == 'global':
    
    @app.middleware("http")
    async def routing_middleware(request: Request, call_next):
        """Route requests to appropriate regional endpoints"""
        
        # Extract customer ID from headers, query params, or path
        customer_id = (
            request.headers.get('X-Customer-ID') or
            request.query_params.get('customer_id') or
            'demo-customer'
        )
        
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
        
        # Log routing decision
        router_service.log_routing_decision(customer_id, target_region, routing_reason, request)
        
        # For S3 API calls, proxy to regional endpoint
        if request.url.path.startswith('/s3/'):
            return await proxy_to_regional(request, regional_endpoint, customer_id)
        
        # For API calls, continue processing locally or proxy
        response = await call_next(request)
        response.headers['X-Routed-To-Region'] = target_region
        response.headers['X-Customer-ID'] = customer_id
        return response
    
    async def proxy_to_regional(request: Request, regional_endpoint: str, customer_id: str):
        """Proxy S3 requests to regional endpoint"""
        
        # Build target URL
        target_url = f"{regional_endpoint.rstrip('/')}{request.url.path}"
        if request.url.query:
            target_url += f"?{request.url.query}"
        
        # Prepare headers
        headers = dict(request.headers)
        headers['X-Customer-ID'] = customer_id
        headers['X-Proxied-From'] = 'global-gateway'
        headers.pop('host', None)
        
        async with httpx.AsyncClient() as client:
            try:
                if request.method == 'GET':
                    response = await client.get(target_url, headers=headers)
                elif request.method == 'PUT':
                    body = await request.body()
                    response = await client.put(target_url, headers=headers, content=body)
                elif request.method == 'DELETE':
                    response = await client.delete(target_url, headers=headers)
                elif request.method == 'POST':
                    body = await request.body()
                    response = await client.post(target_url, headers=headers, content=body)
                else:
                    raise HTTPException(status_code=405, detail="Method not allowed")
                
                # Return proxied response
                response_headers = dict(response.headers)
                response_headers['X-Proxied-From'] = 'global-gateway'
                response_headers['X-Target-Region'] = target_region
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=response.headers.get('content-type', 'application/octet-stream')
                )
                
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=502, 
                    detail=f"Failed to proxy to regional endpoint: {str(e)}"
                )
    
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
            "regional_endpoints": regional_status
        }
    
    @app.get("/routing/customers/{customer_id}")
    async def get_customer_routing(customer_id: str):
        """Get MINIMAL routing information for a customer"""
        region = router_service.get_customer_region(customer_id)
        endpoint = router_service.get_regional_endpoint(region) if region else None
        
        return {
            "customer_id": customer_id,
            "primary_region": region,
            "regional_endpoint": endpoint,
            "available_regions": list(REGIONAL_ENDPOINTS.keys()),
            "note": "Detailed compliance data is stored in regional database"
        }
    
    @app.post("/routing/customers/{customer_id}")
    async def register_customer_routing(customer_id: str, region_id: str):
        """Register customer routing assignment (global level only)"""
        if not GlobalSessionLocal:
            raise HTTPException(status_code=500, detail="Global database not available")
        
        with GlobalSessionLocal() as db:
            query = text("""
                INSERT INTO customer_routing (customer_id, primary_region_id, routing_notes)
                VALUES (:customer_id, :region_id, :notes)
                ON CONFLICT (customer_id) 
                DO UPDATE SET primary_region_id = :region_id, updated_at = CURRENT_TIMESTAMP
            """)
            
            db.execute(query, {
                'customer_id': customer_id,
                'region_id': region_id,
                'notes': f'Customer assigned to {region_id} region'
            })
            db.commit()
        
        return {
            "customer_id": customer_id,
            "assigned_region": region_id,
            "message": "Customer routing registered. Complete customer registration must be done in regional database."
        }

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
        """Log operation in regional database with compliance info"""
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
            
            compliance_info = {
                "region_processed": REGION_ID,
                "cross_border_transfer": False,
                "legal_basis": "legitimate_interest"
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
            "backend_count": len(s3_backends)
        }
    
    @app.get("/s3/{bucket_name}")
    async def list_objects(
        request: Request,
        bucket_name: str, 
        x_customer_id: str = Header(alias="X-Customer-ID", default="demo-customer")
    ):
        """List objects in bucket (from regional metadata with compliance check)"""
        
        # Verify customer exists in this region
        customer_info = get_customer_info(x_customer_id)
        if not customer_info:
            raise HTTPException(status_code=404, detail="Customer not found in this region")
        
        if customer_info['region_id'] != REGION_ID:
            raise HTTPException(status_code=403, detail=f"Customer belongs to region {customer_info['region_id']}, not {REGION_ID}")
        
        objects = get_customer_objects(x_customer_id, bucket_name)
        
        # Log the operation
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
                "X-Compliance-Status": customer_info['compliance_status']
            }
        )
    
    @app.get("/api/customers/{customer_id}/info")
    async def get_customer_info_api(customer_id: str):
        """Get complete customer information (compliance data from regional DB)"""
        customer_info = get_customer_info(customer_id)
        
        if not customer_info:
            raise HTTPException(status_code=404, detail="Customer not found in this region")
        
        return {
            "customer_info": customer_info,
            "region": REGION_ID,
            "note": "Complete compliance data available in regional database"
        }
    
    @app.get("/api/compliance/summary")
    async def compliance_summary(
        x_customer_id: str = Header(alias="X-Customer-ID", default="demo-customer")
    ):
        """Get detailed compliance summary for customer (from regional database)"""
        with SessionLocal() as db:
            query = text("""
                SELECT * FROM customer_compliance_summary 
                WHERE customer_id = :customer_id
            """)
            
            result = db.execute(query, {'customer_id': x_customer_id}).fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail="Customer not found in this region")
            
            return dict(result)
    
    @app.post("/api/customers/{customer_id}/register")
    async def register_customer_regional(customer_id: str, customer_data: dict):
        """Register complete customer information in regional database"""
        with SessionLocal() as db:
            query = text("""
                INSERT INTO customers 
                (customer_id, customer_name, region_id, country, data_residency_requirement,
                 compliance_requirements, primary_contact_email, compliance_officer_email,
                 next_compliance_review)
                VALUES (:customer_id, :customer_name, :region_id, :country, 
                        :data_residency_requirement, :compliance_requirements,
                        :primary_contact_email, :compliance_officer_email, :next_compliance_review)
                ON CONFLICT (customer_id) DO UPDATE SET
                customer_name = :customer_name,
                updated_at = CURRENT_TIMESTAMP
            """)
            
            db.execute(query, {
                'customer_id': customer_id,
                'customer_name': customer_data.get('customer_name', customer_id),
                'region_id': REGION_ID,
                'country': customer_data.get('country', 'Unknown'),
                'data_residency_requirement': customer_data.get('data_residency_requirement', 'strict'),
                'compliance_requirements': json.dumps(customer_data.get('compliance_requirements', [])),
                'primary_contact_email': customer_data.get('primary_contact_email'),
                'compliance_officer_email': customer_data.get('compliance_officer_email'),
                'next_compliance_review': customer_data.get('next_compliance_review')
            })
            db.commit()
        
        return {
            "customer_id": customer_id,
            "region": REGION_ID,
            "message": "Customer registered in regional database with complete compliance data"
        }

@app.get("/")
async def root():
    return {
        "service": f"s3-gateway-{GATEWAY_TYPE}",
        "region": REGION_ID if GATEWAY_TYPE == 'regional' else 'global',
        "message": f"Two-layer S3 Gateway ({GATEWAY_TYPE} tier) - Compliance architecture",
        "compliance_note": "Customer compliance data stored in regional databases only"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 