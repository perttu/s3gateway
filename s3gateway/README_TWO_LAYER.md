# Two-Layer S3 Gateway Architecture (Compliance-Correct)

This document describes the compliance-correct two-layer metadata architecture where ALL customer data and compliance information is stored in regional databases, with the global database containing only minimal routing information.

## Overview

The two-layer architecture separates concerns for compliance:

1. **Global Layer**: Minimal provider registry and customer routing assignments (NO compliance data)
2. **Regional Layer**: ALL customer data, compliance information, and operational data stored regionally

This ensures that customer compliance data never leaves their designated jurisdiction, mirroring how real-world compliance requirements work.

## Architecture Diagram

```
                          ┌─────────────────────┐
                          │   Global Endpoint   │
                          │   (Port 8000)       │
                          │                     │
                          │ - Provider Registry │
                          │ - Minimal Routing   │
                          │ - NO Customer Data  │
                          └──────────┬──────────┘
                                     │
                          ┌──────────┴──────────┐
                          │     Routing Logic   │
                          │  (Customer → Region)│
                          │   (Minimal Info)    │
                          └──────────┬──────────┘
                                     │
                     ┌───────────────┼───────────────┐
                     │               │               │
            ┌────────▼────────┐ ┌────▼─────┐ ┌──────▼──────┐
            │  FI-HEL Region  │ │ DE-FRA   │ │   US-EAST   │
            │   (Port 8001)   │ │(Port 8002)│ │ (Port 8003)│
            │                 │ │          │ │             │
            │ ALL Customer    │ │ALL       │ │ ALL Customer│
            │ Compliance Data │ │Customer  │ │ Compliance  │
            │ Object Metadata │ │Data      │ │ Data        │
            │ Operations Log  │ │Compliance│ │ Operations  │
            │ GDPR Requests   │ │Data      │ │ Log         │
            └─────────────────┘ └──────────┘ └─────────────┘
```

## Database Schema

### Global Database (`schema_global.sql`) - MINIMAL DATA ONLY

**Key Tables:**
- `providers` - All available storage providers (no customer data)
- `regions` - Regional endpoint configuration 
- `customer_routing` - MINIMAL customer-to-region assignment (no compliance details)
- `routing_log` - Basic routing audit (no sensitive data)

**What's NOT in Global Database:**
- ❌ Customer compliance requirements
- ❌ Data residency details
- ❌ Legal basis information
- ❌ Contact information
- ❌ Detailed audit logs

**Example:**
```sql
-- ONLY minimal routing assignment
INSERT INTO customer_routing (customer_id, primary_region_id, routing_notes) 
VALUES ('acme-corp', 'FI-HEL', 'Customer assigned to Finnish region');

-- Regional endpoint (no customer-specific compliance data)
INSERT INTO regions (region_id, gateway_endpoint, jurisdiction_info) 
VALUES ('FI-HEL', 'http://gateway-fi-hel:8000', '{"jurisdiction": "Finland"}');
```

### Regional Database (`schema_regional.sql`) - ALL CUSTOMER DATA

**Key Tables:**
- `customers` - Complete customer profiles with compliance requirements
- `object_metadata` - Customer objects with compliance status
- `buckets` - Customer buckets with regional policies
- `operations_log` - Detailed audit logs with compliance tracking
- `compliance_events` - Violations, reviews, legal holds
- `data_subject_requests` - GDPR Article 15-22 requests
- `compliance_rules` - Customer-specific compliance rules

**Example:**
```sql
-- Complete customer compliance profile stored regionally
INSERT INTO customers (customer_id, customer_name, region_id, data_residency_requirement, 
                      compliance_requirements, compliance_officer_email) 
VALUES ('acme-corp', 'Acme Corporation', 'FI-HEL', 'strict', 
        '["GDPR", "Finnish_Data_Protection_Act"]', 'gdpr@acme.fi');

-- Object with full compliance tracking
INSERT INTO object_metadata (customer_id, bucket_name, object_key, region_id, 
                           compliance_status, legal_hold, data_classification) 
VALUES ('acme-corp', 'documents', 'contract.pdf', 'FI-HEL', 
        'compliant', false, 'confidential');
```

## Deployment

### Using Docker Compose

```bash
# Start two-layer architecture
docker-compose -f docker-compose.two-layer.yml up -d

# Check services
docker-compose -f docker-compose.two-layer.yml ps
```

**Services:**
- `postgres-global` (Port 5432) - Minimal routing data
- `postgres-fi-hel` (Port 5433) - Finnish customer compliance data
- `postgres-de-fra` (Port 5434) - German customer compliance data
- `gateway-global` (Port 8000) - Global routing endpoint
- `gateway-fi-hel` (Port 8001) - FI-HEL regional endpoint
- `gateway-de-fra` (Port 8002) - DE-FRA regional endpoint

### Configuration

**Environment Variables:**

