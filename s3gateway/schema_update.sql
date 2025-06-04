-- Add missing columns for immutability and replication tracking

-- Add primary zone tracking
ALTER TABLE objects ADD COLUMN IF NOT EXISTS primary_zone_code VARCHAR(50);

-- Add replica zones array
ALTER TABLE objects ADD COLUMN IF NOT EXISTS replica_zones VARCHAR(50)[] DEFAULT ARRAY[]::VARCHAR[];

-- Add replica count tracking
ALTER TABLE objects ADD COLUMN IF NOT EXISTS required_replica_count INTEGER DEFAULT 2;
ALTER TABLE objects ADD COLUMN IF NOT EXISTS current_replica_count INTEGER DEFAULT 1;

-- Add sync status tracking
ALTER TABLE objects ADD COLUMN IF NOT EXISTS sync_status VARCHAR(50) DEFAULT 'pending';
ALTER TABLE objects ADD COLUMN IF NOT EXISTS last_sync_attempt TIMESTAMP;
ALTER TABLE objects ADD COLUMN IF NOT EXISTS sync_error_message TEXT;

-- Update existing NULL values to sensible defaults
UPDATE objects SET 
    primary_zone_code = 'FI-HEL-ST-1',
    replica_zones = ARRAY['FI-HEL-UC-1'],
    required_replica_count = 2,
    current_replica_count = 2,
    sync_status = 'complete'
WHERE primary_zone_code IS NULL; 