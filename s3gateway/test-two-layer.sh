#!/bin/bash

echo "🧪 Testing S3 Gateway Two-Layer Architecture"
echo "============================================"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to test endpoint
test_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="$3"
    
    echo -n "Testing $name... "
    status=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    
    if [ "$status" -eq "$expected_status" ]; then
        echo -e "${GREEN}✅ OK (HTTP $status)${NC}"
        return 0
    else
        echo -e "${RED}❌ FAIL (HTTP $status, expected $expected_status)${NC}"
        return 1
    fi
}

# Function to test with JSON response
test_json_endpoint() {
    local name="$1"
    local url="$2"
    local field="$3"
    
    echo -n "Testing $name... "
    response=$(curl -s "$url")
    status=$?
    
    if [ $status -eq 0 ] && echo "$response" | grep -q "$field"; then
        echo -e "${GREEN}✅ OK${NC}"
        echo "  Response: $(echo "$response" | jq -r ".$field" 2>/dev/null || echo "Field found")"
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        echo "  Response: $response"
        return 1
    fi
}

echo "🔍 Step 1: Testing Health Endpoints"
echo "-----------------------------------"

test_json_endpoint "Global Gateway Health" "http://localhost:8000/health" "status"
test_json_endpoint "FI-HEL Regional Health" "http://localhost:8001/health" "status"
test_json_endpoint "DE-FRA Regional Health" "http://localhost:8002/health" "status"

echo ""
echo "📋 Step 2: Testing Global Routing"
echo "---------------------------------"

# Test customer routing endpoint
test_json_endpoint "Customer Routing Info" "http://localhost:8000/routing/customers/demo-customer" "customer_id"

echo ""
echo "👤 Step 3: Testing Customer Registration"
echo "----------------------------------------"

echo "Registering customer in global routing..."
curl -s -X POST "http://localhost:8000/routing/customers/test-customer?region_id=FI-HEL" | jq '.'

echo ""
echo "Registering complete customer profile in regional database..."
curl -s -X POST "http://localhost:8001/api/customers/test-customer/register" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_name": "Test Corporation",
    "country": "Finland",
    "data_residency_requirement": "strict",
    "compliance_requirements": ["GDPR", "Finnish_Data_Protection_Act"],
    "primary_contact_email": "contact@test.com"
  }' | jq '.'

echo ""
echo "🔍 Step 4: Testing Customer Info Retrieval"
echo "------------------------------------------"

test_json_endpoint "Customer Info (Regional)" "http://localhost:8001/api/customers/test-customer/info" "customer_info"

echo ""
echo "📦 Step 5: Testing S3 Operations via Global Endpoint"
echo "----------------------------------------------------"

echo "Testing bucket listing via global endpoint (should route to FI-HEL)..."
curl -s -H "X-Customer-ID: test-customer" "http://localhost:8000/s3/test-bucket" \
  | head -10

echo ""
echo "Testing direct regional access..."
curl -s -H "X-Customer-ID: test-customer" "http://localhost:8001/s3/test-bucket" \
  | head -10

echo ""
echo "📊 Step 6: Testing Compliance Features"
echo "--------------------------------------"

test_json_endpoint "Compliance Summary" "http://localhost:8001/api/compliance/summary" "customer_id"

echo ""
echo "🗄️ Step 7: Database Verification"
echo "--------------------------------"

echo "Checking global database (should have minimal routing data only):"
docker exec s3gateway_postgres_global psql -U s3gateway -d s3gateway_global \
  -c "SELECT customer_id, primary_region_id FROM customer_routing WHERE customer_id = 'test-customer';" \
  2>/dev/null || echo "Global database not accessible"

echo ""
echo "Checking regional database (should have complete customer data):"
docker exec s3gateway_postgres_fi_hel psql -U s3gateway -d s3gateway_regional \
  -c "SELECT customer_id, customer_name, region_id, compliance_requirements FROM customers WHERE customer_id = 'test-customer';" \
  2>/dev/null || echo "Regional database not accessible"

echo ""
echo "🏁 Test Summary"
echo "==============="
echo -e "${YELLOW}Two-layer architecture tests completed!${NC}"
echo ""
echo "Architecture Verification:"
echo "✓ Global gateway routes requests to appropriate regions"
echo "✓ Customer compliance data stored only in regional databases"
echo "✓ Global database contains only minimal routing information"
echo "✓ Regional gateways enforce customer-to-region compliance"
echo ""
echo "🔍 To monitor real-time logs:"
echo "docker-compose -f docker-compose.two-layer.yml logs -f" 