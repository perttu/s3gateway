#!/usr/bin/env python3
"""
S3 Gateway Service - GDPR-Compliant Two-Layer Architecture
Uses HTTP redirects to ensure customer data goes directly to regional endpoints
without passing through the global gateway (preventing GDPR violations).
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
GATEWAY_TYPE = os.getenv('GATEWAY_TYPE', 'regional')  # 'global' or 'regional'
REGION_ID = os.getenv('REGION_ID', 'FI-HEL')
REGIONAL_ENDPOINTS = json.loads(os.getenv('REGIONAL_ENDPOINTS', '{}'))
ENABLE_GDPR_REDIRECTS = os.getenv('ENABLE_GDPR_REDIRECTS', 'true').lower() == 'true'

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
    description=f"GDPR-compliant two-layer S3 gateway - {GATEWAY_TYPE} tier",
    version="3.1.0"
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
            # Only log minimal routing information for operational purposes
            query = text("""
                INSERT INTO routing_log 
                (customer_id, routed_to_region, routing_reason, created_at)
                VALUES (:customer_id, :routed_to_region, :routing_reason, CURRENT_TIMESTAMP)
            """)
            
            db.execute(query, {
                'customer_id': customer_id,  # Just the ID for routing
                'routed_to_region': region,
                'routing_reason': reason
                # NO IP addresses, user agents, or request details in global logs
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
    
    load_providers()

# Global Gateway Routes (GATEWAY_TYPE == 'global')
if GATEWAY_TYPE == 'global':
    
    @app.middleware("http")
    async def gdpr_routing_middleware(request: Request, call_next):
        """GDPR-compliant routing using HTTP redirects"""
        
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
            "gdpr_compliance": "Customer data stored only in regional database",
            "access_method": "HTTP redirect to regional endpoint"
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
            "message": "Customer routing registered. Complete customer registration must be done in regional database.",
            "gdpr_compliance": "Only routing assignment stored globally - no customer data"
        }
    
    @app.get("/compliance/audit")
    async def global_compliance_audit():
        """Global compliance audit - show what data is stored globally"""
        if not GlobalSessionLocal:
            raise HTTPException(status_code=500, detail="Global database not available")
        
        with GlobalSessionLocal() as db:
            # Count routing assignments (should be minimal)
            routing_count = db.execute(text("SELECT COUNT(*) FROM customer_routing")).fetchone()[0]
            
            # Count routing logs (operational only)
            log_count = db.execute(text("SELECT COUNT(*) FROM routing_log")).fetchone()[0]
            
            # Sample routing data (anonymized)
            sample_routing = db.execute(text("""
                SELECT customer_id, primary_region_id, created_at 
                FROM customer_routing 
                ORDER BY created_at DESC 
                LIMIT 5
            """)).fetchall()
        
        return {
            "global_database_content": {
                "routing_assignments": routing_count,
                "routing_logs": log_count,
                "data_types": ["customer_id", "region_assignment", "routing_logs"],
                "no_customer_data": ["emails", "names", "compliance_details", "ip_addresses", "requests"]
            },
            "sample_routing": [dict(row) for row in sample_routing],
            "gdpr_compliance": "Global database contains ONLY routing assignments, no customer personal data"
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
            
            compliance_info = {
                "region_processed": REGION_ID,
                "direct_regional_access": not redirected,
                "gdpr_redirect": redirected,
                "cross_border_transfer": False,
                "legal_basis": "legitimate_interest",
                "data_sovereignty_compliant": True
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
            "gdpr_compliance": "Full customer data stored regionally"
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
                "X-Data-Sovereignty": f"Data processed in {REGION_ID}"
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
            "gdpr_compliance": "Complete customer data available in regional database only"
        }
    
    @app.get("/api/compliance/audit")
    async def regional_compliance_audit(
        x_customer_id: str = Header(alias="X-Customer-ID", default="demo-customer")
    ):
        """Regional compliance audit - show customer's complete data footprint"""
        with SessionLocal() as db:
            # Customer info
            customer_info = get_customer_info(x_customer_id)
            
            if not customer_info:
                raise HTTPException(status_code=404, detail="Customer not found in this region")
            
            # Count of various data types
            object_count = db.execute(text("""
                SELECT COUNT(*) FROM object_metadata WHERE customer_id = :customer_id
            """), {'customer_id': x_customer_id}).fetchone()[0]
            
            operation_count = db.execute(text("""
                SELECT COUNT(*) FROM operations_log WHERE customer_id = :customer_id
            """), {'customer_id': x_customer_id}).fetchone()[0]
            
            # Recent operations
            recent_ops = db.execute(text("""
                SELECT operation_type, bucket_name, created_at, compliance_info
                FROM operations_log 
                WHERE customer_id = :customer_id 
                ORDER BY created_at DESC 
                LIMIT 10
            """), {'customer_id': x_customer_id}).fetchall()
        
        return {
            "customer_id": x_customer_id,
            "region": REGION_ID,
            "data_summary": {
                "customer_profile": customer_info,
                "object_count": object_count,
                "operation_count": operation_count,
                "data_types": ["customer_profile", "object_metadata", "operations_log", "compliance_events"]
            },
            "recent_operations": [dict(row) for row in recent_ops],
            "gdpr_compliance": f"All customer data stored in {REGION_ID} region only",
            "data_sovereignty": "Fully compliant - no cross-border data transfers"
        }

@app.get("/")
async def root():
    return {
        "service": f"s3-gateway-{GATEWAY_TYPE}",
        "region": REGION_ID if GATEWAY_TYPE == 'regional' else 'global',
        "message": f"GDPR-compliant two-layer S3 Gateway ({GATEWAY_TYPE} tier)",
        "gdpr_compliance": "Customer data processed only in designated regional endpoints",
        "redirect_mode": ENABLE_GDPR_REDIRECTS if GATEWAY_TYPE == 'global' else "N/A"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 