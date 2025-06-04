-- Regional S3 Gateway Database Schema
-- This database stores ALL customer data and compliance information in the same region as customer data
-- For compliance: ALL customer information, compliance data, and operational data stays regional

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Regional customer registry (ALL customer details and compliance data)
CREATE TABLE customers (
    customer_id VARCHAR(100) PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_type VARCHAR(50) DEFAULT 'enterprise', -- enterprise, individual, government
    region_id VARCHAR(50) NOT NULL, -- e.g., 'FI-HEL', 'DE-FRA'
    country VARCHAR(100) NOT NULL,
    -- Compliance and legal information
    data_residency_requirement VARCHAR(100) NOT NULL, -- 'strict', 'eu-only', 'flexible'
    compliance_requirements JSONB DEFAULT '[]', -- ["GDPR", "Finnish_Data_Act", "HIPAA"]
    retention_policy JSONB DEFAULT '{}', -- Data retention requirements
    legal_basis JSONB DEFAULT '{}', -- Legal basis for data processing
    data_classification VARCHAR(50) DEFAULT 'confidential', -- public, internal, confidential, restricted
    -- Contact and administrative
    primary_contact_email VARCHAR(255),
    compliance_officer_email VARCHAR(255),
    legal_entity_info JSONB DEFAULT '{}', -- Company registration, VAT, etc.
    -- Service configuration
    service_tier VARCHAR(50) DEFAULT 'standard', -- basic, standard, premium, enterprise
    allowed_regions VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR[], -- Additional allowed regions for this customer
    cross_region_replication BOOLEAN DEFAULT false,
    encryption_requirements JSONB DEFAULT '{"at_rest": true, "in_transit": true}',
    -- Compliance status and monitoring
    compliance_status VARCHAR(50) DEFAULT 'active', -- active, review_required, suspended, violation
    last_compliance_review TIMESTAMP,
    next_compliance_review TIMESTAMP,
    compliance_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Regional object metadata (lightweight, references global providers by provider_id)
CREATE TABLE object_metadata (
    object_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    bucket_name VARCHAR(255) NOT NULL,
    object_key VARCHAR(1024) NOT NULL,
    version_id VARCHAR(100) NOT NULL,
    etag VARCHAR(100),
    size_bytes BIGINT DEFAULT 0,
    content_type VARCHAR(255),
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    storage_class VARCHAR(50) DEFAULT 'STANDARD',
    encryption_type VARCHAR(50),
    is_delete_marker BOOLEAN DEFAULT false,
    -- Replica tracking (lightweight references to global providers)
    replicas JSONB NOT NULL DEFAULT '[]', -- [{"provider_id": "FI-HEL-ST-1", "status": "active", "version": "v1", "sync_time": "2024-01-01T00:00:00Z"}, ...]
    required_replica_count INTEGER DEFAULT 2,
    current_replica_count INTEGER DEFAULT 1,
    sync_status VARCHAR(50) DEFAULT 'pending', -- pending, syncing, complete, failed, partial
    last_sync_attempt TIMESTAMP,
    sync_error_message TEXT,
    -- Compliance and metadata (regional-specific)
    region_id VARCHAR(50) NOT NULL, -- e.g., 'FI-HEL'
    compliance_status VARCHAR(50) DEFAULT 'compliant', -- compliant, review_required, violation
    retention_until TIMESTAMP, -- for immutability/compliance
    legal_hold BOOLEAN DEFAULT false,
    legal_hold_reason TEXT,
    data_classification VARCHAR(50) DEFAULT 'confidential',
    access_log_retention_days INTEGER DEFAULT 2557, -- 7 years default
    tags JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, bucket_name, object_key, version_id)
);

