# S3 Gateway Service

A dockerized S3-compatible gateway service with real S3 backend integration, data sovereignty support, versioning, and immutability features. Built using FastAPI and PostgreSQL for metadata storage.

## Features

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

6. **Bucket mapping demo:**
```bash
./demo-bucket-mapping.sh
```

## API Endpoints

### Gateway Management
- `GET /health` - Health check with backend status
- `GET /providers` - List available providers from CSV
- `GET /backends` - List configured S3 backends
- `GET /api/replicas/status` - Get object replication status
- `GET /api/operations/log` - View operations log

### S3-Compatible API (All with `/s3/` prefix)
- `GET /s3` - List buckets (shows logical names to customers)
- `PUT /s3/{bucket}` - Create bucket (creates hash-mapped backend buckets)
- `GET /s3/{bucket}` - List objects in bucket
- `GET /s3/{bucket}/{key}` - Get object
- `PUT /s3/{bucket}/{key}` - Put object
- `DELETE /s3/{bucket}/{key}` - Delete object

### Bucket Hash Mapping API
- `GET /api/bucket-mappings/{customer_id}` - List customer bucket mappings
- `GET /api/bucket-mappings/{customer_id}/{logical_name}` - Get specific bucket mapping
- `POST /api/bucket-mappings/test` - Test bucket mapping generation

### LocationConstraint API
- `GET /api/location-constraints/{customer_id}/{logical_name}` - Get bucket location policy
- `PUT /api/location-constraints/{customer_id}/{logical_name}/replica-count` - Update replica count
- `POST /api/location-constraints/test` - Test location constraint parsing
- `GET /api/location-constraints/available-locations` - List available regions and zones

### S3 Tagging API (S3-Compatible)
- `GET /s3/{bucket}?tagging` - Get bucket tags
- `PUT /s3/{bucket}?tagging` - Set bucket tags (triggers replica count changes)
- `DELETE /s3/{bucket}?tagging` - Delete bucket tags
- `GET /s3/{bucket}/{key}?tagging` - Get object tags
- `PUT /s3/{bucket}/{key}?tagging` - Set object tags (triggers replica count changes)
- `DELETE /s3/{bucket}/{key}?tagging` - Delete object tags

### Replication Queue API (Regional Gateway Only)
- `GET /api/replication/queue/status` - Get replication queue status
- `GET /api/replication/jobs/active` - List active replication jobs
- `GET /api/replication/jobs/{job_id}` - Get specific job status
- `DELETE /api/replication/jobs/{job_id}` - Cancel replication job
- `POST /api/replication/jobs/add-replica` - Schedule replica addition
- `POST /api/replication/jobs/remove-replica` - Schedule replica removal

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

2. **Create bucket:**
```bash
aws s3 mb s3://my-data-bucket --endpoint-url http://localhost:8080
```

3. **List buckets:**
```bash
aws s3 ls --endpoint-url http://localhost:8080
```

4. **Upload file:**
```bash
echo "Hello World" > test.txt
aws s3 cp test.txt s3://my-data-bucket/ --endpoint-url http://localhost:8080
```

5. **List objects:**
```bash
aws s3 ls s3://my-data-bucket/ --endpoint-url http://localhost:8080
```

### Using Direct API

1. **Create bucket:**
```bash
curl -X PUT -H "X-Customer-ID: my-company" "http://localhost:8000/s3/my-data-bucket"
```

2. **List buckets:**
```bash
curl -H "X-Customer-ID: my-company" "http://localhost:8000/s3"
```

3. **Upload object:**
```bash
curl -X PUT -H "X-Customer-ID: my-company" \
  -d "Hello World" "http://localhost:8000/s3/my-data-bucket/documents/test.txt"
```

4. **Get object:**
```bash
curl -H "X-Customer-ID: my-company" "http://localhost:8000/s3/my-data-bucket/documents/test.txt"
```

5. **List objects:**
```bash
curl -H "X-Customer-ID: my-company" "http://localhost:8000/s3/my-data-bucket"
```

### Check System Status

