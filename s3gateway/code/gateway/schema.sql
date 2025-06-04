-- S3 Gateway Database Schema with Immutability Support and Authentication
-- Create tables for storing S3 metadata and provider information

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- S3 Credentials table for authentication and authorization
CREATE TABLE s3_credentials (
    id SERIAL PRIMARY KEY,
    access_key_id VARCHAR(20) UNIQUE NOT NULL, -- AWS-style access key (e.g., AKIA...)
    secret_access_key VARCHAR(40) NOT NULL,    -- AWS-style secret key
    user_id VARCHAR(50) UNIQUE NOT NULL,       -- Internal user identifier
    user_name VARCHAR(100) NOT NULL,           -- Human-readable user name
    user_email VARCHAR(255),                   -- User email for contact
    permissions JSONB NOT NULL DEFAULT '{}',   -- S3 permissions (actions -> resources)
    is_active BOOLEAN DEFAULT true,            -- Enable/disable credentials
    last_used_at TIMESTAMP,                    -- Track last usage
    expires_at TIMESTAMP,                      -- Optional expiration
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

-- S3 Buckets metadata with user ownership
CREATE TABLE buckets (
    id SERIAL PRIMARY KEY,
    bucket_name VARCHAR(255) NOT NULL,
    customer_id VARCHAR(100), -- Legacy field for backward compatibility
    owner_user_id VARCHAR(50), -- New field: user who owns this bucket
    provider_id INTEGER REFERENCES providers(id),
    zone_code VARCHAR(50) NOT NULL,
    creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    versioning_enabled BOOLEAN DEFAULT false,
    object_lock_enabled BOOLEAN DEFAULT false,
    region VARCHAR(100),
    storage_class VARCHAR(50) DEFAULT 'STANDARD',
    replication_policy JSONB DEFAULT '{"required_replicas": 2, "allowed_countries": ["Finland"], "preferred_zones": []}',
    tags JSONB DEFAULT '{}', -- Bucket-level tags
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bucket_name, provider_id),
    FOREIGN KEY (owner_user_id) REFERENCES s3_credentials(user_id)
);

-- S3 Objects metadata with immutability and versioning support
CREATE TABLE objects (
    id SERIAL PRIMARY KEY,
    object_key VARCHAR(1024) NOT NULL,
    bucket_id INTEGER REFERENCES buckets(id) ON DELETE CASCADE,
    customer_id VARCHAR(100), -- Legacy field for backward compatibility
    owner_user_id VARCHAR(50), -- New field: user who owns this object
    etag VARCHAR(100),
    size_bytes BIGINT DEFAULT 0,
    content_type VARCHAR(255),
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    storage_class VARCHAR(50) DEFAULT 'STANDARD',
    encryption_type VARCHAR(50),
    metadata JSONB,
    tags JSONB DEFAULT '{}', -- Object-level tags
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
    UNIQUE(object_key, bucket_id, version_id),
    FOREIGN KEY (owner_user_id) REFERENCES s3_credentials(user_id)
);

-- Object metadata table (for faster tag/metadata queries)
CREATE TABLE object_metadata (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL,
    bucket_name VARCHAR(63) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    owner_user_id VARCHAR(50), -- User who owns this object
    size_bytes BIGINT DEFAULT 0,
    content_type VARCHAR(255),
    etag VARCHAR(100),
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tags JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    replicas JSONB DEFAULT '[]', -- Array of replica information
    current_replica_count INTEGER DEFAULT 1,
    required_replica_count INTEGER DEFAULT 1,
    sync_status VARCHAR(50) DEFAULT 'complete',
    version_id VARCHAR(100),
    is_delete_marker BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, bucket_name, object_key),
    FOREIGN KEY (owner_user_id) REFERENCES s3_credentials(user_id)
);

