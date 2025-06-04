# S3 Gateway Service

A dockerized S3-compatible gateway service with real S3 backend integration, data sovereignty support, versioning, and immutability features. Built using FastAPI and PostgreSQL for metadata storage.

## Features

- **Real S3 Backend Integration**: Connects to actual S3-compatible storage providers
- **S3-Compatible API**: Full S3 operations (GET, PUT, DELETE, LIST) with `/s3/` prefix
- **S3 RFC-Compliant Validation**: Validates bucket names and object keys to prevent backend failures
- **Bucket Hash Mapping**: Solves S3 global namespace collisions with deterministic hashing
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

## Directory Structure

```
s3gateway/
├── docker-compose.yml          # Main orchestration
├── config/
│   ├── s3proxy.conf           # S3Proxy configuration
│   └── s3_backends.json       # Real S3 backend configuration
├── docker/
│   ├── s3proxy/
│   │   ├── Dockerfile         # S3Proxy container
│   │   └── s3proxy.conf       # S3Proxy config
│   └── gateway/
│       ├── Dockerfile         # Gateway service container
│       └── requirements.txt   # Python dependencies
├── code/
│   └── gateway/
│       ├── main.py           # FastAPI application
│       ├── schema.sql        # Database schema (used by docker-compose)
│       └── Dockerfile        # Gateway dockerfile
├── providers_flat.csv         # Provider data
└── README.md
```

## Quick Start

1. **Start the services:**
```bash
cd s3gateway
./start.sh
```

2. **Run comprehensive tests:**
```bash
./test.sh
```

3. **Check service status:**
```bash
docker-compose ps
curl http://localhost:8000/health
```

4. **View logs:**
```bash
docker-compose logs -f
```

5. **GDPR compliance demo:**
```bash
./demo-gdpr-compliance.sh
```

## API Endpoints

### Gateway Management
- `GET /health` - Health check with backend status
- `GET /providers` - List available providers from CSV
- `GET /backends` - List configured S3 backends
- `GET /bucket-config` - Get hardcoded bucket configuration
- `POST /initialize-bucket` - Create hardcoded bucket in all backends
- `GET /api/replicas/status` - Get object replication status
- `GET /api/operations/log` - View operations log

### S3-Compatible API (All with `/s3/` prefix)
- `GET /s3` - List buckets
- `GET /s3/{bucket}` - List objects in bucket (uses hardcoded bucket)
- `PUT /s3/{bucket}` - Create bucket (creates hardcoded bucket)
- `GET /s3/{bucket}/{key}` - Get object (from hardcoded bucket)
- `PUT /s3/{bucket}/{key}` - Put object (to hardcoded bucket)
- `DELETE /s3/{bucket}/{key}` - Delete object (from hardcoded bucket)

### Bucket Hash Mapping API
- `GET /api/bucket-mappings/{customer_id}` - List customer bucket mappings
- `GET /api/bucket-mappings/{customer_id}/{logical_name}` - Get specific bucket mapping
- `POST /api/bucket-mappings/test` - Test bucket mapping generation

## Configuration

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `S3PROXY_URL`: S3Proxy service URL (for fallback)
- `PROVIDERS_FILE`: Path to providers CSV file
- `S3_BACKENDS_CONFIG`: Path to S3 backends JSON configuration

### S3 Backends Configuration

The service loads real S3 backend configurations from `config/s3_backends.json`:

```json
{
  "spacetime": {
    "provider": "Spacetime",
    "zone_code": "FI-HEL-ST-1",
    "region": "FI-HEL",
    "endpoint": "https://hel1.your-objectstorage.com",
    "access_key": "your-access-key",
    "secret_key": "your-secret-key",
    "is_primary": true,
    "enabled": true
  }
}
```

### Provider Data

The service loads provider information from `providers_flat.csv` containing Finnish providers:
- Zone codes and regions (Helsinki focus)
- Provider capabilities (S3 compatibility, Object Lock, Versioning)
- Compliance information (ISO 27001, GDPR)
- Geographic location data

## Usage Examples

### Using AWS CLI

