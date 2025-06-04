# S3 Gateway Service

A dockerized S3-compatible gateway service with real S3 backend integration, data sovereignty support, versioning, and immutability features. Built using FastAPI and PostgreSQL for metadata storage.

## Features

- **S3 Authentication & Authorization**: Full AWS SigV4 signature validation with credential management
- **Real S3 Backend Integration**: Connects to actual S3-compatible storage providers
- **S3-Compatible API**: Full S3 operations (GET, PUT, DELETE, LIST) with `/s3/` prefix
- **S3 RFC-Compliant Validation**: Validates bucket names and object keys to prevent backend failures
- **Bucket Hash Mapping**: Solves S3 global namespace collisions with deterministic hashing
- **LocationConstraint Support**: S3-compatible location specification with cross-border control
- **GDPR-Compliant Architecture**: Two-layer design with HTTP redirects for data sovereignty
- **Data Sovereignty**: Provider selection based on country/region requirements
- **Versioning & Immutability**: Object versioning with immutable storage support
- **Metadata Authority**: PostgreSQL as single source of truth for object metadata
- **Provider Management**: Load and manage S3 providers from CSV and JSON configuration
- **Operation Logging**: Comprehensive logging of all S3 operations
- **Replication Management**: Multi-zone replication with real-time status tracking
- **Multi-Regional Support**: Separate databases and gateways for different jurisdictions

## Architecture

```
┌─────────────────┐    ┌─────────────────────────────────────────────────────────────┐
│   S3 Client     │    │             GDPR-Compliant Gateway Architecture            │
│                 │    │                                                             │
│ (AWS CLI,       │────│  ┌─────────────────┐           ┌─────────────────────────┐ │
│  boto3, etc.)   │    │  │ Global Gateway  │──HTTP 307─│   Regional Gateways     │ │
└─────────────────┘    │  │                 │  Redirect │                         │ │
                       │  │ • S3 Validation │           │ • FI-HEL (Standard)     │ │
                       │  │ • Customer      │           │ • DE-FRA (Strict)       │ │
                       │  │   Routing       │           │ • Full Customer Data    │ │
                       │  │ • Minimal Data  │           │ • Compliance Tracking   │ │
                       │  └─────────────────┘           └─────────────────────────┘ │
                       │           │                                  │               │
                       │  ┌─────────────────┐           ┌─────────────────────────┐ │
                       │  │ Global Database │           │  Regional Databases     │ │
                       │  │                 │           │                         │ │
                       │  │ • Provider Info │           │ • Customer Metadata     │ │
                       │  │ • Routing Only  │           │ • Object Metadata       │ │
                       │  │ • NO Customer   │           │ • Operations Log        │ │
                       │  │   Personal Data │           │ • Compliance Events     │ │
                       │  └─────────────────┘           └─────────────────────────┘ │
                       └─────────────────────────────────────────────────────────────┘
                                                │
                                      ┌─────────────────┐
                                      │ Real S3 Backends│
                                      │                 │
                                      │ (Spacetime,     │
                                      │  UpCloud,       │
                                      │  Hetzner, etc.) │
                                      └─────────────────┘
```

## S3 Authentication and Authorization

The gateway implements comprehensive AWS SigV4 authentication with fine-grained authorization to secure all S3 operations. This ensures that only authenticated users with proper permissions can access resources.

### GDPR-Compliant Authentication Architecture

The system uses **Option 3: Authentication After Redirect** - a GDPR-compliant approach where:

1. **Global Gateway**: Routes requests without authentication (minimal data processing)
2. **Regional Gateways**: Handle authentication using regional databases only
3. **Credential Storage**: All credentials stored in regional databases only

This ensures that authentication data never crosses jurisdictional boundaries and complies with GDPR data sovereignty requirements.

### How It Works

1. **Credential Creation**: Administrators create AWS-style access keys and secret keys for users
2. **Request Routing**: Global gateway routes S3 requests to appropriate regional endpoint
3. **Regional Authentication**: Regional gateway validates AWS SigV4 signatures against local credentials
4. **Authorization**: System checks user permissions for the requested resource/action  
5. **Audit Logging**: All authentication attempts and operations are logged regionally

