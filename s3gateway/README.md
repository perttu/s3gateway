# S3 Gateway Service

A dockerized S3-compatible gateway service with real S3 backend integration, data sovereignty support, versioning, and immutability features. Built using FastAPI and PostgreSQL for metadata storage.

## Features

- **Real S3 Backend Integration**: Connects to actual S3-compatible storage providers
- **S3-Compatible API**: Full S3 operations (GET, PUT, DELETE, LIST) with `/s3/` prefix
- **Data Sovereignty**: Provider selection based on country/region requirements
- **Versioning & Immutability**: Object versioning with immutable storage support
- **Metadata Authority**: PostgreSQL as single source of truth for object metadata
- **Provider Management**: Load and manage S3 providers from CSV and JSON configuration
- **Operation Logging**: Comprehensive logging of all S3 operations
- **Replication Management**: Multi-zone replication with real-time status tracking
- **Hardcoded Bucket Strategy**: All operations use a predefined bucket (`2025-datatransfer`)

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   S3 Client     │    │  Gateway API    │    │   PostgreSQL    │
│                 │────│                 │────│                 │
│ (AWS CLI,       │    │  FastAPI +      │    │ Metadata Store  │
│  boto3, etc.)   │    │  Real S3        │    │ (Authority)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
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
docker-compose up -d
```

2. **Initialize the hardcoded bucket:**
```bash
curl -X POST http://localhost:8000/initialize-bucket
```

3. **Check service status:**
```bash
docker-compose ps
curl http://localhost:8000/health
```

4. **View logs:**
```bash
docker-compose logs -f gateway
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

### Key Features

- **Metadata Authority**: PostgreSQL is the single source of truth
- **Versioning**: Each object upload gets a unique version ID
- **Immutability**: Objects are tracked as immutable with replica verification
- **Multi-Zone Replication**: Objects are replicated across multiple S3 backends

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