```bash
# Check health and backend status
curl "http://localhost:8000/health"

# List configured backends
curl "http://localhost:8000/backends"

# Test bucket mapping generation
curl -X POST "http://localhost:8000/api/bucket-mappings/test" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "test-customer", "region_id": "FI-HEL", "logical_name": "test-bucket"}'

# List customer bucket mappings
curl "http://localhost:8000/api/bucket-mappings/test-customer"

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

### Database Access

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U s3gateway -d s3gateway

# View tables
\dt

# Check operations log
SELECT * FROM operations_log ORDER BY created_at DESC LIMIT 10;

# Check bucket mappings
SELECT customer_id, logical_name, backend_mapping 
FROM bucket_mappings ORDER BY created_at DESC LIMIT 10;

# Check backend bucket names
SELECT customer_id, logical_name, backend_id, backend_name 
FROM backend_bucket_names ORDER BY created_at DESC LIMIT 10;

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

## S3 Tagging and Replication Management

The gateway supports full S3-compatible tagging with automatic replica count management through background queues. This enables non-blocking replication operations triggered by tag changes, including **efficient deletion when replica count is reduced**.

### How It Works

1. **S3-Compatible Tagging**: Standard S3 tagging API endpoints with XML payloads
2. **Tag-Based Replica Count**: Set `replica-count` tag to trigger replication changes
3. **Background Processing**: Replication jobs queued and processed by worker threads
4. **LocationConstraint Integration**: Respects allowed regions and priority order
5. **Non-Blocking Operations**: Tag operations return immediately, replication happens async
6. **Smart Deletion**: Efficient bulk deletion when replica count is reduced

### Deletion Capabilities

When replica count is reduced, the system provides comprehensive deletion:

✅ **Individual Object Deletion**: Removes specific objects from unused zones  
✅ **Bulk Bucket Deletion**: Deletes entire bucket replicas for cost optimization  
✅ **Backend Bucket Cleanup**: Removes empty backend buckets completely  
✅ **Database Metadata Updates**: Keeps metadata consistent with actual data  
✅ **Primary Region Protection**: Always preserves primary region data  
✅ **Smart Operation Selection**: Automatically chooses bulk vs individual operations  

### Tag-Based Replica Management

```bash
# Set replica count via object tags
curl -X PUT "http://localhost:8001/s3/my-bucket/my-file.txt?tagging" \
  -H "X-Customer-ID: demo-customer" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>3</Value>
      </Tag>
      <Tag>
        <Key>Environment</Key>
        <Value>production</Value>
      </Tag>
    </TagSet>
  </Tagging>'

# Reduce replica count (triggers efficient deletion)
curl -X PUT "http://localhost:8001/s3/my-bucket/my-file.txt?tagging" \
  -H "X-Customer-ID: demo-customer" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>1</Value>
      </Tag>
      <Tag>
        <Key>cost-optimization</Key>
        <Value>enabled</Value>
      </Tag>
    </TagSet>
  </Tagging>'

# Set replica count via bucket tags (affects all objects)
curl -X PUT "http://localhost:8001/s3/my-bucket?tagging" \
  -H "X-Customer-ID: demo-customer" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>2</Value>
      </Tag>
    </TagSet>
  </Tagging>'
```

### Replication Logic

Based on LocationConstraint and replica count:

```python
# Example LocationConstraint: "fi,de,fr"
regions = ['fi', 'de', 'fr']  # parsed from LocationConstraint
replica_count = 2             # from replica-count tag

# Active regions = first N regions
active_regions = regions[:replica_count]  # ['fi', 'de']
primary_region = regions[0]               # 'fi'
```

**Adding Replicas**: When `replica_count` increases:
- Add next region from allowed list
- Queue background job to copy data
- Update metadata when complete

**Removing Replicas**: When `replica_count` decreases:
- Remove last region from active list
- Queue background job to delete data (individual objects OR entire bucket)
- Always preserve primary region
- Clean up empty backend buckets

### Deletion Job Types

The system supports multiple deletion strategies:

1. **Individual Object Removal** (`REMOVE_REPLICA`):
   - Deletes specific objects from target zones
   - Used for small-scale operations
   - Preserves other objects in the bucket

2. **Bulk Bucket Deletion** (`DELETE_BUCKET_REPLICA`):
   - Deletes ALL objects from a bucket in target zone
   - Automatically used for buckets with many objects (>10)
   - Optionally deletes the empty backend bucket

3. **Empty Bucket Cleanup** (`CLEANUP_EMPTY_BUCKET`):
   - Removes completely empty backend buckets
   - Prevents storage costs for unused buckets
   - Updates database mapping status

### Smart Operation Selection

The system automatically chooses the most efficient approach:

```python
object_count = get_object_count_in_bucket(customer_id, bucket_name)

if object_count > 10:
    # Use bulk bucket deletion for efficiency
    schedule_bucket_replica_deletion(customer_id, bucket_name, zone)
else:
    # Use individual object deletion for precision
    for object_key in objects:
        schedule_replica_removal(customer_id, bucket_name, object_key, zone)
```

### Deletion Safety Features

- **Primary Region Protection**: Never deletes from the first region in LocationConstraint
- **Validation**: Ensures replica count doesn't go below 1
- **Atomic Operations**: Database updates only after successful deletion
- **Error Handling**: Failed deletions don't affect successful ones
- **Retry Logic**: Failed jobs automatically retried with exponential backoff

### Supported Tag Names

The system recognizes multiple tag names for replica count:
- `replica-count` (recommended)
- `replica_count`
- `replication-count`
- `replication_count`
- `replicas`
- `x-replica-count`

### Replication Queue System

#### Features
- **Thread-Safe**: Multiple worker threads process jobs concurrently
- **Priority-Based**: High-priority jobs (replica removal) processed first
- **Retry Logic**: Failed jobs automatically retried with exponential backoff
- **Job Tracking**: Monitor job status and completion
- **Database Integration**: Metadata updated atomically
- **Bulk Operations**: Efficient handling of large-scale deletions

#### Queue Operations

```bash
# Check queue status
curl "http://localhost:8001/api/replication/queue/status"