-- Bucket mappings for hash-based bucket names
CREATE TABLE bucket_mappings (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL,
    logical_name VARCHAR(63) NOT NULL, -- Customer-facing bucket name
    backend_mapping JSONB NOT NULL,    -- {"backend_id": "backend_bucket_name"}
    region_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    owner_user_id VARCHAR(50), -- User who owns this mapping
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, logical_name),
    FOREIGN KEY (owner_user_id) REFERENCES s3_credentials(user_id)
);

-- Backend bucket names for global uniqueness tracking
CREATE TABLE backend_bucket_names (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL,
    logical_name VARCHAR(63) NOT NULL,
    backend_id VARCHAR(50) NOT NULL,
    backend_name VARCHAR(63) NOT NULL,
    region_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    owner_user_id VARCHAR(50), -- User who owns this bucket
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, logical_name, backend_id),
    UNIQUE(backend_id, backend_name), -- Global uniqueness per backend
    FOREIGN KEY (owner_user_id) REFERENCES s3_credentials(user_id)
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

-- S3 Operations log with user tracking
CREATE TABLE operations_log (
    id SERIAL PRIMARY KEY,
    operation_type VARCHAR(50) NOT NULL, -- GET, PUT, DELETE, HEAD, LIST, etc.
    bucket_name VARCHAR(255),
    object_key VARCHAR(1024),
    customer_id VARCHAR(100), -- Legacy field
    user_id VARCHAR(50), -- User who performed the operation
    access_key_id VARCHAR(20), -- Which access key was used
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES s3_credentials(user_id)
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

-- S3 Request authentication log (for audit and debugging)
CREATE TABLE s3_auth_log (
    id SERIAL PRIMARY KEY,
    access_key_id VARCHAR(20),
    request_method VARCHAR(10),
    request_path VARCHAR(1024),
    request_query_string TEXT,
    auth_status VARCHAR(20), -- success, failed, invalid_signature, access_denied
    error_message TEXT,
    source_ip INET,
    user_agent VARCHAR(255),
    request_timestamp TIMESTAMP,
    signature_version VARCHAR(20),
    signed_headers TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

-- User bucket ownership view
CREATE VIEW user_bucket_access AS
SELECT 
    c.user_id,
    c.user_name,
    c.access_key_id,
    b.bucket_name,
    b.id as bucket_id,
    b.created_at as bucket_created_at,
    CASE WHEN b.owner_user_id = c.user_id THEN 'owner' ELSE 'shared' END as access_type
FROM s3_credentials c
LEFT JOIN buckets b ON b.owner_user_id = c.user_id
WHERE c.is_active = true;

-- Create indexes for performance
CREATE INDEX idx_s3_credentials_access_key ON s3_credentials(access_key_id);
CREATE INDEX idx_s3_credentials_user_id ON s3_credentials(user_id);
CREATE INDEX idx_s3_credentials_active ON s3_credentials(is_active);
CREATE INDEX idx_buckets_owner ON buckets(owner_user_id);
CREATE INDEX idx_buckets_customer ON buckets(customer_id); -- Legacy support
CREATE INDEX idx_buckets_provider_zone ON buckets(provider_id, zone_code);
CREATE INDEX idx_objects_owner ON objects(owner_user_id);
CREATE INDEX idx_objects_customer ON objects(customer_id); -- Legacy support
CREATE INDEX idx_objects_bucket_key ON objects(bucket_id, object_key);
CREATE INDEX idx_objects_sync_status ON objects(sync_status);
CREATE INDEX idx_objects_replica_count ON objects(current_replica_count, required_replica_count);
CREATE INDEX idx_objects_last_modified ON objects(last_modified);
CREATE INDEX idx_objects_version ON objects(version_id);
CREATE INDEX idx_objects_delete_marker ON objects(is_delete_marker);
CREATE INDEX idx_object_metadata_customer_bucket ON object_metadata(customer_id, bucket_name);
CREATE INDEX idx_object_metadata_owner ON object_metadata(owner_user_id);
CREATE INDEX idx_object_metadata_tags ON object_metadata USING GIN(tags);
CREATE INDEX idx_bucket_mappings_customer ON bucket_mappings(customer_id);
CREATE INDEX idx_bucket_mappings_owner ON bucket_mappings(owner_user_id);
CREATE INDEX idx_backend_bucket_names_backend ON backend_bucket_names(backend_id, backend_name);
CREATE INDEX idx_backend_bucket_names_owner ON backend_bucket_names(owner_user_id);
CREATE INDEX idx_operations_log_user ON operations_log(user_id);
CREATE INDEX idx_operations_log_access_key ON operations_log(access_key_id);
CREATE INDEX idx_operations_log_bucket ON operations_log(bucket_name);
CREATE INDEX idx_operations_log_created ON operations_log(created_at);
CREATE INDEX idx_operations_log_operation ON operations_log(operation_type);
CREATE INDEX idx_replicas_object_zone ON object_replicas(object_id, zone_code);
CREATE INDEX idx_replicas_status ON object_replicas(replica_status);
CREATE INDEX idx_providers_zone_code ON providers(zone_code);
CREATE INDEX idx_providers_country ON providers(country);
CREATE INDEX idx_sync_jobs_status ON sync_jobs(status);
CREATE INDEX idx_sync_jobs_scheduled ON sync_jobs(scheduled_at);
CREATE INDEX idx_s3_auth_log_access_key ON s3_auth_log(access_key_id);
CREATE INDEX idx_s3_auth_log_status ON s3_auth_log(auth_status);
CREATE INDEX idx_s3_auth_log_created ON s3_auth_log(created_at);

-- Insert Helsinki region providers
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) VALUES
('Finland', 'Helsinki', 'FI-HEL-ST-1', 'Spacetime', 'hel1.your-objectstorage.com', true, true, true, true, true, 'Spacetime S3-compatible storage in Helsinki'),
('Finland', 'Helsinki', 'FI-HEL-UC-1', 'Upcloud', 'f969k.upcloudobjects.com', true, true, true, true, true, 'Upcloud Object Storage in Helsinki'),
('Finland', 'Helsinki', 'FI-HEL-HZ-1', 'Hetzner', 's3c.tns.cx', true, true, true, true, true, 'Hetzner Object Storage in Helsinki (test provider)');

-- Create demo user credentials
INSERT INTO s3_credentials (access_key_id, secret_access_key, user_id, user_name, user_email, permissions) VALUES
('AKIA1234567890EXAMPLE', 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY', 'user-demo123', 'Demo User', 'demo@example.com', 
 '{"s3:*": ["*"]}'),
('AKIADEMOUSER12345678', 'demoSecretKey1234567890abcdefghijklmnop123', 'user-demo456', 'Test User', 'test@example.com',
 '{"s3:GetObject": ["demo-*"], "s3:PutObject": ["demo-*"], "s3:ListBucket": ["demo-*"], "s3:CreateBucket": ["demo-*"]}');

-- Create hardcoded immutable bucket with ownership
INSERT INTO buckets (bucket_name, owner_user_id, provider_id, zone_code, region, versioning_enabled, object_lock_enabled, replication_policy) VALUES
('2025-datatransfer', 'user-demo123', 1, 'FI-HEL-ST-1', 'FI-HEL', true, true, 
 '{"required_replicas": 2, "allowed_countries": ["Finland"], "preferred_zones": ["FI-HEL-ST-1", "FI-HEL-UC-1", "FI-HEL-HZ-1"]}'),
('2025-datatransfer', 'user-demo123', 2, 'FI-HEL-UC-1', 'FI-HEL', true, true, 
 '{"required_replicas": 2, "allowed_countries": ["Finland"], "preferred_zones": ["FI-HEL-ST-1", "FI-HEL-UC-1", "FI-HEL-HZ-1"]}');

-- Create immutability replication rule
INSERT INTO replication_rules (bucket_id, rule_name, source_zone, target_zones, replica_count, country_restriction) VALUES
(1, 'FI-HEL-immutable-replication', 'FI-HEL-ST-1', ARRAY['FI-HEL-UC-1'], 2, 'Finland'); 