1. **Configure AWS CLI:**
```bash
aws configure set aws_access_key_id local-identity
aws configure set aws_secret_access_key local-credential
aws configure set default.region us-east-1
```

2. **List buckets:**
```bash
aws s3 ls --endpoint-url http://localhost:8080
```

3. **Create bucket (creates hardcoded bucket):**
```bash
aws s3 mb s3://any-name --endpoint-url http://localhost:8080
```

4. **Upload file (goes to hardcoded bucket):**
```bash
echo "Hello World" > test.txt
aws s3 cp test.txt s3://any-name/ --endpoint-url http://localhost:8080
```

### Using Direct API

1. **List objects:**
```bash
curl http://localhost:8000/s3/any-bucket-name
```

2. **Create bucket:**
```bash
curl -X PUT http://localhost:8000/s3/my-bucket
```

3. **Upload object:**
```bash
curl -X PUT http://localhost:8000/s3/my-bucket/test.txt -d "Hello World"
```

4. **Get object:**
```bash
curl http://localhost:8000/s3/my-bucket/test.txt
```

### Check System Status

```bash
# Check health and backend status
curl "http://localhost:8000/health"

# List configured backends
curl "http://localhost:8000/backends"

# View replication status
curl "http://localhost:8000/api/replicas/status"

# View operations log
curl "http://localhost:8000/api/operations/log"
```

## Database Schema

The service uses PostgreSQL to store:

- **Providers**: Available S3 providers and their capabilities
- **Buckets**: Bucket metadata and location information
- **Objects**: Object metadata with versioning and immutability tracking
- **Object Replicas**: Detailed replica status for each zone
- **Sync Jobs**: Queue for managing data replication
- **Operations Log**: All S3 operations for auditing
- **Replication Rules**: Data sovereignty and replication requirements
- **Bucket Mappings**: Mapping between customer logical names and backend bucket names

### Key Features

- **Metadata Authority**: PostgreSQL is the single source of truth
- **Versioning**: Each object upload gets a unique version ID
- **Immutability**: Objects are tracked as immutable with replica verification
- **Multi-Zone Replication**: Objects are replicated across multiple S3 backends
- **Bucket Hash Mapping**: Solves S3 global namespace collisions with deterministic hashing

## Hardcoded Bucket Strategy

The service uses a hardcoded bucket approach for security and simplicity:

- All operations use the bucket `2025-datatransfer`
- Bucket name in client requests is ignored
- This ensures consistent data placement and security
- Real bucket is created in all configured S3 backends

## Development

### Adding New S3 Backends

1. Update `config/s3_backends.json` with new backend configuration
2. Restart the gateway service
3. Initialize bucket: `curl -X POST http://localhost:8000/initialize-bucket`

### Testing

```bash
# Start services
docker-compose up -d

# Check health
curl http://localhost:8000/health

# Initialize bucket
curl -X POST http://localhost:8000/initialize-bucket

# Test S3 operations
curl -X PUT http://localhost:8000/s3/test/hello.txt -d "Hello World"
curl http://localhost:8000/s3/test/hello.txt
```

### Database Access

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U s3gateway -d s3gateway

# View tables
\dt

# Check operations log
SELECT * FROM operations_log ORDER BY created_at DESC LIMIT 10;

# Check object replication status
SELECT object_key, current_replica_count, required_replica_count, sync_status 
FROM objects ORDER BY created_at DESC LIMIT 10;
```

## Data Sovereignty Features

The gateway includes several features for data sovereignty compliance:

1. **Provider Selection**: Automatically selects providers based on country requirements
2. **Metadata Tracking**: All operations logged with zone and provider information
3. **Region Restrictions**: Enforce data residency requirements through configuration
4. **Replica Management**: Track and verify data replicas across zones

### Current Configuration

The service is configured for Finnish data sovereignty:

```sql
-- Helsinki region providers
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint) VALUES
('Finland', 'Helsinki', 'FI-HEL-ST-1', 'Spacetime', 'hel1.your-objectstorage.com'),
('Finland', 'Helsinki', 'FI-HEL-UC-1', 'Upcloud', 'f969k.upcloudobjects.com'),
('Finland', 'Helsinki', 'FI-HEL-HZ-1', 'Hetzner', 's3c.tns.cx');
```

## Monitoring

- **Health Check**: `GET /health` with backend status
- **Operations Log**: View all S3 operations in the database
- **Replica Status**: Check object replication across zones
- **Provider Status**: Check available providers and their capabilities

## Troubleshooting

### Common Issues

1. **Backend Connection Failed**:
   ```bash
   curl http://localhost:8000/backends
   # Check S3 credentials in s3_backends.json
   ```

2. **Database Connection Failed**:
   ```bash
   docker-compose logs postgres
   docker-compose restart postgres
   ```

3. **Object Not Found**:
   ```bash
   # Check if object exists in metadata
   curl http://localhost:8000/api/operations/log
   ```

### Reset Services

```bash
# Stop all services
docker-compose down