-- Regional buckets (customer buckets in this region)
CREATE TABLE buckets (
    bucket_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    bucket_name VARCHAR(255) NOT NULL,
    region_id VARCHAR(50) NOT NULL,
    versioning_enabled BOOLEAN DEFAULT false,
    object_lock_enabled BOOLEAN DEFAULT false,
    encryption_enabled BOOLEAN DEFAULT true,
    encryption_algorithm VARCHAR(50) DEFAULT 'AES-256',
    replication_policy JSONB DEFAULT '{"required_replicas": 2, "allowed_providers": []}',
    compliance_config JSONB DEFAULT '{}', -- retention policies, legal hold settings
    access_policy JSONB DEFAULT '{}', -- IAM-style bucket policies
    lifecycle_policy JSONB DEFAULT '{}', -- Object lifecycle management
    notification_config JSONB DEFAULT '{}', -- Event notifications
    tags JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id, bucket_name)
);

-- Regional operations log (detailed audit for compliance within this region)
CREATE TABLE operations_log (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    operation_type VARCHAR(50) NOT NULL, -- GET, PUT, DELETE, HEAD, LIST, etc.
    bucket_name VARCHAR(255),
    object_key VARCHAR(1024),
    object_id UUID REFERENCES object_metadata(object_id),
    provider_used VARCHAR(50), -- provider_id from global registry
    request_id UUID DEFAULT uuid_generate_v4(),
    session_id VARCHAR(100), -- For tracking user sessions
    user_id VARCHAR(100), -- End user identifier
    user_agent VARCHAR(255),
    source_ip INET,
    source_country VARCHAR(100), -- Derived from IP for compliance monitoring
    status_code INTEGER,
    bytes_transferred BIGINT DEFAULT 0,
    response_time_ms INTEGER,
    error_message TEXT,
    request_headers JSONB,
    response_headers JSONB,
    -- Compliance-specific audit fields
    compliance_info JSONB DEFAULT '{}', -- audit trail for compliance
    data_subject_id VARCHAR(100), -- GDPR data subject identifier
    legal_basis VARCHAR(100), -- Legal basis for the operation
    purpose_of_processing TEXT, -- Why this operation was performed
    retention_applied BOOLEAN DEFAULT false,
    cross_border_transfer BOOLEAN DEFAULT false, -- If data crossed borders
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Compliance events and violations
CREATE TABLE compliance_events (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    event_type VARCHAR(50) NOT NULL, -- violation, review_required, legal_hold_applied, data_subject_request
    severity VARCHAR(50) DEFAULT 'medium', -- low, medium, high, critical
    event_description TEXT NOT NULL,
    affected_objects JSONB DEFAULT '[]', -- List of affected object IDs
    remediation_required BOOLEAN DEFAULT false,
    remediation_actions TEXT,
    remediation_deadline TIMESTAMP,
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),
    resolution_notes TEXT,
    regulatory_body VARCHAR(100), -- Which authority needs to be notified
    notification_required BOOLEAN DEFAULT false,
    notification_sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Data subject requests (GDPR Article 15-22)
CREATE TABLE data_subject_requests (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    data_subject_id VARCHAR(100) NOT NULL,
    request_type VARCHAR(50) NOT NULL, -- access, rectification, erasure, portability, restriction
    request_details TEXT,
    verification_status VARCHAR(50) DEFAULT 'pending', -- pending, verified, rejected
    verification_method VARCHAR(100),
    status VARCHAR(50) DEFAULT 'received', -- received, in_progress, completed, rejected
    response_deadline TIMESTAMP NOT NULL, -- Usually 30 days from receipt
    affected_objects JSONB DEFAULT '[]',
    processing_notes TEXT,
    response_data JSONB, -- For access requests
    completed_at TIMESTAMP,
    completed_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sync jobs for cross-region replication (within this region's scope)
CREATE TABLE sync_jobs (
    id SERIAL PRIMARY KEY,
    object_id UUID REFERENCES object_metadata(object_id) ON DELETE CASCADE,
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    source_provider_id VARCHAR(50) NOT NULL, -- global provider reference
    target_provider_id VARCHAR(50) NOT NULL, -- global provider reference
    job_type VARCHAR(50) NOT NULL, -- replicate, verify, delete, migrate
    priority INTEGER DEFAULT 5, -- 1=highest, 10=lowest
    status VARCHAR(50) DEFAULT 'queued', -- queued, running, completed, failed, cancelled
    compliance_reason VARCHAR(100), -- Why this sync is needed (compliance-driven)
    scheduled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    compliance_deadline TIMESTAMP, -- for compliance-driven operations
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customer access patterns (for optimization and compliance monitoring)
CREATE TABLE access_patterns (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
    object_id UUID REFERENCES object_metadata(object_id),
    access_type VARCHAR(50) NOT NULL, -- read, write, delete, list
    access_frequency INTEGER DEFAULT 1,
    last_access TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_location INET, -- for geo-compliance monitoring
    access_country VARCHAR(100), -- Derived from IP
    user_id VARCHAR(100),
    user_agent VARCHAR(255),
    unusual_access BOOLEAN DEFAULT false, -- Flagged by anomaly detection
    compliance_concern BOOLEAN DEFAULT false, -- Potential compliance issue
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Regional compliance configuration and rules
CREATE TABLE compliance_rules (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100) REFERENCES customers(customer_id), -- NULL for global rules
    rule_name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(50) NOT NULL, -- retention, access_control, encryption, cross_border
    rule_definition JSONB NOT NULL,
    enabled BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 5,
    effective_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    effective_until TIMESTAMP,
    created_by VARCHAR(100),
    approval_required BOOLEAN DEFAULT false,
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX idx_customers_customer_id ON customers(customer_id);
CREATE INDEX idx_customers_region ON customers(region_id);
CREATE INDEX idx_customers_country ON customers(country);
CREATE INDEX idx_customers_compliance_status ON customers(compliance_status);
CREATE INDEX idx_customers_compliance_review ON customers(next_compliance_review);

CREATE INDEX idx_object_metadata_customer ON object_metadata(customer_id);
CREATE INDEX idx_object_metadata_bucket ON object_metadata(customer_id, bucket_name);
CREATE INDEX idx_object_metadata_key ON object_metadata(customer_id, bucket_name, object_key);
CREATE INDEX idx_object_metadata_sync_status ON object_metadata(sync_status);
CREATE INDEX idx_object_metadata_created ON object_metadata(created_at);
CREATE INDEX idx_object_metadata_replica_count ON object_metadata(current_replica_count, required_replica_count);
CREATE INDEX idx_object_metadata_compliance ON object_metadata(compliance_status);
CREATE INDEX idx_object_metadata_region ON object_metadata(region_id);
CREATE INDEX idx_object_metadata_legal_hold ON object_metadata(legal_hold);
CREATE INDEX idx_object_metadata_retention ON object_metadata(retention_until);

CREATE INDEX idx_buckets_customer ON buckets(customer_id);
CREATE INDEX idx_buckets_customer_name ON buckets(customer_id, bucket_name);
CREATE INDEX idx_buckets_region ON buckets(region_id);

CREATE INDEX idx_operations_log_customer ON operations_log(customer_id);
CREATE INDEX idx_operations_log_bucket ON operations_log(customer_id, bucket_name);
CREATE INDEX idx_operations_log_created ON operations_log(created_at);
CREATE INDEX idx_operations_log_operation ON operations_log(operation_type);
CREATE INDEX idx_operations_log_status ON operations_log(status_code);
CREATE INDEX idx_operations_log_subject ON operations_log(data_subject_id);
CREATE INDEX idx_operations_log_cross_border ON operations_log(cross_border_transfer);

CREATE INDEX idx_compliance_events_customer ON compliance_events(customer_id);
CREATE INDEX idx_compliance_events_type ON compliance_events(event_type);
CREATE INDEX idx_compliance_events_severity ON compliance_events(severity);
CREATE INDEX idx_compliance_events_created ON compliance_events(created_at);
CREATE INDEX idx_compliance_events_deadline ON compliance_events(remediation_deadline);

CREATE INDEX idx_data_subject_requests_customer ON data_subject_requests(customer_id);
CREATE INDEX idx_data_subject_requests_subject ON data_subject_requests(data_subject_id);
CREATE INDEX idx_data_subject_requests_type ON data_subject_requests(request_type);
CREATE INDEX idx_data_subject_requests_deadline ON data_subject_requests(response_deadline);
CREATE INDEX idx_data_subject_requests_status ON data_subject_requests(status);

CREATE INDEX idx_sync_jobs_customer ON sync_jobs(customer_id);
CREATE INDEX idx_sync_jobs_status ON sync_jobs(status);
CREATE INDEX idx_sync_jobs_scheduled ON sync_jobs(scheduled_at);
CREATE INDEX idx_sync_jobs_object ON sync_jobs(object_id);
CREATE INDEX idx_sync_jobs_compliance_deadline ON sync_jobs(compliance_deadline);

CREATE INDEX idx_access_patterns_customer ON access_patterns(customer_id);
CREATE INDEX idx_access_patterns_object ON access_patterns(object_id);
CREATE INDEX idx_access_patterns_access ON access_patterns(last_access);
CREATE INDEX idx_access_patterns_unusual ON access_patterns(unusual_access);
CREATE INDEX idx_access_patterns_compliance ON access_patterns(compliance_concern);

CREATE INDEX idx_compliance_rules_customer ON compliance_rules(customer_id);
CREATE INDEX idx_compliance_rules_type ON compliance_rules(rule_type);
CREATE INDEX idx_compliance_rules_enabled ON compliance_rules(enabled);
CREATE INDEX idx_compliance_rules_effective ON compliance_rules(effective_from, effective_until);

-- Views for operational queries

-- Object replication status within this region
CREATE VIEW object_replication_status AS
SELECT 
    om.object_id,
    om.customer_id,
    c.customer_name,
    om.bucket_name,
    om.object_key,
    om.version_id,
    om.required_replica_count,
    om.current_replica_count,
    om.sync_status,
    om.region_id,
    om.compliance_status,
    om.legal_hold,
    CASE 
        WHEN om.current_replica_count < om.required_replica_count THEN 'needs_sync'
        WHEN om.current_replica_count = om.required_replica_count THEN 'complete'
        WHEN om.current_replica_count > om.required_replica_count THEN 'over_replicated'
    END as replication_status,
    om.replicas as replica_details,
    om.last_sync_attempt
FROM object_metadata om
JOIN customers c ON om.customer_id = c.customer_id
ORDER BY om.created_at DESC;

-- Customer compliance summary for this region
CREATE VIEW customer_compliance_summary AS
SELECT 
    c.customer_id,
    c.customer_name,
    c.region_id,
    c.compliance_status as customer_compliance_status,
    c.data_residency_requirement,
    c.compliance_requirements,
    COUNT(om.object_id) as total_objects,
    COUNT(CASE WHEN om.compliance_status = 'compliant' THEN 1 END) as compliant_objects,
    COUNT(CASE WHEN om.compliance_status = 'review_required' THEN 1 END) as review_required,
    COUNT(CASE WHEN om.compliance_status = 'violation' THEN 1 END) as violations,
    COUNT(CASE WHEN om.legal_hold = true THEN 1 END) as legal_hold_objects,
    COUNT(CASE WHEN om.sync_status != 'complete' THEN 1 END) as sync_pending,
    COUNT(CASE WHEN ce.event_type = 'violation' AND ce.resolved_at IS NULL THEN 1 END) as open_violations,
    COUNT(CASE WHEN dsr.status IN ('received', 'in_progress') THEN 1 END) as pending_data_requests,
    MAX(om.updated_at) as last_activity,
    c.next_compliance_review
FROM customers c
LEFT JOIN object_metadata om ON c.customer_id = om.customer_id
LEFT JOIN compliance_events ce ON c.customer_id = ce.customer_id
LEFT JOIN data_subject_requests dsr ON c.customer_id = dsr.customer_id
GROUP BY c.customer_id, c.customer_name, c.region_id, c.compliance_status, 
         c.data_residency_requirement, c.compliance_requirements, c.next_compliance_review
ORDER BY c.customer_id;

-- Recent operations summary for compliance monitoring
CREATE VIEW recent_operations_summary AS
SELECT 
    ol.customer_id,
    c.customer_name,
    ol.operation_type,
    COUNT(*) as operation_count,
    COUNT(CASE WHEN ol.cross_border_transfer = true THEN 1 END) as cross_border_operations,
    COUNT(CASE WHEN ol.status_code >= 400 THEN 1 END) as error_count,
    COUNT(DISTINCT ol.data_subject_id) as unique_data_subjects,
    AVG(ol.response_time_ms) as avg_response_time,
    SUM(ol.bytes_transferred) as total_bytes,
    MAX(ol.created_at) as last_operation
FROM operations_log ol
JOIN customers c ON ol.customer_id = c.customer_id
WHERE ol.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY ol.customer_id, c.customer_name, ol.operation_type
ORDER BY ol.customer_id, ol.operation_type;

-- Compliance alerts and pending actions
CREATE VIEW compliance_alerts AS
SELECT 
    'compliance_event' as alert_type,
    ce.customer_id,
    c.customer_name,
    ce.event_type as alert_category,
    ce.severity,
    ce.event_description as alert_message,
    ce.remediation_deadline as deadline,
    ce.created_at
FROM compliance_events ce
JOIN customers c ON ce.customer_id = c.customer_id
WHERE ce.resolved_at IS NULL

UNION ALL

SELECT 
    'data_subject_request' as alert_type,
    dsr.customer_id,
    c.customer_name,
    dsr.request_type as alert_category,
    'medium' as severity,
    'Data subject request: ' || dsr.request_type as alert_message,
    dsr.response_deadline as deadline,
    dsr.created_at
FROM data_subject_requests dsr
JOIN customers c ON dsr.customer_id = c.customer_id
WHERE dsr.status IN ('received', 'in_progress')

UNION ALL

SELECT 
    'compliance_review' as alert_type,
    c.customer_id,
    c.customer_name,
    'review_due' as alert_category,
    'low' as severity,
    'Compliance review due' as alert_message,
    c.next_compliance_review as deadline,
    c.updated_at as created_at
FROM customers c
WHERE c.next_compliance_review <= NOW() + INTERVAL '30 days'

ORDER BY deadline ASC, created_at DESC;

-- Example data for demo region (adjust based on region)
-- This would be inserted when the regional database is set up

-- Demo customers for this region
INSERT INTO customers (customer_id, customer_name, region_id, country, data_residency_requirement, compliance_requirements, primary_contact_email, compliance_officer_email, next_compliance_review) VALUES
('demo-customer', 'Demo Corporation', 'FI-HEL', 'Finland', 'strict', '["GDPR", "Finnish_Data_Protection_Act"]', 'contact@demo.com', 'compliance@demo.com', NOW() + INTERVAL '6 months'),
('acme-corp-fi', 'Acme Corp Finland', 'FI-HEL', 'Finland', 'strict', '["GDPR", "Finnish_Data_Protection_Act", "ISO_27001"]', 'contact@acme.fi', 'gdpr@acme.fi', NOW() + INTERVAL '3 months');

-- Demo bucket
INSERT INTO buckets (customer_id, bucket_name, region_id, versioning_enabled, object_lock_enabled, replication_policy) VALUES
('demo-customer', '2025-datatransfer', 'FI-HEL', true, true, 
 '{"required_replicas": 2, "allowed_providers": ["FI-HEL-ST-1", "FI-HEL-UC-1", "FI-HEL-HZ-1"]}');

-- Demo object
INSERT INTO object_metadata (customer_id, bucket_name, object_key, version_id, size_bytes, etag, content_type, region_id, replicas, required_replica_count, current_replica_count, sync_status) VALUES
('demo-customer', '2025-datatransfer', 'test-file.txt', 'v1-2024-01-01', 1024, '"d41d8cd98f00b204e9800998ecf8427e"', 'text/plain', 'FI-HEL',
 '[{"provider_id": "FI-HEL-ST-1", "status": "active", "version": "v1", "sync_time": "2024-01-01T00:00:00Z"}, {"provider_id": "FI-HEL-UC-1", "status": "active", "version": "v1", "sync_time": "2024-01-01T00:00:00Z"}]',
 2, 2, 'complete');

-- Demo compliance rule
INSERT INTO compliance_rules (customer_id, rule_name, rule_type, rule_definition, enabled) VALUES
('demo-customer', 'Finnish Data Residency', 'cross_border', 
 '{"max_cross_border_transfers": 0, "allowed_countries": ["Finland"], "require_explicit_consent": true}', 
 true); 