### Authentication Flow

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   S3 Client     │────▶│   Global Gateway    │────▶│  Regional Gateway   │
│                 │     │                     │     │                     │
│ Signs request   │     │ • Routes customer   │     │ • Authenticates     │
│ with AWS SigV4  │     │ • NO authentication │     │ • Authorizes        │
│                 │     │ • Minimal data      │     │ • Processes S3 ops  │
│                 │     │ • HTTP 307 redirect │     │ • Local credentials │
└─────────────────┘     └─────────────────────┘     └─────────────────────┘
         │                                                     │
         │                                                     │
         └─────────────── Direct Redirect ────────────────────┘
               (preserves authentication headers)
```

### Security Features

✅ **Industry Standard**: AWS SigV4 signature validation (same as real AWS S3)  
✅ **GDPR Compliant**: Credentials stored only in regional databases  
✅ **Data Sovereignty**: Authentication happens in the correct jurisdiction  
✅ **Fine-Grained Permissions**: Resource-based access control per bucket/object  
✅ **Credential Management**: Full lifecycle management of access keys  
✅ **Audit Trail**: Comprehensive logging for compliance and security  
✅ **Real-Time Authorization**: Dynamic permission checking on every request  
✅ **Secure Storage**: Encrypted credential storage with activity tracking  
✅ **Zero Global Auth Data**: No credentials or sensitive data in global database  

### Credential Management

Credentials are managed through regional gateways only. Each regional gateway maintains its own set of user credentials.

#### Creating Credentials

```bash
# Create new S3 credentials for a user (via regional endpoint)
curl -X POST "http://localhost:8001/api/credentials/create" \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "John Doe",
    "user_email": "john@company.com",
    "permissions": {
      "s3:GetObject": ["my-bucket", "shared-*"],
      "s3:PutObject": ["my-bucket"],
      "s3:ListBucket": ["my-bucket", "shared-*"],
      "s3:CreateBucket": ["my-*"],
      "s3:GetObjectTagging": ["*"],
      "s3:PutObjectTagging": ["my-*"]
    }
  }'