# Remove volumes (clears database)
docker-compose down -v

# Rebuild and start
docker-compose up --build -d

# Initialize bucket
curl -X POST http://localhost:8000/initialize-bucket
```

## Security Features

- **Immutable Storage**: Objects cannot be modified once written
- **Versioning**: All object changes create new versions
- **Metadata Verification**: Database serves as authority for object existence
- **Multi-Zone Replication**: Data automatically replicated for durability
- **Operation Logging**: All operations tracked for audit trails

## Production Considerations

For production deployment, consider:

1. **Credentials Management**: Use proper secrets management for S3 credentials
2. **SSL/TLS**: Enable HTTPS for all endpoints
3. **Authentication**: Add proper S3 signature validation
4. **Load Balancing**: Distribute requests across multiple gateway instances
5. **Monitoring**: Add metrics collection and alerting
6. **Backup**: Regular database backups for metadata
7. **Performance**: Optimize database queries and connection pooling

## S3 Validation Features

The gateway includes comprehensive S3 RFC-compliant naming validation to prevent backend creation failures:

### Bucket Name Validation
- **Length**: 3-63 characters
- **Characters**: Lowercase letters, numbers, periods, and hyphens only
- **Format**: Must start and end with letter or number
- **Restrictions**: 
  - No consecutive periods (`..`)
  - No period-hyphen combinations (`.-` or `-.`)
  - No IP address format (`192.168.1.1`)
  - No forbidden prefixes (`xn--`) or suffixes (`-s3alias`, `--ol-s3`)

### Object Key Validation
- **Length**: Maximum 1024 bytes when UTF-8 encoded
- **Characters**: UTF-8 safe characters
- **Strict Mode**: Optional filtering of problematic characters (`&`, `$`, `@`, etc.)
- **Control Characters**: Rejected (except tab, newline, carriage return)

### Validation Modes
- **Standard Mode**: Warnings for problematic characters, errors for invalid ones
- **Strict Mode**: Rejects all potentially problematic characters
- **Regional Configuration**: Different regions can use different validation levels

### Testing Validation

```bash
# Test bucket and object validation
curl "http://localhost:8000/validation/test?bucket_name=test-bucket&object_key=file.txt"

# Test invalid bucket name (will be rejected)
curl -X PUT -H "X-Customer-ID: demo-customer" http://localhost:8000/s3/Invalid-Bucket-Name

