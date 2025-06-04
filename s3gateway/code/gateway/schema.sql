-- S3 Gateway Database Schema with Immutability Support
-- Create tables for storing S3 metadata and provider information

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Providers table (loaded from providers_flat.csv)
CREATE TABLE providers (
    id SERIAL PRIMARY KEY,
    country VARCHAR(100) NOT NULL,
    region_city VARCHAR(100) NOT NULL,
    zone_code VARCHAR(50) UNIQUE NOT NULL,
    provider_name VARCHAR(100) NOT NULL,
    endpoint VARCHAR(255),
    s3_compatible BOOLEAN DEFAULT false,
    object_lock BOOLEAN DEFAULT false,
    versioning BOOLEAN DEFAULT false,
    iso_27001_gdpr BOOLEAN DEFAULT false,
    veeam_ready BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- S3 Buckets metadata
CREATE TABLE buckets (
    id SERIAL PRIMARY KEY,
    bucket_name VARCHAR(255) NOT NULL,
    provider_id INTEGER REFERENCES providers(id),
    zone_code VARCHAR(50) NOT NULL,
    creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    versioning_enabled BOOLEAN DEFAULT false,
    object_lock_enabled BOOLEAN DEFAULT false,
    region VARCHAR(100),
    storage_class VARCHAR(50) DEFAULT 'STANDARD',
    replication_policy JSONB DEFAULT '{"required_replicas": 2, "allowed_countries": ["Finland"], "preferred_zones": []}',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bucket_name, provider_id)
);

-- S3 Objects metadata with immutability and versioning support
CREATE TABLE objects (
    id SERIAL PRIMARY KEY,
    object_key VARCHAR(1024) NOT NULL,
    bucket_id INTEGER REFERENCES buckets(id) ON DELETE CASCADE,
    etag VARCHAR(100),
    size_bytes BIGINT DEFAULT 0,
    content_type VARCHAR(255),
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    storage_class VARCHAR(50) DEFAULT 'STANDARD',
    encryption_type VARCHAR(50),
    metadata JSONB,
    tags JSONB,
    version_id VARCHAR(100),
    is_delete_marker BOOLEAN DEFAULT false,
    -- Immutability and replication tracking fields
    primary_zone_code VARCHAR(50) NOT NULL,
    replica_zones VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR[],
    required_replica_count INTEGER DEFAULT 2,
    current_replica_count INTEGER DEFAULT 1,
    sync_status VARCHAR(50) DEFAULT 'pending', -- pending, syncing, complete, failed, partial
    last_sync_attempt TIMESTAMP,
    sync_error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(object_key, bucket_id, version_id)
);

-- Object replicas tracking - detailed status for each zone
CREATE TABLE object_replicas (
    id SERIAL PRIMARY KEY,
    object_id INTEGER REFERENCES objects(id) ON DELETE CASCADE,
    zone_code VARCHAR(50) NOT NULL,
    provider_id INTEGER REFERENCES providers(id),
    replica_status VARCHAR(50) DEFAULT 'pending', -- pending, active, failed, deleted, syncing
    sync_time TIMESTAMP,
    checksum VARCHAR(100),
    size_bytes BIGINT DEFAULT 0,
    last_verified TIMESTAMP,
    sync_attempts INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(object_id, zone_code)
);