# Response includes access key and secret key
{
  "access_key_id": "AKIA1234567890EXAMPLE",
  "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLE",
  "user_id": "user-abc123",
  "user_name": "John Doe",
  "permissions": {...},
  "message": "Credentials created successfully"
}
```

#### Permission System

Permissions follow AWS S3 action patterns with resource matching:

```json
{
  "permissions": {
    "s3:GetObject": ["bucket1", "bucket2/*", "shared-*"],
    "s3:PutObject": ["my-bucket/*"],
    "s3:DeleteObject": ["my-bucket/temp/*"],
    "s3:ListBucket": ["*"],
    "s3:CreateBucket": ["my-*", "test-*"],
    "s3:*": ["admin-bucket"]
  }
}
```

**Resource Patterns**:
- `bucket-name` - Exact bucket match
- `prefix-*` - Wildcard matching
- `*` - All resources
- `bucket/path/*` - Path-based object matching

#### Using with AWS CLI

```bash
# Configure AWS CLI with your credentials
aws configure set aws_access_key_id AKIA1234567890EXAMPLE --profile myprofile
aws configure set aws_secret_access_key wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLE --profile myprofile
aws configure set default.region fi-hel --profile myprofile

# Use authenticated S3 operations
aws s3 ls --endpoint-url http://localhost:8001 --profile myprofile
aws s3 cp file.txt s3://my-bucket/ --endpoint-url http://localhost:8001 --profile myprofile
aws s3api put-object-tagging --bucket my-bucket --key file.txt \
  --tagging 'TagSet=[{Key=Environment,Value=prod}]' \
  --endpoint-url http://localhost:8001 --profile myprofile
```

### API Endpoints

#### Credential Management
- `POST /api/credentials/create` - Create new credentials
- `GET  /api/credentials/list` - List all credentials  
- `GET  /api/credentials/{access_key_id}` - Get credential info
- `PUT  /api/credentials/{access_key_id}/permissions` - Update permissions
- `DELETE /api/credentials/{access_key_id}` - Deactivate credentials
- `POST /api/credentials/generate-demo` - Generate demo credentials
- `GET  /api/credentials/user/{user_id}/buckets` - List user buckets

#### All S3 Operations Require Authentication
- `GET /s3` - List buckets (shows only user's buckets)
- `PUT /s3/{bucket}` - Create bucket (requires CreateBucket permission)
- `GET /s3/{bucket}` - List objects (requires ListBucket permission)
- `GET /s3/{bucket}/{key}` - Get object (requires GetObject permission)
- `PUT /s3/{bucket}/{key}` - Put object (requires PutObject permission)
- `DELETE /s3/{bucket}/{key}` - Delete object (requires DeleteObject permission)
- All tagging operations require corresponding tagging permissions

### Authentication Flow

```
1. Client Request (with AWS SigV4 signature)
   ↓
2. Extract Authorization Header
   ↓
3. Parse Credential, SignedHeaders, Signature
   ↓
4. Lookup User Credentials in Database
   ↓
5. Calculate Expected Signature
   ↓
6. Compare Signatures
   ↓
7. Check User Permissions for Resource/Action
   ↓
8. Allow/Deny Request
   ↓
9. Log Authentication Result
```

### Bucket Ownership

Buckets are automatically assigned to the user who creates them:

```sql
-- Buckets table includes owner tracking
CREATE TABLE buckets (
    bucket_name VARCHAR(255) NOT NULL,
    owner_user_id VARCHAR(50), -- Links to s3_credentials.user_id
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ...
);

-- Users can only see and manage their own buckets
SELECT bucket_name FROM buckets WHERE owner_user_id = :user_id;
```

### Security Configuration

Environment variables control authentication behavior:

```bash
# Enable/disable authentication (default: true)
ENABLE_S3_AUTHENTICATION=true

# Endpoints that bypass authentication (default: ["/health", "/api/credentials"])
S3_AUTH_BYPASS_ENDPOINTS='["/health", "/api/credentials", "/validation"]'
```

### Demo and Testing

Run the authentication demo to see the system in action:

```bash
# Run comprehensive authentication demo
./demo-s3-authentication.sh
```

This demo shows:
- Credential creation and management
- Authenticated S3 operations with AWS CLI
- Permission enforcement and authorization failures
- Credential updates and deactivation
- Audit logging and compliance features

### Error Handling

The system returns standard S3 error responses:

```xml
<!-- Missing authentication -->
<Error>
    <Code>MissingSecurityHeader</Code>
    <Message>Missing Authorization header</Message>
    <Resource>/bucket/object</Resource>
    <RequestId>12345678-1234-1234-1234-123456789012</RequestId>
</Error>

<!-- Invalid credentials -->
<Error>
    <Code>InvalidAccessKeyId</Code>
    <Message>Invalid access key</Message>
    <Resource>/bucket/object</Resource>
    <RequestId>12345678-1234-1234-1234-123456789012</RequestId>
</Error>

<!-- Permission denied -->
<Error>
    <Code>AccessDenied</Code>
    <Message>Access denied for action s3:GetObject</Message>
    <Resource>/bucket/object</Resource>
    <RequestId>12345678-1234-1234-1234-123456789012</RequestId>
</Error>
```

### Database Schema

Authentication data is stored securely:

```sql
-- S3 credentials with permissions
CREATE TABLE s3_credentials (
    access_key_id VARCHAR(20) UNIQUE NOT NULL,
    secret_access_key VARCHAR(40) NOT NULL,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    user_name VARCHAR(100) NOT NULL,
    permissions JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);

-- Authentication audit log
CREATE TABLE s3_auth_log (
    access_key_id VARCHAR(20),
    request_method VARCHAR(10),
    request_path VARCHAR(1024),
    auth_status VARCHAR(20), -- success, failed, access_denied
    error_message TEXT,
    source_ip INET,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Benefits

🔐 **Enterprise Security**: AWS-compatible authentication that works with existing tools  
🔐 **Compliance Ready**: Comprehensive audit logs for security compliance  
🔐 **Flexible Permissions**: Fine-grained control over who can access what  
🔐 **Zero Trust**: Every request authenticated and authorized  
🔐 **Credential Management**: Full lifecycle management with secure storage  
🔐 **Real-time Control**: Immediate credential deactivation and permission updates  

The authentication system ensures that your S3 gateway is production-ready with enterprise-grade security that's fully compatible with existing AWS S3 tools and workflows.

## LocationConstraint

The gateway supports S3-compatible LocationConstraint with advanced multi-location capabilities. Unlike standard S3 which only supports single regions, our implementation allows comma-separated regions/zones with sophisticated replication control.

### How It Works

1. **Bucket Creation**: Customer specifies LocationConstraint during bucket creation
2. **Location Parsing**: System parses comma-separated locations (regions or zones)
3. **Primary Placement**: Bucket created in first specified location (primary)
4. **Replication Control**: Additional locations define replication possibilities
5. **Cross-Border Policy**: Replication across countries only if multiple countries specified

### LocationConstraint Syntax

```
LocationConstraint: comma-separated list of regions/zones
Examples:
- "fi"                      # Single region (Finland)
- "fi,de"                   # Cross-border (Finland + Germany)
- "fi-hel-st-1"            # Specific zone
- "fi,de,fr"               # Multi-country replication
- "fi-hel-st-1,de-fra-uc-1" # Specific zones
```

### Order-Based Priority

The order matters:
1. **First location = Primary**: Bucket initially created here
2. **Additional locations = Replication targets**: Used when replica_count > 1
3. **Cross-border control**: Multiple countries enable cross-border replication

### Location Types

**Regions** (resolve to first available zone):
- `fi` → `fi-hel-st-1` (Finland region → Helsinki Spacetime zone)
- `de` → `de-fra-st-1` (Germany region → Frankfurt Spacetime zone)
- `fr` → `fr-par-st-1` (France region → Paris Spacetime zone)

**Specific Zones**:
- `fi-hel-st-1` (Helsinki Spacetime)
- `fi-hel-uc-1` (Helsinki UpCloud)
- `de-fra-hz-1` (Frankfurt Hetzner)

### Replication Control

**Default Behavior**: Only primary location used (replica_count = 1)

**Increasing Replicas**: Set replica_count via API or tags
```bash
# Increase to 2 replicas (uses first 2 locations)
curl -X PUT "http://localhost:8000/api/location-constraints/customer/bucket/replica-count" \
  -d '{"replica_count": 2}'
```

**Replica Placement Logic**:
```
LocationConstraint: "fi,de,fr"
replica_count: 1 → ["fi-hel-st-1"]                    # Primary only
replica_count: 2 → ["fi-hel-st-1", "de-fra-st-1"]    # Primary + first additional
replica_count: 3 → ["fi-hel-st-1", "de-fra-st-1", "fr-par-st-1"]  # All specified
```

### Cross-Border Replication

**Single Country**: `"fi"` or `"fi,fi-hel"` → No cross-border replication allowed
**Multi-Country**: `"fi,de"` → Cross-border replication enabled between Finland and Germany

This enforces data sovereignty by default while allowing explicit cross-border replication when needed.

### Examples

#### Basic Usage

```bash
# Create bucket in Finland only
curl -X PUT -H "X-Customer-ID: company" \
  -d '<CreateBucketConfiguration><LocationConstraint>fi</LocationConstraint></CreateBucketConfiguration>' \
  "http://localhost:8000/s3/my-bucket"

# Create with cross-border replication allowed
curl -X PUT -H "X-Customer-ID: company" \
  -d '<CreateBucketConfiguration><LocationConstraint>fi,de</LocationConstraint></CreateBucketConfiguration>' \
  "http://localhost:8000/s3/eu-bucket"

# Create in specific zone
curl -X PUT -H "X-Customer-ID: company" \
  -d '<CreateBucketConfiguration><LocationConstraint>fi-hel-st-1</LocationConstraint></CreateBucketConfiguration>' \
  "http://localhost:8000/s3/zone-specific"
```

#### Advanced Scenarios

**Compliance Scenario**: Company must keep data in Finland but wants option for EU expansion
```
LocationConstraint: "fi,de,fr"
replica_count: 1           # Starts in Finland only
                          # Can expand to Germany/France later
```

**Performance Scenario**: Multi-region application with specific zone requirements
```
LocationConstraint: "fi-hel-st-1,de-fra-uc-1,fr-par-hz-1"
replica_count: 3           # Data in all three zones
                          # Optimized for specific provider capabilities
```

**Cost Optimization**: Primary in cheaper region, replica in premium region
```
LocationConstraint: "de,fi"
replica_count: 1           # Starts in Germany (primary)
                          # Can add Finland replica if needed
```

### API Management

```bash
# Test location constraint parsing
curl -X POST "http://localhost:8000/api/location-constraints/test" \
  -d '{"location_constraint": "fi,de", "replica_count": 2}'

# Get bucket location policy
curl "http://localhost:8000/api/location-constraints/customer/bucket"

# Update replica count (triggers replication)
curl -X PUT "http://localhost:8000/api/location-constraints/customer/bucket/replica-count" \
  -d '{"replica_count": 3}'

# List available locations
curl "http://localhost:8000/api/location-constraints/available-locations"
```

### Benefits

✅ **S3 Compatibility**: Standard LocationConstraint syntax  
✅ **Multi-Location Support**: Comma-separated regions/zones  
✅ **Order-Based Priority**: Predictable placement logic  
✅ **Cross-Border Control**: Automatic sovereignty enforcement  
✅ **Flexible Targeting**: Region or zone-level precision  
✅ **Dynamic Replication**: Adjust replica_count without recreating bucket  
✅ **Cost Optimization**: Choose regions/zones based on requirements  
✅ **Compliance Support**: Keep data in specific jurisdictions  

## Development

### Adding New S3 Backends

1. Update `config/s3_backends.json` with new backend configuration
2. Restart the gateway service
3. Test with bucket creation: `curl -X PUT -H "X-Customer-ID: test" http://localhost:8000/s3/test-bucket`

### Testing

```bash
# Start services
docker-compose up -d

# Check health
curl http://localhost:8000/health

# Create a test bucket with hash mapping
curl -X PUT -H "X-Customer-ID: test-customer" http://localhost:8000/s3/test-bucket

# Upload test object
curl -X PUT -H "X-Customer-ID: test-customer" \
  -d "Hello World" http://localhost:8000/s3/test-bucket/hello.txt

# Get test object
curl -H "X-Customer-ID: test-customer" http://localhost:8000/s3/test-bucket/hello.txt

# List objects in bucket
curl -H "X-Customer-ID: test-customer" http://localhost:8000/s3/test-bucket

# Check bucket mapping
curl "http://localhost:8000/api/bucket-mappings/test-customer/test-bucket"
```

## Conclusion

You now have a complete S3 gateway with:

✅ **S3 RFC-compliant naming validation** - Prevents backend failures
✅ **Bucket hash mapping** - Solves S3 global namespace collisions
✅ **LocationConstraint support** - S3-compatible multi-location control
✅ **S3-compatible tagging API** - Full tagging support with XML payloads
✅ **Tag-based replica management** - Set replica-count via tags
✅ **Background replication queue** - Non-blocking replication operations
✅ **GDPR-compliant two-layer architecture** - HTTP redirects for data sovereignty  
✅ **Multi-regional support** - FI-HEL and DE-FRA regions
✅ **Multi-backend replication** - Unique bucket names per backend
✅ **Customer isolation** - Deterministic hashing with collision avoidance
✅ **Cross-border replication control** - Based on specified countries
✅ **Order-based location priority** - First location = primary placement
✅ **Flexible region/zone targeting** - fi, fi-hel, fi-hel-st-1 syntax
✅ **Dynamic replica management** - Adjust replica_count via API or tags
✅ **Comprehensive validation** - Bucket names and object keys
✅ **S3 Authentication & Authorization** - AWS SigV4 with GDPR-compliant architecture
✅ **Production-ready security** - Enterprise-grade authentication system

### Quick Start

```bash
# Start all services and explore features
./run.sh start
./run.sh

# Or test everything quickly
./run.sh quick
```

### Key Features Demo

```bash
./run.sh auth        # AWS SigV4 authentication with credential management
./run.sh mapping     # Bucket hash mapping solves namespace collisions  
./run.sh tagging     # S3 tagging with background replication
./run.sh gdpr        # GDPR-compliant architecture demonstration
./run.sh test        # Comprehensive validation and compliance tests
```

### Manual Commands (Alternative)

If you prefer individual scripts:

```bash
# Start services
./start.sh

# Run comprehensive tests
./test.sh

# Authentication demo
./demo-s3-authentication.sh

# Bucket mapping demo
./demo-bucket-mapping.sh

# Tagging and replication demo
./demo-tagging-replication.sh
```

## Unified Launcher Commands

The `./run.sh` script provides organized access to all functionality:

### 🏗️ Setup & Management
```bash
./run.sh start      # Start all services
./run.sh stop       # Stop all services  
./run.sh restart    # Restart with fresh data
./run.sh status     # Check service health
./run.sh logs       # View service logs
```

### 🧪 Testing & Validation
```bash
./run.sh test       # Comprehensive test suite
./run.sh quick      # Quick smoke test
```

### 🔐 Authentication & Security  
```bash
./run.sh auth       # Full AWS SigV4 authentication demo
./run.sh auth-arch  # Test GDPR-compliant auth architecture
```

### 🗺️ Bucket Mapping & Location
```bash
./run.sh mapping    # Bucket hash mapping demo
./run.sh location   # LocationConstraint features
```

### 🏷️ Tagging & Replication
```bash
./run.sh tagging    # S3 tagging with replication demo
./run.sh replica    # Replication management demo
```

### ⚖️ GDPR Compliance
```bash
./run.sh gdpr       # GDPR compliance demonstration
./run.sh privacy    # Data sovereignty verification
```

### 📚 Documentation
```bash
./run.sh features   # List all S3 gateway features
./run.sh help       # Detailed help for all commands
```

## Workflow

The S3 gateway follows standard S3 workflow with bucket hash mapping and tagging:

1. **Create bucket** (generates hash mapping):
   ```bash
   curl -X PUT -H "X-Customer-ID: my-company" http://localhost:8000/s3/my-data-bucket
   ```

2. **Upload objects** (to existing bucket):
   ```bash
   curl -X PUT -H "X-Customer-ID: my-company" \
     -d "Hello World" http://localhost:8000/s3/my-data-bucket/documents/file.txt
   ```

3. **Set tags** (triggers replication based on replica-count):
   ```bash
   curl -X PUT "http://localhost:8001/s3/my-data-bucket/documents/file.txt?tagging" \
     -H "X-Customer-ID: my-company" \
     -H "Content-Type: application/xml" \
     -d '<Tagging><TagSet><Tag><Key>replica-count</Key><Value>3</Value></Tag></TagSet></Tagging>'
   ```

4. **List objects**:
   ```bash
   curl -H "X-Customer-ID: my-company" http://localhost:8000/s3/my-data-bucket
   ```

5. **View bucket mapping**:
   ```bash
   curl http://localhost:8000/api/bucket-mappings/my-company/my-data-bucket
   ```

6. **Check replication status**:
   ```bash
   curl http://localhost:8001/api/replication/jobs/active
   ```

Behind the scenes: Customer sees `my-data-bucket`, but backends get unique names like `s3gw-a1b2c3d4-spacetim`, solving S3's global namespace collision problem. Tags trigger background replication jobs for non-blocking operations. 