Global Gateway:
```bash
GATEWAY_TYPE=global
DATABASE_URL=postgresql://s3gateway:s3gateway_pass@postgres-global:5432/s3gateway_global
REGIONAL_ENDPOINTS={"FI-HEL": "http://gateway-fi-hel:8000", "DE-FRA": "http://gateway-de-fra:8000"}
```

Regional Gateway:
```bash
GATEWAY_TYPE=regional
REGION_ID=FI-HEL
DATABASE_URL=postgresql://s3gateway:s3gateway_pass@postgres-fi-hel:5432/s3gateway_regional
GLOBAL_DATABASE_URL=postgresql://s3gateway:s3gateway_pass@postgres-global:5432/s3gateway_global
```

## Usage Examples

### Customer Registration (Two-Step Process)

**Step 1: Register routing in global database**
```bash
curl -X POST http://localhost:8000/routing/customers/acme-corp?region_id=FI-HEL
```

**Step 2: Register complete compliance profile in regional database**
```bash
curl -X POST http://localhost:8001/api/customers/acme-corp/register \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "Acme Corporation",
    "country": "Finland",
    "data_residency_requirement": "strict",
    "compliance_requirements": ["GDPR", "Finnish_Data_Protection_Act"],
    "primary_contact_email": "contact@acme.fi",
    "compliance_officer_email": "gdpr@acme.fi"
  }'
```

### S3 Operations via Global Endpoint

The global endpoint automatically routes to the correct region:

```bash
# List objects (routed to customer's region automatically)
curl -H "X-Customer-ID: acme-corp" http://localhost:8000/s3/documents

# Upload object (stored in compliance region with full audit)
curl -X PUT -H "X-Customer-ID: acme-corp" \
  http://localhost:8000/s3/documents/contract.pdf \
  --data-binary @contract.pdf
```

### Direct Regional Access

For performance or detailed compliance operations:

```bash
# Direct access to FI-HEL region
curl -H "X-Customer-ID: acme-corp" http://localhost:8001/s3/documents

# Get complete customer compliance info (only available regionally)
curl http://localhost:8001/api/customers/acme-corp/info

# Get detailed compliance summary
curl -H "X-Customer-ID: acme-corp" http://localhost:8001/api/compliance/summary

# Get compliance alerts
curl -H "X-Customer-ID: acme-corp" http://localhost:8001/api/compliance/alerts
```

### Routing Information

```bash
# Check where customer requests are routed (minimal info only)
curl http://localhost:8000/routing/customers/acme-corp

# Response (minimal data):
{
  "customer_id": "acme-corp",
  "primary_region": "FI-HEL", 
  "regional_endpoint": "http://gateway-fi-hel:8000",
  "available_regions": ["FI-HEL", "DE-FRA"],
  "note": "Detailed compliance data is stored in regional database"
}
```

## Compliance Features

### Data Residency Enforcement

Customer compliance data is automatically segregated by region:

```sql
-- Finnish customers in FI-HEL database
SELECT customer_id, customer_name, compliance_requirements 
FROM customers 
WHERE region_id = 'FI-HEL' AND country = 'Finland';

-- German customers in DE-FRA database  
SELECT customer_id, customer_name, compliance_requirements 
FROM customers 
WHERE region_id = 'DE-FRA' AND country = 'Germany';
```

### Comprehensive Audit Trail

Each regional database maintains complete audit logs:

```sql
-- Detailed operations log in regional database
SELECT customer_id, operation_type, compliance_info, cross_border_transfer
FROM operations_log 
WHERE customer_id = 'acme-corp'
ORDER BY created_at DESC;

-- Compliance events tracking
SELECT event_type, severity, event_description, remediation_deadline
FROM compliance_events 
WHERE customer_id = 'acme-corp' AND resolved_at IS NULL;
```

### GDPR Data Subject Requests

Full GDPR compliance handled regionally:

```sql
-- Data subject requests processed regionally
SELECT request_type, status, response_deadline, affected_objects
FROM data_subject_requests 
WHERE customer_id = 'acme-corp' AND data_subject_id = 'john.doe@acme.fi';
```

### Compliance Monitoring

```bash
# Regional compliance dashboard
curl -H "X-Customer-ID: acme-corp" http://localhost:8001/api/compliance/summary

# Response (detailed compliance data):
{
  "customer_id": "acme-corp",
  "customer_name": "Acme Corporation",
  "region": "FI-HEL",
  "customer_compliance_status": "active",
  "data_residency_requirement": "strict",
  "compliance_requirements": ["GDPR", "Finnish_Data_Protection_Act"],
  "total_objects": 42,
  "compliant_objects": 42,
  "legal_hold_objects": 3,
  "open_violations": 0,
  "pending_data_requests": 1,
  "compliance_percentage": 100
}
```

## Compliance Verification

### Data Location Verification