-- Sync jobs queue for managing data replication
CREATE TABLE sync_jobs (
    id SERIAL PRIMARY KEY,
    object_id INTEGER REFERENCES objects(id) ON DELETE CASCADE,
    source_zone_code VARCHAR(50) NOT NULL,
    target_zone_code VARCHAR(50) NOT NULL,
    job_type VARCHAR(50) NOT NULL, -- replicate, verify, delete
    priority INTEGER DEFAULT 5, -- 1=highest, 10=lowest
    status VARCHAR(50) DEFAULT 'queued', -- queued, running, completed, failed, cancelled
    scheduled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- S3 Operations log
CREATE TABLE operations_log (
    id SERIAL PRIMARY KEY,
    operation_type VARCHAR(50) NOT NULL, -- GET, PUT, DELETE, HEAD, LIST, etc.
    bucket_name VARCHAR(255),
    object_key VARCHAR(1024),
    provider_id INTEGER REFERENCES providers(id),
    zone_code VARCHAR(50),
    request_id UUID DEFAULT uuid_generate_v4(),
    user_agent VARCHAR(255),
    source_ip INET,
    status_code INTEGER,
    bytes_transferred BIGINT DEFAULT 0,
    response_time_ms INTEGER,
    error_message TEXT,
    request_headers JSONB,
    response_headers JSONB,
    replication_info JSONB, -- Track which zones were selected for the operation
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Replication rules for data sovereignty
CREATE TABLE replication_rules (
    id SERIAL PRIMARY KEY,
    bucket_id INTEGER REFERENCES buckets(id) ON DELETE CASCADE,
    rule_name VARCHAR(255) NOT NULL,
    source_zone VARCHAR(50) NOT NULL,
    target_zones VARCHAR(50)[] NOT NULL,
    replica_count INTEGER DEFAULT 2,
    country_restriction VARCHAR(100), -- e.g., 'Finland', 'EU', 'Switzerland'
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sync status summary view
CREATE VIEW sync_status_summary AS
SELECT 
    o.id as object_id,
    o.object_key,
    b.bucket_name,
    o.primary_zone_code,
    o.required_replica_count,
    o.current_replica_count,
    o.sync_status,
    o.last_sync_attempt,
    CASE 
        WHEN o.current_replica_count < o.required_replica_count THEN 'needs_sync'
        WHEN o.current_replica_count = o.required_replica_count THEN 'complete'
        WHEN o.current_replica_count > o.required_replica_count THEN 'over_replicated'
    END as replication_status,
    ARRAY_AGG(orep.zone_code ORDER BY orep.zone_code) as active_zones,
    ARRAY_AGG(
        CASE WHEN orep.replica_status = 'active' THEN orep.zone_code ELSE NULL END
    ) FILTER (WHERE orep.replica_status = 'active') as healthy_zones
FROM objects o
JOIN buckets b ON o.bucket_id = b.id
LEFT JOIN object_replicas orep ON o.id = orep.object_id
GROUP BY o.id, o.object_key, b.bucket_name, o.primary_zone_code, 
         o.required_replica_count, o.current_replica_count, 
         o.sync_status, o.last_sync_attempt;

-- Create indexes for performance
CREATE INDEX idx_buckets_provider_zone ON buckets(provider_id, zone_code);
CREATE INDEX idx_objects_bucket_key ON objects(bucket_id, object_key);
CREATE INDEX idx_objects_sync_status ON objects(sync_status);
CREATE INDEX idx_objects_replica_count ON objects(current_replica_count, required_replica_count);
CREATE INDEX idx_objects_last_modified ON objects(last_modified);
CREATE INDEX idx_objects_version ON objects(version_id);
CREATE INDEX idx_objects_delete_marker ON objects(is_delete_marker);
CREATE INDEX idx_operations_log_bucket ON operations_log(bucket_name);
CREATE INDEX idx_operations_log_created ON operations_log(created_at);
CREATE INDEX idx_operations_log_operation ON operations_log(operation_type);
CREATE INDEX idx_replicas_object_zone ON object_replicas(object_id, zone_code);
CREATE INDEX idx_replicas_status ON object_replicas(replica_status);
CREATE INDEX idx_providers_zone_code ON providers(zone_code);
CREATE INDEX idx_providers_country ON providers(country);
CREATE INDEX idx_sync_jobs_status ON sync_jobs(status);
CREATE INDEX idx_sync_jobs_scheduled ON sync_jobs(scheduled_at);

-- Insert Helsinki region providers
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) VALUES
('Finland', 'Helsinki', 'FI-HEL-ST-1', 'Spacetime', 'hel1.your-objectstorage.com', true, true, true, true, true, 'Spacetime S3-compatible storage in Helsinki'),
('Finland', 'Helsinki', 'FI-HEL-UC-1', 'Upcloud', 'f969k.upcloudobjects.com', true, true, true, true, true, 'Upcloud Object Storage in Helsinki'),
('Finland', 'Helsinki', 'FI-HEL-HZ-1', 'Hetzner', 's3c.tns.cx', true, true, true, true, true, 'Hetzner Object Storage in Helsinki (test provider)');

-- Create hardcoded immutable bucket
INSERT INTO buckets (bucket_name, provider_id, zone_code, region, versioning_enabled, object_lock_enabled, replication_policy) VALUES
('2025-datatransfer', 1, 'FI-HEL-ST-1', 'FI-HEL', true, true, 
 '{"required_replicas": 2, "allowed_countries": ["Finland"], "preferred_zones": ["FI-HEL-ST-1", "FI-HEL-UC-1", "FI-HEL-HZ-1"]}'),
('2025-datatransfer', 2, 'FI-HEL-UC-1', 'FI-HEL', true, true, 
 '{"required_replicas": 2, "allowed_countries": ["Finland"], "preferred_zones": ["FI-HEL-ST-1", "FI-HEL-UC-1", "FI-HEL-HZ-1"]}');

-- Create immutability replication rule
INSERT INTO replication_rules (bucket_id, rule_name, source_zone, target_zones, replica_count, country_restriction) VALUES
(1, 'FI-HEL-immutable-replication', 'FI-HEL-ST-1', ARRAY['FI-HEL-UC-1'], 2, 'Finland'); 