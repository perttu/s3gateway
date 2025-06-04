# S3 Service Discovery Demo - Bulletproof Protocol

This demo showcases the secure data ingest feature for the Bulletproof Protocol, allowing users to discover S3 buckets and files using their credentials without storing them on the server.

## Features

- 🔒 **Zero-Trust Security**: Credentials are only used for service discovery and never stored
- 🪣 **Bucket Discovery**: List all accessible S3 buckets with provided credentials
- 📁 **File Listing**: View all files in a bucket with size and metadata
- 💾 **Backend Storage**: Snapshots are saved as JSON files on the server for persistence
- 📊 **Metadata Viewer**: View stored snapshots and export discovered data for migration planning
- 🔄 **Version Support**: Discover object versions for S3 buckets with versioning enabled
- 🌐 **Multi-Provider Support**: Works with AWS S3, MinIO, Ceph, and other S3-compatible services
- 🎨 **Modern UI**: Clean, responsive interface with real-time updates
- 🐳 **Docker Support**: Easy deployment with Docker Compose

## Architecture

- **Frontend**: Vanilla JavaScript with modern CSS served by Nginx
- **Backend**: FastAPI (Python) for S3 service discovery
- **Security**: Credentials are passed through to boto3 client without storage
- **Containerization**: Both services run in Docker containers

## Prerequisites

- Docker and Docker Compose
- S3-compatible storage credentials

## Quick Start with Docker

### 1. Clone the repository

```bash
git clone <repository-url>
cd s3discovery
```

### 2. Start all services

```bash
docker-compose up
```

Or use the Makefile:
```bash
make up
```

### 3. Access the application

- Frontend: http://localhost:8080
- API Docs: http://localhost:8000/docs

## Development with Docker

### Using Docker Compose

```bash
# Build images
docker-compose build

# Start services in background
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Using Make commands

```bash
# Show all available commands
make help

# Start in development mode with hot reload
make dev

# View logs
make logs

# Open shell in backend container
make shell-backend

# Clean up containers and volumes
make clean
```

## Manual Installation (without Docker)

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the backend:
```bash
python main.py
```

### Frontend Setup

The frontend is static HTML/CSS/JS and can be served by any web server.

Option 1 - Using Python's built-in server:
```bash
cd frontend
python -m http.server 8080
```

Option 2 - Using Node.js (if installed):
```bash
cd frontend
npx http-server -p 8080
```

Option 3 - Open directly in browser:
Simply open `frontend/index.html` in your web browser.

## Usage

### Discovery Tab

1. **Enter S3 Credentials**:
   - Access Key: Your S3 access key
   - Secret Key: Your S3 secret key
   - Region: AWS region or "default" for custom S3 providers
   - Endpoint: S3 API endpoint (default: `https://s3c.tns.cx`)

2. **Discover Buckets**:
   - Click "Discover Buckets" to list all accessible buckets
   - The system will validate credentials and display available buckets
   - A snapshot is automatically saved to the backend server
   - The complete JSON data is displayed on screen

3. **View Files**:
   - Click on any bucket to view its contents
   - See file names, sizes, last modified dates, and ETags
   - Versioning status is shown if available

### Metadata Viewer Tab

1. **View Stored Snapshots**:
   - Switch to the "Metadata Viewer" tab
   - See all snapshots saved on the server
   - Each snapshot shows endpoint, timestamp, and statistics

2. **Explore Snapshot Details**:
   - Click on any snapshot to view full details
   - See complete JSON structure with all buckets and files

3. **Export for Migration**:
   - Click "Export JSON" to download snapshot data
   - Use exported data for migration planning or as input for replication jobs
   - Snapshots are stored in the `snapshots/` directory on the server

4. **Manage Snapshots**:
   - Delete individual snapshots as needed
   - All snapshots are persisted on the backend server

## Security Notes

- ✅ Credentials are **never stored** on the server
- ✅ All API calls are stateless
- ✅ Credentials are only used to create temporary boto3 clients
- ✅ HTTPS should be used in production
- ✅ CORS is configured for development (restrict in production)

## Supported S3 Providers

- AWS S3
- MinIO
- Ceph RGW
- Wasabi
- DigitalOcean Spaces
- Any S3-compatible storage

## API Endpoints

- `POST /discover/buckets` - List all buckets
- `POST /discover/bucket/{bucket_name}` - Get bucket details and file list
- `POST /discover/bucket/{bucket_name}/versions` - Get object versions (if versioning enabled)
- `POST /snapshot/save` - Save a discovery snapshot
- `GET /snapshot/list` - List all saved snapshots
- `GET /snapshot/{snapshot_id}` - Get a specific snapshot
- `DELETE /snapshot/{snapshot_id}` - Delete a snapshot
- `GET /health` - Health check

## Error Handling

The demo includes comprehensive error handling for:
- Invalid credentials
- Network errors
- Access denied scenarios
- Non-existent buckets
- S3 API errors

## Development

### Backend Development

The FastAPI backend supports hot-reload:
```bash
cd backend
uvicorn main:app --reload
```

### Frontend Development

Modify files in the `frontend/` directory and refresh your browser.

## License

Part of the Bulletproof Protocol project - ensuring data sovereignty and zero-trust security for federated storage networks. 