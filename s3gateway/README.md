# S3 Gateway Service

A dockerized S3-compatible gateway service with data sovereignty support, built using S3Proxy and PostgreSQL for metadata storage.

## Features

- **S3-Compatible API**: Mock S3 operations (GET, PUT, DELETE, LIST)
- **Data Sovereignty**: Provider selection based on country/region requirements
- **Metadata Storage**: PostgreSQL database for tracking operations and metadata
- **Provider Management**: Load and manage S3 providers from CSV data
- **Operation Logging**: Comprehensive logging of all S3 operations
- **Replication Rules**: Support for data replication based on sovereignty requirements

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   S3 Client     │    │  Gateway API    │    │   PostgreSQL    │
│                 │────│                 │────│                 │
│ (AWS CLI,       │    │  FastAPI +      │    │ Metadata Store  │
│  boto3, etc.)   │    │  Provider Logic │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              │
                       ┌─────────────────┐
                       │    S3Proxy      │
                       │                 │
                       │ (Local Storage) │
                       └─────────────────┘
```

## Directory Structure

```
s3gateway/
├── docker-compose.yml          # Main orchestration
├── config/
│   └── s3proxy.conf           # S3Proxy configuration
├── docker/
│   ├── s3proxy/
│   │   ├── Dockerfile         # S3Proxy container
│   │   └── s3proxy.conf       # S3Proxy config
│   └── gateway/
│       ├── Dockerfile         # Gateway service container
│       └── requirements.txt   # Python dependencies
├── code/
│   ├── db/
│   │   └── init.sql          # Database schema
│   └── gateway/
│       └── main.py           # FastAPI application
└── README.md
```

## Quick Start

1. **Start the services:**
```bash
cd s3gateway
docker-compose up -d
```

2. **Check service status:**
```bash
docker-compose ps
```

3. **View logs:**
```bash
docker-compose logs -f gateway
```

## API Endpoints

### Gateway Management
- `GET /health` - Health check
- `GET /providers` - List available providers
- `GET /sovereignty/check?country=Germany&replicas=3` - Check sovereignty compliance
- `GET /api/operations/log` - View operations log

### S3-Compatible API
- `GET /` - List buckets
- `GET /{bucket}` - List objects in bucket
- `PUT /{bucket}` - Create bucket
- `GET /{bucket}/{key}` - Get object
- `PUT /{bucket}/{key}` - Put object
- `DELETE /{bucket}/{key}` - Delete object

## Usage Examples

### Using AWS CLI

1. **Configure AWS CLI for local S3Proxy:**
```bash
aws configure set aws_access_key_id local-identity
aws configure set aws_secret_access_key local-credential
aws configure set default.region us-east-1
```

2. **List buckets:**
```bash
aws s3 ls --endpoint-url http://localhost:8080
```

3. **Create a bucket:**
```bash
aws s3 mb s3://test-bucket --endpoint-url http://localhost:8080
```

4. **Upload a file:**
```bash
echo "Hello World" > test.txt
aws s3 cp test.txt s3://test-bucket/ --endpoint-url http://localhost:8080
```

### Using curl

1. **List buckets:**
```bash
curl http://localhost:8000/
```

2. **Create bucket:**
```bash
curl -X PUT http://localhost:8000/my-bucket
```

3. **Upload object:**
```bash
curl -X PUT http://localhost:8000/my-bucket/test.txt -d "Hello World"
```

4. **Get object:**
```bash
curl http://localhost:8000/my-bucket/test.txt
```

### Check Data Sovereignty

```bash
# Check if Germany has enough providers for 3 replicas
curl "http://localhost:8000/sovereignty/check?country=Germany&replicas=3"

# List all available providers
curl "http://localhost:8000/providers"

# View operations log
curl "http://localhost:8000/api/operations/log"
```

## Database Schema

The service uses PostgreSQL to store:

- **Providers**: Available S3 providers and their capabilities
- **Buckets**: Bucket metadata and location information
- **Objects**: Object metadata and storage information
- **Operations Log**: All S3 operations for auditing
- **Replication Rules**: Data sovereignty and replication requirements
- **Object Replicas**: Tracking of object replicas across zones

## Configuration

### Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `S3PROXY_URL`: S3Proxy service URL
- `PROVIDERS_FILE`: Path to providers CSV file

### Provider Data

The service loads provider information from `providers_flat.csv` which contains:
- Zone codes and regions
- Provider capabilities (S3 compatibility, Object Lock, Versioning)
- Compliance information (ISO 27001, GDPR)
- Geographic location data

## Development

### Adding New Features

1. **New S3 Operations**: Add endpoints to `main.py`
2. **Database Schema**: Modify `init.sql` and restart services
3. **Provider Logic**: Update `select_provider_zone()` function

### Testing

```bash
# Start services
docker-compose up -d

# Check health
curl http://localhost:8000/health

# Run basic S3 operations
curl -X PUT http://localhost:8000/test-bucket
curl -X PUT http://localhost:8000/test-bucket/test.txt -d "test data"
curl http://localhost:8000/test-bucket/test.txt
```

### Database Access

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U s3gateway -d s3gateway

# View tables
\dt

# Check operations log
SELECT * FROM operations_log ORDER BY created_at DESC LIMIT 10;
```

## Data Sovereignty Features

The gateway includes several features for data sovereignty compliance:

1. **Provider Selection**: Automatically selects providers based on country requirements
2. **Replication Rules**: Configurable rules for data replication across zones
3. **Compliance Tracking**: Logs all operations with zone and provider information
4. **Region Restrictions**: Enforce data residency requirements

### Example Sovereignty Rules

```sql
-- Ensure data stays within EU
INSERT INTO replication_rules (bucket_id, rule_name, source_zone, target_zones, country_restriction) 
VALUES (1, 'EU-only', 'GE-FRAN-AWS-1', ARRAY['NE-AMST-WASA-1', 'FR-PARI-AWS-1'], 'EU');

-- German data must stay in Germany
INSERT INTO replication_rules (bucket_id, rule_name, source_zone, target_zones, country_restriction) 
VALUES (2, 'Germany-only', 'GE-FRAN-AWS-1', ARRAY['GE-MUN-CONT-1', 'GE-HAMB-IMPO-1'], 'Germany');
```

## Monitoring

- **Health Check**: `GET /health`
- **Operations Log**: View all S3 operations in the database
- **Provider Status**: Check available providers and their capabilities
- **Sovereignty Compliance**: Verify data placement rules

## Troubleshooting

### Common Issues

1. **Database Connection Failed**:
   ```bash
   docker-compose logs postgres
   docker-compose restart postgres
   ```

2. **S3Proxy Not Starting**:
   ```bash
   docker-compose logs s3proxy
   # Check if Java is available and configuration is correct
   ```

3. **Provider Data Not Loading**:
   ```bash
   # Ensure providers_flat.csv is in the parent directory
   ls -la ../providers_flat.csv
   ```

### Reset Services

```bash
# Stop all services
docker-compose down

# Remove volumes (clears database)
docker-compose down -v

# Rebuild and start
docker-compose up --build -d
```

## Next Steps

This is a mockup service. For production use, consider:

1. **Real S3 Backend Integration**: Replace mock responses with actual S3 calls
2. **Authentication**: Add proper S3 signature validation
3. **Load Balancing**: Distribute requests across multiple providers
4. **Encryption**: Add client-side and server-side encryption
5. **Monitoring**: Add metrics and alerting
6. **Performance**: Optimize database queries and caching 