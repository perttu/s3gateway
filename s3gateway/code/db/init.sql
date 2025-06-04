-- S3 Gateway Database Schema
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
    replication_policy JSONB DEFAULT '{"required_replicas": 3, "allowed_countries": ["EU"], "preferred_zones": []}',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bucket_name, provider_id)
);

-- S3 Objects metadata with replica tracking
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
    -- Replication tracking fields
    primary_zone_code VARCHAR(50) NOT NULL,
    replica_zones VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR[],
    required_replica_count INTEGER DEFAULT 3,
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
    replica_count INTEGER DEFAULT 3,
    country_restriction VARCHAR(100), -- e.g., 'Germany', 'EU', 'Switzerland'
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
    ARRAY_AGG(or.zone_code ORDER BY or.zone_code) as active_zones,
    ARRAY_AGG(
        CASE WHEN or.replica_status = 'active' THEN or.zone_code ELSE NULL END
    ) FILTER (WHERE or.replica_status = 'active') as healthy_zones
FROM objects o
JOIN buckets b ON o.bucket_id = b.id
LEFT JOIN object_replicas or ON o.id = or.object_id
GROUP BY o.id, o.object_key, b.bucket_name, o.primary_zone_code, 
         o.required_replica_count, o.current_replica_count, 
         o.sync_status, o.last_sync_attempt;

-- Create indexes for performance
CREATE INDEX idx_buckets_provider_zone ON buckets(provider_id, zone_code);
CREATE INDEX idx_objects_bucket_key ON objects(bucket_id, object_key);
CREATE INDEX idx_objects_sync_status ON objects(sync_status);
CREATE INDEX idx_objects_replica_count ON objects(current_replica_count, required_replica_count);
CREATE INDEX idx_objects_last_modified ON objects(last_modified);
CREATE INDEX idx_operations_log_bucket ON operations_log(bucket_name);
CREATE INDEX idx_operations_log_created ON operations_log(created_at);
CREATE INDEX idx_operations_log_operation ON operations_log(operation_type);
CREATE INDEX idx_replicas_object_zone ON object_replicas(object_id, zone_code);
CREATE INDEX idx_replicas_status ON object_replicas(replica_status);
CREATE INDEX idx_providers_zone_code ON providers(zone_code);
CREATE INDEX idx_providers_country ON providers(country);
CREATE INDEX idx_sync_jobs_status ON sync_jobs(status);
CREATE INDEX idx_sync_jobs_scheduled ON sync_jobs(scheduled_at);

-- Insert sample provider data
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) VALUES
('Germany', 'Frankfurt', 'GE-FRAN-AWS-1', 'AWS', 's3.eu-central-1.amazonaws.com', true, true, true, true, true, 'Amazon S3 - Frankfurt region'),
('Netherlands', 'Amsterdam', 'NE-AMST-WASA-1', 'Wasabi', 's3.eu-central-1.wasabisys.com', true, true, true, true, true, 'Wasabi EU Central'),
('Switzerland', 'Zurich', 'SW-ZURI-AWS-1', 'AWS', 's3.eu-central-2.amazonaws.com', true, true, true, true, true, 'Amazon S3 - Zurich region'),
('France', 'Paris', 'FR-PARI-AWS-1', 'AWS', 's3.eu-west-3.amazonaws.com', true, true, true, true, true, 'Amazon S3 - Paris region');

-- Sample bucket with replication policy
INSERT INTO buckets (bucket_name, provider_id, zone_code, region, versioning_enabled, object_lock_enabled, replication_policy) VALUES
('test-bucket-eu', 1, 'GE-FRAN-AWS-1', 'eu-central-1', true, false, 
 '{"required_replicas": 3, "allowed_countries": ["Germany", "Netherlands", "Switzerland"], "preferred_zones": ["GE-FRAN-AWS-1", "NE-AMST-WASA-1", "SW-ZURI-AWS-1"]}');

-- Sample replication rule
INSERT INTO replication_rules (bucket_id, rule_name, source_zone, target_zones, replica_count, country_restriction) VALUES
(1, 'EU-only-replication', 'GE-FRAN-AWS-1', ARRAY['NE-AMST-WASA-1', 'SW-ZURI-AWS-1'], 3, 'EU');

-- Sample object with replication tracking
INSERT INTO objects (object_key, bucket_id, size_bytes, etag, content_type, primary_zone_code, replica_zones, required_replica_count, current_replica_count, sync_status) VALUES
('test-file.txt', 1, 1024, '"d41d8cd98f00b204e9800998ecf8427e"', 'text/plain', 'GE-FRAN-AWS-1', ARRAY['NE-AMST-WASA-1'], 3, 2, 'partial');

-- Sample replica entries
INSERT INTO object_replicas (object_id, zone_code, provider_id, replica_status, sync_time, checksum, size_bytes) VALUES
(1, 'GE-FRAN-AWS-1', 1, 'active', CURRENT_TIMESTAMP, 'd41d8cd98f00b204e9800998ecf8427e', 1024),
(1, 'NE-AMST-WASA-1', 2, 'active', CURRENT_TIMESTAMP, 'd41d8cd98f00b204e9800998ecf8427e', 1024);

-- Sample sync job for missing replica
INSERT INTO sync_jobs (object_id, source_zone_code, target_zone_code, job_type, status, priority) VALUES
(1, 'GE-FRAN-AWS-1', 'SW-ZURI-AWS-1', 'replicate', 'queued', 1); 