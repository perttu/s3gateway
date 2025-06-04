#!/bin/bash

echo "🔒 GDPR Compliance Demonstration: Proxy vs Redirect"
echo "=================================================="

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo ""
echo -e "${BLUE}🎯 Scenario: Finnish customer accessing S3 data${NC}"
echo "Customer ID: finnish-customer-123"
echo "Expected region: FI-HEL (Finland)"
echo "Data sovereignty requirement: STRICT (data must not leave Finland)"
echo ""

echo "⚖️ GDPR Article 44: Transfers of personal data to third countries"
echo "Personal data cannot cross borders without adequate safeguards"
echo ""

# Function to test proxy approach (GDPR violation)
test_proxy_approach() {
    echo -e "${RED}❌ PROBLEMATIC: Proxy Approach (Current Implementation)${NC}"
    echo "----------------------------------------------------"
    echo ""
    echo "Flow:"
    echo "1. Customer (Finland) → Global Gateway (Unknown jurisdiction)"
    echo "2. Global Gateway sees full request including customer data"
    echo "3. Global Gateway → FI-HEL Regional Gateway"
    echo "4. FI-HEL processes request"
    echo "5. Response → Global Gateway → Customer"
    echo ""
    
    echo "🚨 GDPR Violations:"
    echo "• Customer data processed in unknown jurisdiction"
    echo "• IP addresses logged globally (Article 4(1) - personal data)"
    echo "• Request content visible to global gateway"
    echo "• Audit trail contaminated with cross-border data"
    echo ""
    
    echo "Example logs (GDPR problematic):"
    echo "Global gateway log:"
    echo '  {
    "customer_id": "finnish-customer-123",
    "source_ip": "192.168.1.100",          ← GDPR violation
    "user_agent": "aws-cli/2.0.1",         ← GDPR violation  
    "request_content": "/s3/sensitive-bucket/personal-data.pdf",  ← GDPR violation
    "request_headers": {...},              ← GDPR violation
    "timestamp": "2024-01-01T10:00:00Z"
  }'
    echo ""
    
    echo "🔍 Test with verbose curl (shows proxying):"
    echo "curl -v -H 'X-Customer-ID: finnish-customer' http://localhost:8000/s3/test-bucket"
    echo "→ Response comes directly from global gateway (data crossed borders)"
    echo ""
}

# Function to test redirect approach (GDPR compliant)
test_redirect_approach() {
    echo -e "${GREEN}✅ GDPR COMPLIANT: Redirect Approach${NC}"
    echo "-----------------------------------"
    echo ""
    echo "Flow:"
    echo "1. Customer (Finland) → Global Gateway (Minimal processing)"
    echo "2. Global Gateway determines region (NO customer data processing)"
    echo "3. Global Gateway → HTTP 307 Redirect to FI-HEL endpoint"
    echo "4. Customer → FI-HEL Regional Gateway (DIRECT connection)"
    echo "5. FI-HEL processes request and responds directly"
    echo ""
    
    echo "✅ GDPR Compliance:"
    echo "• No customer data processed globally"
    echo "• No IP addresses stored globally"
    echo "• Direct customer-to-region connection"
    echo "• Complete audit trail in correct jurisdiction"
    echo ""
    
    echo "Example logs (GDPR compliant):"
    echo "Global gateway log (minimal):"
    echo '  {
    "customer_id": "finnish-customer-123",  ← Just for routing
    "routed_to_region": "FI-HEL",          ← Operational info
    "routing_reason": "customer_region",    ← Operational info
    "timestamp": "2024-01-01T10:00:00Z"
    # NO IP, user agent, request content, or personal data
  }'
    echo ""
    echo "Regional gateway log (complete):"
    echo '  {
    "customer_id": "finnish-customer-123",
    "source_ip": "192.168.1.100",          ← OK - in Finnish jurisdiction
    "operation": "GetObject",
    "compliance_info": {
      "region_processed": "FI-HEL",
      "jurisdiction": "Finland",
      "gdpr_redirect": true,
      "cross_border_transfer": false
    }
  }'
    echo ""
    
    echo "🔍 Test with verbose curl (shows redirect):"
    echo "curl -v -H 'X-Customer-ID: finnish-customer' http://localhost:8000/s3/test-bucket"
    echo "→ HTTP 307 redirect to http://localhost:8001/s3/test-bucket"
    echo "→ Customer follows redirect DIRECTLY to FI-HEL (no global processing)"
    echo ""
}

