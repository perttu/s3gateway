-- GDPR-Compliant Global S3 Gateway Database Schema
-- This database handles ONLY provider information and minimal routing
-- NO customer personal data, IP addresses, or sensitive information

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Global providers registry (all available providers across regions)
CREATE TABLE providers (
    provider_id VARCHAR(50) PRIMARY KEY, -- e.g., 'FI-HEL-ST-1'
    provider_name VARCHAR(100) NOT NULL,
    region VARCHAR(100) NOT NULL, -- e.g., 'FI-HEL', 'DE-FRA', 'US-EAST'
    country VARCHAR(100) NOT NULL,
    zone_code VARCHAR(50) UNIQUE NOT NULL, -- same as provider_id for compatibility
    endpoint_url VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active', -- active, maintenance, offline
    s3_compatible BOOLEAN DEFAULT false,
    object_lock BOOLEAN DEFAULT false,
    versioning BOOLEAN DEFAULT false,
    iso_27001_gdpr BOOLEAN DEFAULT false,
    veeam_ready BOOLEAN DEFAULT false,
    capabilities JSONB DEFAULT '{}', -- extensible capabilities
    health_check_url VARCHAR(255),
    last_health_check TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Regional endpoints/databases registry
CREATE TABLE regions (
    region_id VARCHAR(50) PRIMARY KEY, -- e.g., 'FI-HEL', 'DE-FRA'
    region_name VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    metadata_endpoint VARCHAR(255) NOT NULL, -- Regional database/API endpoint
    gateway_endpoint VARCHAR(255) NOT NULL, -- Regional gateway API endpoint
    status VARCHAR(50) DEFAULT 'active', -- active, maintenance, offline
    jurisdiction_info JSONB DEFAULT '{}', -- Basic jurisdiction info only (no customer data)
    primary_provider_id VARCHAR(50) REFERENCES providers(provider_id),
    backup_provider_ids VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- MINIMAL customer routing (NO compliance data - just region assignment)
-- Detailed customer compliance data MUST be stored in regional databases
CREATE TABLE customer_routing (
    customer_id VARCHAR(100) PRIMARY KEY,
    primary_region_id VARCHAR(50) REFERENCES regions(region_id),
    routing_notes TEXT, -- Non-sensitive routing notes only
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- GDPR-COMPLIANT routing log (minimal operational data only)
-- NO IP addresses, user agents, request details, or customer personal data
CREATE TABLE routing_log (
    id SERIAL PRIMARY KEY,
    customer_id VARCHAR(100), -- Just customer ID for operational tracking
    routed_to_region VARCHAR(50) REFERENCES regions(region_id),
    routing_reason VARCHAR(100), -- 'customer_region', 'default_region', 'load_balance'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- REMOVED for GDPR compliance:
    -- - source_ip (personal data)
    -- - user_agent (personal data)
    -- - requested_endpoint (may contain personal data)
    -- - request_id (operational but not needed for compliance)
);

-- Provider health monitoring (global operational data only)
CREATE TABLE provider_health (
    id SERIAL PRIMARY KEY,
    provider_id VARCHAR(50) REFERENCES providers(provider_id),
    health_status VARCHAR(50), -- healthy, degraded, unhealthy, unreachable
    response_time_ms INTEGER,
    error_message TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Global system configuration (non-customer specific)
CREATE TABLE system_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- GDPR compliance log (track compliance measures)
CREATE TABLE gdpr_compliance_log (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(100) NOT NULL, -- 'redirect_performed', 'data_minimization', 'audit_access'
    description TEXT,
    region_affected VARCHAR(50),
    compliance_measure VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX idx_providers_region ON providers(region);
CREATE INDEX idx_providers_country ON providers(country);
CREATE INDEX idx_providers_status ON providers(status);
CREATE INDEX idx_providers_zone_code ON providers(zone_code);
CREATE INDEX idx_regions_country ON regions(country);
CREATE INDEX idx_regions_status ON regions(status);
CREATE INDEX idx_customer_routing_customer ON customer_routing(customer_id);
CREATE INDEX idx_customer_routing_region ON customer_routing(primary_region_id);
CREATE INDEX idx_routing_log_customer ON routing_log(customer_id);
CREATE INDEX idx_routing_log_region ON routing_log(routed_to_region);
CREATE INDEX idx_routing_log_created ON routing_log(created_at);
CREATE INDEX idx_provider_health_provider ON provider_health(provider_id);
CREATE INDEX idx_provider_health_checked ON provider_health(checked_at);
CREATE INDEX idx_gdpr_compliance_log_created ON gdpr_compliance_log(created_at);

-- Insert Helsinki region configuration
INSERT INTO providers (provider_id, provider_name, region, country, zone_code, endpoint_url, status, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) VALUES
('FI-HEL-ST-1', 'Spacetime', 'FI-HEL', 'Finland', 'FI-HEL-ST-1', 'https://hel1.your-objectstorage.com', 'active', true, true, true, true, true, 'Spacetime S3-compatible storage in Helsinki'),
('FI-HEL-UC-1', 'Upcloud', 'FI-HEL', 'Finland', 'FI-HEL-UC-1', 'https://f969k.upcloudobjects.com', 'active', true, true, true, true, true, 'Upcloud Object Storage in Helsinki'),
('FI-HEL-HZ-1', 'Hetzner', 'FI-HEL', 'Finland', 'FI-HEL-HZ-1', 'https://s3c.tns.cx', 'active', true, true, true, true, true, 'Hetzner Object Storage in Helsinki (test provider)');

-- Insert German region providers
INSERT INTO providers (provider_id, provider_name, region, country, zone_code, endpoint_url, status, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) VALUES
('DE-FRA-AWS-1', 'AWS Frankfurt', 'DE-FRA', 'Germany', 'DE-FRA-AWS-1', 'https://s3.eu-central-1.amazonaws.com', 'active', true, true, true, true, true, 'AWS S3 Frankfurt region'),
('DE-FRA-WASA-1', 'Wasabi Frankfurt', 'DE-FRA', 'Germany', 'DE-FRA-WASA-1', 'https://s3.eu-central-1.wasabisys.com', 'active', true, true, true, true, true, 'Wasabi EU Central storage');

-- Insert regional endpoint configuration (NO customer compliance data)
INSERT INTO regions (region_id, region_name, country, metadata_endpoint, gateway_endpoint, primary_provider_id, backup_provider_ids, jurisdiction_info) VALUES
('FI-HEL', 'Helsinki', 'Finland', 
 'postgresql://s3gateway:s3gateway_pass@postgres-fi-hel:5432/s3gateway_regional', 
 'http://gateway-fi-hel:8000', 
 'FI-HEL-ST-1', 
 ARRAY['FI-HEL-UC-1', 'FI-HEL-HZ-1'],
 '{"jurisdiction": "Finland", "data_protection_laws": ["GDPR", "Finnish_Data_Protection_Act"]}');

INSERT INTO regions (region_id, region_name, country, metadata_endpoint, gateway_endpoint, primary_provider_id, backup_provider_ids, jurisdiction_info) VALUES
('DE-FRA', 'Frankfurt', 'Germany', 
 'postgresql://s3gateway:s3gateway_pass@postgres-de-fra:5432/s3gateway_regional', 
 'http://gateway-de-fra:8000', 
 'DE-FRA-AWS-1', 
 ARRAY['DE-FRA-WASA-1'],
 '{"jurisdiction": "Germany", "data_protection_laws": ["GDPR", "German_Federal_Data_Protection_Act"]}');

-- MINIMAL customer routing assignments (NO compliance details)
-- All detailed compliance data is stored in regional databases
INSERT INTO customer_routing (customer_id, primary_region_id, routing_notes) VALUES
('demo-customer', 'FI-HEL', 'Demo customer assigned to Finnish region'),
('acme-corp-fi', 'FI-HEL', 'Finnish entity routed to FI-HEL'),
('acme-corp-de', 'DE-FRA', 'German entity routed to DE-FRA');

-- System configuration
INSERT INTO system_config (config_key, config_value, description) VALUES
('default_region', '"FI-HEL"', 'Default region for new customers'),
('routing_strategy', '"strict_compliance"', 'Customer routing strategy'),
('gdpr_redirect_enabled', 'true', 'Enable GDPR-compliant HTTP redirects'),
('data_minimization', 'true', 'Enable data minimization in global logs');

-- GDPR compliance tracking
INSERT INTO gdpr_compliance_log (action_type, description, compliance_measure) VALUES
('data_minimization', 'Global database configured with minimal customer data', 'No IP addresses or personal data in global logs'),
('redirect_setup', 'HTTP redirects configured to prevent data crossing jurisdictions', 'Direct regional routing implemented'),
('audit_ready', 'Global database ready for GDPR compliance audits', 'Minimal data retention policy applied');

-- Views for operational queries (minimal data only)

-- Active providers by region
CREATE VIEW active_providers_by_region AS
SELECT 
    r.region_id,
    r.region_name,
    r.country,
    p.provider_id,
    p.provider_name,
    p.status,
    p.endpoint_url
FROM regions r
JOIN providers p ON p.region = r.region_id
WHERE p.status = 'active' AND r.status = 'active'
ORDER BY r.region_id, p.provider_name;

-- Customer routing information (minimal - no compliance details)
CREATE VIEW customer_routing_info AS
SELECT 
    cr.customer_id,
    cr.primary_region_id,
    r.region_name,
    r.country,
    r.gateway_endpoint,
    r.metadata_endpoint
FROM customer_routing cr
JOIN regions r ON cr.primary_region_id = r.region_id
WHERE r.status = 'active';

-- Regional health summary
CREATE VIEW regional_health_summary AS
SELECT 
    r.region_id,
    r.region_name,
    r.status as region_status,
    COUNT(p.provider_id) as total_providers,
    COUNT(CASE WHEN p.status = 'active' THEN 1 END) as active_providers,
    AVG(ph.response_time_ms) as avg_response_time
FROM regions r
LEFT JOIN providers p ON p.region = r.region_id
LEFT JOIN provider_health ph ON ph.provider_id = p.provider_id 
    AND ph.checked_at >= NOW() - INTERVAL '1 hour'
GROUP BY r.region_id, r.region_name, r.status
ORDER BY r.region_id;

-- GDPR compliance summary
CREATE VIEW gdpr_compliance_summary AS
SELECT 
    COUNT(CASE WHEN action_type = 'redirect_performed' THEN 1 END) as redirects_performed,
    COUNT(CASE WHEN action_type = 'data_minimization' THEN 1 END) as data_minimization_actions,
    COUNT(CASE WHEN action_type = 'audit_access' THEN 1 END) as audit_accesses,
    MAX(created_at) as last_compliance_action
FROM gdpr_compliance_log
WHERE created_at >= NOW() - INTERVAL '30 days'; 