```bash
# Verify Finnish customer data is in FI-HEL database only
docker exec -it s3gateway_postgres_fi_hel psql -U s3gateway -d s3gateway_regional \
  -c "SELECT customer_id, region_id, country FROM customers WHERE customer_id = 'acme-corp';"

# Verify no customer compliance data in global database
docker exec -it s3gateway_postgres_global psql -U s3gateway -d s3gateway_global \
  -c "SELECT customer_id, primary_region_id FROM customer_routing WHERE customer_id = 'acme-corp';"
```

### Cross-Border Transfer Monitoring

```sql
-- Monitor any cross-border data transfers
SELECT customer_id, operation_type, source_country, compliance_info
FROM operations_log 
WHERE cross_border_transfer = true
ORDER BY created_at DESC;
```

### Jurisdiction Compliance

```bash
# Finnish jurisdiction compliance check
curl http://localhost:8001/api/compliance/alerts

# German jurisdiction compliance check  
curl http://localhost:8002/api/compliance/alerts
```

## Migration from Single-Layer

### Step 1: Deploy Global Database (Minimal)

```bash
# Create global database with minimal schema
docker-compose -f docker-compose.two-layer.yml up postgres-global -d

# Migrate only provider and routing data (no customer compliance data)
docker exec -it s3gateway_postgres_global psql -U s3gateway -d s3gateway_global \
  -c "COPY providers FROM '/path/to/providers_only.csv' WITH CSV HEADER;"
```

### Step 2: Set Up Regional Databases

```bash
# Start regional databases
docker-compose -f docker-compose.two-layer.yml up postgres-fi-hel postgres-de-fra -d

# Migrate customer compliance data by region
# Finnish customers → FI-HEL database
# German customers → DE-FRA database
```

### Step 3: Deploy Gateways

```bash
# Start all gateways
docker-compose -f docker-compose.two-layer.yml up gateway-global gateway-fi-hel gateway-de-fra -d
```

### Step 4: Customer Re-registration

```bash
# Re-register customers in correct regional databases
curl -X POST http://localhost:8001/api/customers/finnish-customer/register \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Finnish Corp", "country": "Finland", ...}'

curl -X POST http://localhost:8002/api/customers/german-customer/register \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "German Corp", "country": "Germany", ...}'
```

## Security Considerations

### Data Segregation

- **Global Database**: Contains NO customer personal data or compliance information
- **Regional Databases**: Completely isolated by jurisdiction
- **Network Isolation**: Regional databases not accessible across regions

### Access Control

```bash
# Customers can only access their region's data
curl -H "X-Customer-ID: finnish-customer" http://localhost:8000/s3/bucket
# → Automatically routed to FI-HEL region

curl -H "X-Customer-ID: german-customer" http://localhost:8000/s3/bucket  
# → Automatically routed to DE-FRA region
```

### Compliance Validation

```bash
# Verify no cross-region data leakage
curl http://localhost:8001/api/compliance/validate/data-residency

# Audit jurisdiction compliance
curl http://localhost:8001/api/audit/jurisdiction-compliance
```

## Monitoring

### Health Checks

```bash
# Global gateway health (checks routing only)
curl http://localhost:8000/health

# Regional gateway health (includes customer count)
curl http://localhost:8001/health  # FI-HEL
curl http://localhost:8002/health  # DE-FRA
```

### Compliance Dashboards

```bash
# Finnish compliance dashboard
curl http://localhost:8001/api/compliance/alerts

# German compliance dashboard  
curl http://localhost:8002/api/compliance/alerts
```

## Troubleshooting

### Common Issues

1. **Customer Not Found in Region**
   ```bash
   # Check if customer is registered in correct regional database
   curl http://localhost:8001/api/customers/customer-id/info
   ```

2. **Routing Failures**
   ```bash
   # Check minimal routing assignment in global database
   docker exec -it s3gateway_postgres_global psql -U s3gateway -d s3gateway_global \
     -c "SELECT * FROM customer_routing WHERE customer_id = 'problematic-customer';"
   ```

3. **Compliance Data Missing**
   ```bash
   # Customer must be registered in regional database
   curl -X POST http://localhost:8001/api/customers/customer-id/register \
     -H "Content-Type: application/json" -d '{...}'
   ```

## Compliance Benefits

### ✅ **Correct Data Residency**
- Finnish customer data stays in Finnish database
- German customer data stays in German database
- No customer compliance data in global database

### ✅ **Jurisdiction Compliance**
- Each region operates under local data protection laws
- Complete audit trails maintained regionally
- GDPR requests processed in the correct jurisdiction

### ✅ **Scalable Architecture**
- Add new regions without affecting existing ones
- Independent compliance monitoring per region
- Regional-specific compliance rules and policies

### ✅ **Zero Cross-Border Data Leakage**
- Global database contains only routing assignments
- Regional databases completely isolated
- Compliance data never crosses jurisdictional boundaries

This corrected architecture ensures true compliance with data sovereignty requirements while maintaining the scalability and operational benefits of a distributed system. 