# Test valid bucket name (will be redirected)  
curl -X PUT -H "X-Customer-ID: demo-customer" http://localhost:8000/s3/valid-bucket-name
```

## Bucket Hash Mapping

The gateway solves S3's global namespace collision problem using deterministic hash mapping. Since S3 bucket names must be globally unique across all providers and customers, multiple customers cannot use the same logical bucket name. Our hash mapping creates unique backend bucket names while preserving customer-facing logical names.

### How It Works

1. **Customer Request**: Customer requests bucket `"my-data"`
2. **Hash Generation**: System generates unique backend names:
   - Spacetime: `s3gw-a1b2c3d4e5f6789a-spacetim`
   - UpCloud: `s3gw-f9e8d7c6b5a43210-upcloud`
   - Hetzner: `s3gw-1a2b3c4d5e6f7890-hetzner`
3. **Database Storage**: Mapping stored in regional database
4. **Backend Creation**: Real buckets created with hashed names
5. **Customer Transparency**: Customer only sees `"my-data"`

### Hash Algorithm

```
Hash Input: customer_id:region_id:logical_name:backend_id:collision_counter
Algorithm: SHA-256
Format: s3gw-<16_chars_hash>-<backend_suffix>
```

### Benefits

- **Global Uniqueness**: No namespace collisions across customers or providers
- **Multi-Backend Replication**: Different bucket names on each backend
- **Customer Isolation**: Logical names remain private and collision-free
- **Deterministic**: Same input always produces same output
- **S3 Compliance**: Generated names follow S3 naming rules
- **Collision Avoidance**: Counter incremented on rare hash collisions

### Example Mapping

```json
{
  "customer_id": "company-abc",
  "logical_name": "backup-data",
  "backend_mapping": {
    "spacetime": "s3gw-7f3a2b1c9d8e6f45-spacetim",
    "upcloud": "s3gw-8d9c2a1b3f4e5678-upcloud",
    "hetzner": "s3gw-5e6f7a8b9c1d2345-hetzner"
  }
}
```

### Testing Bucket Mapping

```bash
# Test mapping generation (no storage)
curl -X POST "http://localhost:8000/api/bucket-mappings/test" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "test-customer",
    "region_id": "FI-HEL",
    "logical_name": "my-bucket"
  }'

# List customer bucket mappings
curl "http://localhost:8000/api/bucket-mappings/test-customer"

# Get specific bucket mapping
curl "http://localhost:8000/api/bucket-mappings/test-customer/my-bucket"

# Create bucket with mapping
curl -X PUT -H "X-Customer-ID: test-customer" \
  "http://localhost:8000/s3/my-bucket"
```

### Database Schema

Bucket mappings are stored in regional databases:

```sql
-- Main bucket mapping table
CREATE TABLE bucket_mappings (
    customer_id VARCHAR(100) NOT NULL,
    logical_name VARCHAR(63) NOT NULL,
    backend_mapping JSONB NOT NULL,
    region_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, logical_name)
);

-- Individual backend mappings for queries
CREATE TABLE backend_bucket_names (
    customer_id VARCHAR(100) NOT NULL,
    logical_name VARCHAR(63) NOT NULL,
    backend_id VARCHAR(50) NOT NULL,
    backend_name VARCHAR(63) NOT NULL,
    region_id VARCHAR(50) NOT NULL,
    UNIQUE(customer_id, logical_name, backend_id),
    UNIQUE(backend_id, backend_name)  -- Global uniqueness per backend
);
```

### Multi-Customer Example

Three customers can all use logical name "data-backup":

| Customer | Logical Name | Spacetime Backend | UpCloud Backend |
|----------|-------------|-------------------|-----------------|
| customer-1 | data-backup | s3gw-a1b2c3d4e5f6-spacetim | s3gw-f1e2d3c4b5a6-upcloud |
| customer-2 | data-backup | s3gw-b2c3d4e5f6a1-spacetim | s3gw-e2f3d4c5b6a1-upcloud |
| customer-3 | data-backup | s3gw-c3d4e5f6a1b2-spacetim | s3gw-d3e4f5c6a1b2-upcloud |

All backend names are globally unique while customers use identical logical names.

## Conclusion

You now have a complete S3 gateway with:

✅ **S3 RFC-compliant naming validation** - Prevents backend failures
✅ **Bucket hash mapping** - Solves S3 global namespace collisions
✅ **GDPR-compliant two-layer architecture** - HTTP redirects for data sovereignty  
✅ **Multi-regional support** - FI-HEL and DE-FRA regions
✅ **Multi-backend replication** - Unique bucket names per backend
✅ **Customer isolation** - Deterministic hashing with collision avoidance
✅ **Comprehensive validation** - Bucket names and object keys
✅ **Simple scripts** - `./start.sh` and `./test.sh` for easy operation
✅ **Single docker-compose.yml** - Simple deployment and management

Start testing with:
```bash
./start.sh
./test.sh
``` 