# Function to demonstrate the actual behavior
demo_actual_behavior() {
    echo -e "${YELLOW}🧪 Live Demonstration${NC}"
    echo "--------------------"
    echo ""
    
    # Check if GDPR-compliant service is running
    echo "Checking if GDPR-compliant gateway is running..."
    if curl -s http://localhost:8000/health > /dev/null; then
        echo "✅ Service is running"
        echo ""
        
        echo "1. Testing global health (should show GDPR compliance):"
        curl -s http://localhost:8000/health | jq '.gdpr_compliant, .redirect_mode' 2>/dev/null || echo "Service running but response not JSON"
        echo ""
        
        echo "2. Testing routing info (minimal data only):"
        curl -s http://localhost:8000/routing/customers/finnish-customer | jq '.gdpr_compliance, .access_method' 2>/dev/null || echo "Response received"
        echo ""
        
        echo "3. Testing S3 request with verbose output (should show redirect):"
        echo "Command: curl -v -H 'X-Customer-ID: finnish-customer' http://localhost:8000/s3/test-bucket"
        echo ""
        response=$(curl -v -H 'X-Customer-ID: finnish-customer' http://localhost:8000/s3/test-bucket 2>&1)
        
        if echo "$response" | grep -q "HTTP/1.1 307"; then
            echo -e "${GREEN}✅ GDPR COMPLIANT: Request was redirected!${NC}"
            echo "Location header points to regional endpoint:"
            echo "$response" | grep -i "location:" || echo "Redirect detected"
        elif echo "$response" | grep -q "HTTP/1.1 200"; then
            echo -e "${RED}❌ GDPR VIOLATION: Request was proxied!${NC}"
            echo "Response came directly from global gateway"
        else
            echo "Service responded: $(echo "$response" | head -5)"
        fi
        echo ""
        
        echo "4. Testing compliance audit endpoints:"
        echo "Global compliance audit (should show minimal data):"
        curl -s http://localhost:8000/compliance/audit 2>/dev/null | jq '.gdpr_compliance' 2>/dev/null || echo "Audit endpoint available"
        echo ""
        
        echo "Regional compliance audit (should show complete data):"
        curl -s -H 'X-Customer-ID: finnish-customer' http://localhost:8001/api/compliance/audit 2>/dev/null | jq '.gdpr_compliance' 2>/dev/null || echo "Regional audit endpoint available"
        
    else
        echo -e "${YELLOW}⚠️  Service not running. Start with:${NC}"
        echo "docker-compose -f docker-compose.gdpr-compliant.yml up -d"
        echo ""
        echo "Then run this script again to see the live demonstration."
    fi
}

# Function to show database compliance
demo_database_compliance() {
    echo -e "${BLUE}🗄️ Database Compliance Verification${NC}"
    echo "-----------------------------------"
    echo ""
    
    echo "Global Database (should contain MINIMAL data only):"
    echo "Tables: providers, regions, customer_routing, routing_log"
    echo "What's included: provider info, region endpoints, customer-to-region mapping"
    echo "What's excluded: IP addresses, user agents, request details, compliance data"
    echo ""
    
    echo "Regional Database (contains ALL customer data in correct jurisdiction):"
    echo "Tables: customers, object_metadata, operations_log, compliance_events"
    echo "Includes: full customer profiles, audit trails, GDPR requests, compliance status"
    echo "Jurisdiction: Data stored in same region as customer (FI-HEL for Finnish customers)"
    echo ""
    
    echo "Verification commands:"
    echo "# Check global database (minimal data)"
    echo "docker exec s3gateway_postgres_global_gdpr psql -U s3gateway -d s3gateway_global -c \"SELECT customer_id, primary_region_id FROM customer_routing;\""
    echo ""
    echo "# Check regional database (complete data)"
    echo "docker exec s3gateway_postgres_fi_hel_gdpr psql -U s3gateway -d s3gateway_regional -c \"SELECT customer_id, customer_name, compliance_requirements FROM customers;\""
}

# Main execution
echo "This demonstration shows how to implement GDPR-compliant S3 gateway routing"
echo "to prevent personal data from crossing jurisdictional boundaries."
echo ""

test_proxy_approach
echo ""
test_redirect_approach
echo ""
demo_actual_behavior
echo ""
demo_database_compliance
echo ""

echo -e "${GREEN}🎯 Summary: GDPR Compliance Through HTTP Redirects${NC}"
echo "================================================="
echo ""
echo "✅ Benefits of Redirect Approach:"
echo "• Customer data stays in designated jurisdiction"
echo "• Global gateway processes no personal data"
echo "• Complete audit trails in correct region"
echo "• Transparent to S3 clients (they follow redirects automatically)"
echo "• Scalable to multiple regions"
echo ""
echo "🔧 Implementation:"
echo "• HTTP 307 redirects preserve request method and body"
echo "• Global database stores only routing assignments"
echo "• Regional databases store complete customer profiles"
echo "• GDPR compliance built into the architecture"
echo ""
echo "📚 Standards Compliance:"
echo "• GDPR Article 44 (international transfers)"
echo "• GDPR Article 5 (data minimization)"
echo "• GDPR Article 25 (data protection by design)"
echo "• GDPR Article 30 (records of processing activities)" 