# List active jobs
curl "http://localhost:8001/api/replication/jobs/active"

# Check specific job
curl "http://localhost:8001/api/replication/jobs/{job_id}"

# Cancel queued job
curl -X DELETE "http://localhost:8001/api/replication/jobs/{job_id}"
```

#### Manual Job Scheduling

```bash
# Add replica manually
curl -X POST "http://localhost:8001/api/replication/jobs/add-replica" \
  -d "customer_id=demo-customer&bucket_name=my-bucket&object_key=file.txt&source_zone=fi-hel-st-1&target_zone=de-fra-st-1&priority=3"

# Remove replica manually  
curl -X POST "http://localhost:8001/api/replication/jobs/remove-replica" \
  -d "customer_id=demo-customer&bucket_name=my-bucket&object_key=file.txt&target_zone=fr-par-st-1&priority=7"

# Delete entire bucket replica (bulk operation)
curl -X POST "http://localhost:8001/api/replication/jobs/delete-bucket-replica" \
  -d "customer_id=demo-customer&bucket_name=my-bucket&target_zone=de-fra-st-1&priority=6"
```

### Integration Example

Complete workflow combining LocationConstraint and tag-based replication with deletion:

```bash
# 1. Create bucket with LocationConstraint
curl -X PUT "http://localhost:8000/s3/my-app-data" \
  -H "X-Customer-ID: my-company" \
  -H "Content-Type: application/xml" \
  -d '<CreateBucketConfiguration>
    <LocationConstraint>fi,de,fr</LocationConstraint>
  </CreateBucketConfiguration>'

# 2. Upload object (starts in primary region 'fi')
curl -X PUT "http://localhost:8001/s3/my-app-data/user-profile.json" \
  -H "X-Customer-ID: my-company" \
  -H "Content-Type: application/json" \
  -d '{"user_id": 12345, "name": "John Doe"}'

# 3. Set tags to replicate to 3 regions
curl -X PUT "http://localhost:8001/s3/my-app-data/user-profile.json?tagging" \
  -H "X-Customer-ID: my-company" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>3</Value>
      </Tag>
      <Tag>
        <Key>data-classification</Key>
        <Value>sensitive</Value>
      </Tag>
    </TagSet>
  </Tagging>'

# 4. Check replication job status
curl "http://localhost:8001/api/replication/jobs/active"

# 5. Later: reduce replicas to save costs (triggers deletion)
curl -X PUT "http://localhost:8001/s3/my-app-data/user-profile.json?tagging" \
  -H "X-Customer-ID: my-company" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>1</Value>
      </Tag>
      <Tag>
        <Key>cost-optimization</Key>
        <Value>enabled</Value>
      </Tag>
    </TagSet>
  </Tagging>'

# 6. Monitor deletion progress
curl "http://localhost:8001/api/replication/jobs/active"
```

### Cost Optimization Use Cases

**Scale Down for Cost Savings**:
```bash
# Reduce from 3 replicas to 1 (66% cost reduction)
# Deletes data from 'de' and 'fr', keeps 'fi'
replica-count: 3 → 1
```

**Temporary Scale Up**:
```bash
# Scale up for high availability during critical periods
replica-count: 1 → 3

# Scale back down after critical period
replica-count: 3 → 1
```

**Regional Compliance**:
```bash
# Move from multi-region to single region for compliance
LocationConstraint: "fi,de,fr" + replica-count: 3 → replica-count: 1
# Ensures data stays only in Finland
```

### Benefits

✅ **Non-Blocking**: Tag operations return immediately  
✅ **S3-Compatible**: Standard tagging API works with existing tools  
✅ **Automatic Replication**: Tag changes trigger background replication  
✅ **Efficient Deletion**: Bulk deletion for cost optimization  
✅ **Cost Control**: Reduce replicas by changing tags  
✅ **Compliance**: Respects LocationConstraint and data sovereignty  
✅ **Monitoring**: Full visibility into replication jobs  
✅ **Fault Tolerant**: Retry logic and error handling  
✅ **Scalable**: Multi-threaded processing with priority queues  
✅ **Smart Operations**: Automatic bulk vs individual operation selection  
✅ **Complete Cleanup**: Removes data AND backend infrastructure  

### Error Handling

The system provides robust error handling:

- **Tag Validation**: S3-compliant tag validation (keys ≤ 128 chars, values ≤ 256 chars)
- **Constraint Validation**: Replica count cannot exceed allowed regions
- **Job Retry**: Failed replication/deletion jobs automatically retried
- **Partial Failures**: Some replicas may succeed while others fail
- **Status Tracking**: Detailed job status and error messages
- **Deletion Safety**: Primary region always preserved
- **Backend Cleanup**: Empty buckets properly removed

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
✅ **Simple scripts** - `./start.sh` and `./test.sh` for easy operation
✅ **Single docker-compose.yml** - Simple deployment and management

Start testing with:
```bash
./start.sh
./test.sh
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