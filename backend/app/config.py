"""
Centralized configuration for the S3 discovery backend.

Environment variables let operators adjust CORS and snapshot throttling without
changing code. Documented defaults are safe for local development; production
deployments should override them in Docker/Compose.
"""
from pathlib import Path
import os

# Snapshot persistence
SNAPSHOTS_DIR = Path("snapshots")
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# CORS behaviour
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8080").split(",")
    if origin.strip()
]

# Snapshot throttling (defaults suit demos; override for production)
MAX_SNAPSHOT_BUCKETS = int(os.getenv("MAX_SNAPSHOT_BUCKETS", "200"))
MAX_SNAPSHOT_FILES = int(os.getenv("MAX_SNAPSHOT_FILES", "50000"))
MAX_FILES_PER_BUCKET = int(os.getenv("MAX_FILES_PER_BUCKET", "5000"))
