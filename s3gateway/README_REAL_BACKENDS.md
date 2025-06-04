# S3 Gateway with Real Backends

This enhanced S3 Gateway now supports real S3 backends instead of just mock responses. It can replicate data to multiple S3-compatible storage providers simultaneously.

## Features

- **Real S3 Integration**: Uses boto3 to interact with actual S3-compatible storage backends
- **Multi-Backend Replication**: Automatically uploads objects to all configured backends
- **Data Sovereignty**: Track which zones/providers store your data
- **Comprehensive Metadata**: PostgreSQL tracks all operations and replication status
- **Error Handling**: Graceful handling of backend failures with partial success support

## Setup Instructions

### 1. Configure S3 Backends

Edit the `config/s3_backends.json` file with your actual S3 credentials:

```json
{
  "backends": [
    {
      "name": "primary-s3",
      "provider": "AWS",
      "zone_code": "GE-FRAN-AWS-1",
      "region": "eu-central-1",
      "endpoint_url": null,
      "access_key": "YOUR_AWS_ACCESS_KEY",
      "secret_key": "YOUR_AWS_SECRET_KEY",
      "enabled": true,
      "is_primary": true
    },
    {
      "name": "backup-s3",
      "provider": "Wasabi",
      "zone_code": "NE-AMST-WASA-1",
      "region": "eu-central-1",
      "endpoint_url": "https://s3.eu-central-1.wasabisys.com",
      "access_key": "YOUR_WASABI_ACCESS_KEY",
      "secret_key": "YOUR_WASABI_SECRET_KEY",
      "enabled": true,
      "is_primary": false
    }
  ],
  "replication": {
    "enabled": true,
    "required_replicas": 2,
    "async_upload": false,
    "verify_uploads": true
  }
}
```

**Important**: Never commit real credentials to version control. Consider using environment variables or secrets management.

### 2. Supported S3 Providers

The gateway works with any S3-compatible storage:

- **AWS S3**: Set `endpoint_url` to `null`, specify correct region
- **Wasabi**: Use region-specific endpoints like `https://s3.eu-central-1.wasabisys.com`
- **DigitalOcean Spaces**: Use `https://fra1.digitaloceanspaces.com`
- **Linode Object Storage**: Use `https://eu-central-1.linodeobjects.com`
- **Backblaze B2**: Use S3-compatible API with region endpoints
- **MinIO**: Use your MinIO server endpoint

### 3. Start the Services

```bash
cd s3gateway
docker-compose up -d
```

The gateway will:
- Load your S3 backend configuration
- Initialize PostgreSQL database with metadata schema
- Start the S3-compatible API on port 8000

### 4. Verify Setup

Check that all backends are loaded:

```bash
curl http://localhost:8000/backends
```

Expected response:
```json
{
  "backends": [
    {
      "name": "primary-s3",
      "provider": "AWS",
      "zone_code": "GE-FRAN-AWS-1",
      "region": "eu-central-1",
      "enabled": true,
      "is_primary": true
    },
    {
      "name": "backup-s3",
      "provider": "Wasabi",
      "zone_code": "NE-AMST-WASA-1",
      "region": "eu-central-1",
      "enabled": true,
      "is_primary": false
    }
  ],
  "count": 2
}
```

## Usage Examples

### Create Bucket (creates in all backends)

```bash
curl -X PUT http://localhost:8000/my-test-bucket
```

The bucket will be created in both AWS and Wasabi simultaneously.

### Upload File (uploads to all backends)

```bash
curl -X PUT \
  -H "Content-Type: text/plain" \
  -d "Hello from S3 Gateway!" \
  http://localhost:8000/my-test-bucket/test-file.txt
```

The file will be uploaded to both backends with metadata tracking.

### Download File (tries primary first)

```bash
curl http://localhost:8000/my-test-bucket/test-file.txt
```

Downloads from the primary backend, falls back to other backends if primary fails.

### List Objects

```bash
curl http://localhost:8000/my-test-bucket
```

Returns XML list of objects from the primary backend.

## Monitoring and Management

### Check Replication Status

```bash
curl http://localhost:8000/api/replicas/status
```

Shows which objects are successfully replicated to all backends.

### View Operations Log

```bash
curl http://localhost:8000/api/operations/log
```

Shows detailed log of all S3 operations with backend information.

### Health Check

```bash
curl http://localhost:8000/health
```

Shows status of all configured backends.

## Data Flow

1. **Bucket Creation**: Creates bucket in all enabled backends
2. **Object Upload**: Uploads to all backends simultaneously 
3. **Metadata Storage**: Records operation details and replication status in PostgreSQL
4. **Object Download**: Tries primary backend first, falls back to others
5. **Error Handling**: Continues with partial success if some backends fail

## Error Handling

- **Partial Failures**: If upload succeeds to some but not all backends, operation is marked as successful
- **Complete Failures**: If upload fails to all backends, returns 500 error
- **Backend Unavailable**: Skips unavailable backends, continues with others
- **Credential Issues**: Logs detailed error messages for troubleshooting

## Response Headers

The gateway adds custom headers to track replication:

- `X-Backend-Count`: Number of successful operations
- `X-Backend-Zones`: Comma-separated list of zone codes used
- `X-Replication-Status`: "complete" or "partial"
- `X-Backend-Used`: Which backend served a GET request

## Security Considerations

1. **Credentials**: Store sensitive credentials securely, use environment variables
2. **Network**: Use HTTPS endpoints for production
3. **Access Control**: Configure backend IAM policies appropriately
4. **Monitoring**: Monitor failed operations and backend availability

## Troubleshooting

### Backend Connection Issues

Check logs:
```bash
docker logs s3gateway_service
```

Common issues:
- Wrong credentials
- Incorrect endpoint URLs
- Network connectivity
- Bucket already exists in different region

### Database Connection

Verify PostgreSQL is running:
```bash
docker logs s3gateway_postgres
```

### Configuration Errors

Validate JSON configuration:
```bash
python -m json.tool config/s3_backends.json
```

## Architecture

```
Client Request
     ↓
S3 Gateway (Port 8000)
     ↓
[Primary Backend] [Secondary Backend] [Tertiary Backend...]
     ↓
PostgreSQL Metadata Storage
```

The gateway provides a single S3-compatible interface while managing multiple real S3 backends behind the scenes, ensuring data sovereignty and redundancy. 