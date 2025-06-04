-- Add Helsinki region providers for the configured S3 backends

-- Spacetime provider (primary in FI-HEL)
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) 
VALUES 
('Finland', 'Helsinki', 'FI-HEL-ST-1', 'Spacetime', 'hel1.your-objectstorage.com', true, true, true, true, true, 'Spacetime S3-compatible storage in Helsinki')
ON CONFLICT (zone_code) DO UPDATE SET 
    provider_name = EXCLUDED.provider_name,
    endpoint = EXCLUDED.endpoint,
    updated_at = CURRENT_TIMESTAMP;

-- Upcloud provider (secondary in FI-HEL)
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) 
VALUES 
('Finland', 'Helsinki', 'FI-HEL-UC-1', 'Upcloud', 'f969k.upcloudobjects.com', true, true, true, true, true, 'Upcloud Object Storage in Helsinki')
ON CONFLICT (zone_code) DO UPDATE SET 
    provider_name = EXCLUDED.provider_name,
    endpoint = EXCLUDED.endpoint,
    updated_at = CURRENT_TIMESTAMP;

-- Hetzner provider (disabled, ready for testing in FI-HEL)
INSERT INTO providers (country, region_city, zone_code, provider_name, endpoint, s3_compatible, object_lock, versioning, iso_27001_gdpr, veeam_ready, notes) 
VALUES 
('Finland', 'Helsinki', 'FI-HEL-HZ-1', 'Hetzner', 's3c.tns.cx', true, true, true, true, true, 'Hetzner Object Storage in Helsinki (test provider)')
ON CONFLICT (zone_code) DO UPDATE SET 
    provider_name = EXCLUDED.provider_name,
    endpoint = EXCLUDED.endpoint,
    updated_at = CURRENT_TIMESTAMP; 