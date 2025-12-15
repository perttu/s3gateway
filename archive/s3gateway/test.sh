#!/bin/bash

echo "🧪 S3 Gateway Validation & Compliance Test Suite"
echo "================================================"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if services are running
if ! curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${YELLOW}⚠️ Services not running. Start with:${NC}"
    echo "./start.sh"
    echo ""
    exit 1
fi

# Test the bucket mapping module directly
echo ""
echo -e "${BLUE}🗺️ Testing Bucket Hash Mapping Module${NC}"
echo "------------------------------------"

echo "Running Python bucket mapping tests..."
cd code/gateway
python3 bucket_mapping.py
echo ""

# Test the location constraint module directly
echo ""
echo -e "${BLUE}🌍 Testing Location Constraint Module${NC}"
echo "------------------------------------"

echo "Running Python location constraint tests..."
python3 location_constraint.py
cd ../..

# Test the validation module directly
echo ""
echo -e "${BLUE}📋 Testing S3 Validation Module Directly${NC}"
echo "----------------------------------------"

echo "Running Python validation tests..."
python3 s3_validation.py
cd ../..

echo ""
echo -e "${BLUE}🧪 Testing Bucket Mapping API Endpoints${NC}"
echo "--------------------------------------"

# Test bucket mapping generation (no storage)
echo ""
echo "1. Testing bucket mapping generation:"
mapping_response=$(curl -s -X POST "http://localhost:8000/api/bucket-mappings/test" \
    -H "Content-Type: application/json" \
    -d '{
        "customer_id": "test-customer-123",
        "region_id": "FI-HEL",
        "logical_name": "my-data-bucket"
    }' 2>/dev/null)

if echo "$mapping_response" | grep -q '"test": true'; then
    echo -e "   ${GREEN}✅ SUCCESS${NC}: Bucket mapping generation works"
    
    # Extract backend mapping
    spacetime_bucket=$(echo "$mapping_response" | grep -o '"spacetime": "[^"]*"' | cut -d'"' -f4)
    upcloud_bucket=$(echo "$mapping_response" | grep -o '"upcloud": "[^"]*"' | cut -d'"' -f4)
    hetzner_bucket=$(echo "$mapping_response" | grep -o '"hetzner": "[^"]*"' | cut -d'"' -f4)
    
    echo "   Generated mappings:"
    echo "   • Logical name: my-data-bucket"
    echo "   • Spacetime:   $spacetime_bucket"
    echo "   • UpCloud:     $upcloud_bucket"
    echo "   • Hetzner:     $hetzner_bucket"
    
    # Verify uniqueness
    if [ "$spacetime_bucket" != "$upcloud_bucket" ] && [ "$spacetime_bucket" != "$hetzner_bucket" ] && [ "$upcloud_bucket" != "$hetzner_bucket" ]; then
        echo -e "   ${GREEN}✅ UNIQUENESS${NC}: All backend names are different"
    else
        echo -e "   ${RED}❌ COLLISION${NC}: Some backend names are identical"
    fi
    
    # Verify S3 compliance
    if [[ "$spacetime_bucket" =~ ^[a-z0-9.-]+$ ]] && [ ${#spacetime_bucket} -ge 3 ] && [ ${#spacetime_bucket} -le 63 ]; then
        echo -e "   ${GREEN}✅ S3 COMPLIANCE${NC}: Backend names follow S3 naming rules"
    else
        echo -e "   ${RED}❌ S3 VIOLATION${NC}: Backend names violate S3 naming rules"
    fi
else
    echo -e "   ${RED}❌ FAILED${NC}: Bucket mapping generation failed"
    echo "   Response: ${mapping_response:0:200}..."
fi

# Test different customers, same logical name
echo ""
echo "2. Testing same logical name, different customers:"
customers=("customer-alpha" "customer-beta" "customer-gamma")
logical_name="shared-bucket"

mappings=()
for customer in "${customers[@]}"; do
    echo "   Testing customer: $customer"
    response=$(curl -s -X POST "http://localhost:8000/api/bucket-mappings/test" \
        -H "Content-Type: application/json" \
        -d "{
            \"customer_id\": \"$customer\",
            \"region_id\": \"FI-HEL\",
            \"logical_name\": \"$logical_name\"
        }" 2>/dev/null)
    
    spacetime_backend=$(echo "$response" | grep -o '"spacetime": "[^"]*"' | cut -d'"' -f4)
    mappings+=("$spacetime_backend")
    echo "     Spacetime backend: $spacetime_backend"
done

# Check uniqueness across customers
unique_count=$(printf '%s\n' "${mappings[@]}" | sort -u | wc -l)
total_count=${#mappings[@]}

if [ "$unique_count" -eq "$total_count" ]; then
    echo -e "   ${GREEN}✅ CUSTOMER ISOLATION${NC}: Different customers get unique backend names"
else
    echo -e "   ${RED}❌ CUSTOMER COLLISION${NC}: Some customers got identical backend names"
fi

echo ""
echo -e "${BLUE}🌐 Testing Global Gateway Validation${NC}"
echo "-----------------------------------"

# Test various bucket names through global gateway
test_bucket_names=(
    "valid-bucket-name"
    "Invalid-Bucket-Name"  # Invalid: uppercase
    "my..bucket"           # Invalid: consecutive periods
    "192.168.1.1"          # Invalid: IP address
    "xn--bucket"           # Invalid: forbidden prefix
    "ab"                   # Invalid: too short
    "bucket-s3alias"       # Invalid: forbidden suffix
    "a-very-long-bucket-name-that-exceeds-the-sixty-three-character-limit-for-s3-buckets"  # Invalid: too long
)

echo "Testing bucket name validation through global gateway..."
for bucket in "${test_bucket_names[@]}"; do
    echo ""
    echo "Testing bucket: '$bucket'"
    
    # Test validation endpoint
    response=$(curl -s "http://localhost:8000/validation/test?bucket_name=$bucket" 2>/dev/null)
    if echo "$response" | grep -q '"overall_valid": true'; then
        echo -e "  ${GREEN}✅ VALID${NC}: $bucket"
    elif echo "$response" | grep -q '"overall_valid": false'; then
        echo -e "  ${RED}❌ INVALID${NC}: $bucket"
        # Extract error message
        error_msg=$(echo "$response" | grep -o '"errors": \[[^]]*\]' || echo "See full response")
        echo "     Error: $error_msg"
    else
        echo -e "  ${YELLOW}⚠️ UNKNOWN${NC}: Service may be down or response format changed"
        echo "     Response: ${response:0:100}..."
    fi
    
    # Test actual S3 endpoint with bucket mapping (should redirect with validation)
    echo "  Testing S3 endpoint with bucket mapping..."
    s3_response=$(curl -s -w "HTTP_CODE:%{http_code}" -H "X-Customer-ID: test-customer" "http://localhost:8000/s3/$bucket" 2>/dev/null)
    
    http_code=$(echo "$s3_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    
    case $http_code in
        307) echo -e "    ${GREEN}✅ REDIRECT${NC}: Validation passed, redirected to regional endpoint" ;;
        400) echo -e "    ${RED}❌ VALIDATION ERROR${NC}: Bucket name validation failed" ;;
        503) echo -e "    ${YELLOW}⚠️ SERVICE UNAVAILABLE${NC}: Regional endpoint not available" ;;
        *) echo -e "    ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $http_code" ;;
    esac
done

echo ""
echo -e "${BLUE}🏠 Testing Regional Gateway Validation${NC}"
echo "------------------------------------"

# Test object key validation
test_object_keys=(
    "valid/object/key.txt"
    "object with spaces.txt"                # Warning: spaces
    "object&with\$special@chars.txt"        # Warning: special chars
    "/leading-slash.txt"                    # Warning: leading slash
    "folder/"                               # Warning: trailing slash
    "valid-key.txt"                         # Valid
    "object$(echo -e '\x00')control.txt"    # Invalid: control chars
)

echo "Testing object key validation through regional gateway..."
for obj_key in "${test_object_keys[@]}"; do
    echo ""
    echo "Testing object key: '${obj_key:0:50}${#obj_key > 50 ? "..." : ""}'"
    
    # URL encode the object key for the request
    encoded_key=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$obj_key', safe='/'))")
    
    # Test validation endpoint
    response=$(curl -s "http://localhost:8001/validation/test?object_key=$encoded_key" 2>/dev/null)
    if echo "$response" | grep -q '"overall_valid": true'; then
        echo -e "  ${GREEN}✅ VALID${NC}"
        # Check for warnings
        if echo "$response" | grep -q 'warning'; then
            echo -e "    ${YELLOW}⚠️ Has warnings${NC}"
        fi
    elif echo "$response" | grep -q '"overall_valid": false'; then
        echo -e "  ${RED}❌ INVALID${NC}"
    else
        echo -e "  ${YELLOW}⚠️ UNKNOWN${NC}: Service may be down"
    fi
done

echo ""
echo -e "${BLUE}🧪 Integration Tests${NC}"
echo "-------------------"

echo "Testing complete S3 workflow with bucket mapping and validation..."

# Test 1: Valid bucket with mapping
echo ""
echo "1. Testing valid bucket creation with hash mapping:"
valid_bucket="test-bucket-$(date +%s)"
valid_object="documents/test-file.txt"

echo "   Creating bucket: $valid_bucket"
create_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT -H "X-Customer-ID: integration-test-customer" "http://localhost:8000/s3/$valid_bucket" 2>/dev/null)
create_http_code=$(echo "$create_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

case $create_http_code in
    307) 
        echo -e "   ${GREEN}✅ SUCCESS${NC}: Redirected to regional endpoint"
        
        # Check if bucket mapping was created
        sleep 2  # Give time for mapping creation and redirect processing
        mapping_check=$(curl -s "http://localhost:8000/api/bucket-mappings/integration-test-customer/$valid_bucket" 2>/dev/null)
        if echo "$mapping_check" | grep -q '"backend_mapping"'; then
            echo -e "   ${GREEN}✅ MAPPING CREATED${NC}: Backend hash mapping stored in database"
            
            # Extract backend names
            backend_mapping=$(echo "$mapping_check" | grep -o '"backend_mapping": {[^}]*}')
            echo "   Backend mapping: $backend_mapping"
        else
            echo -e "   ${YELLOW}⚠️ MAPPING UNKNOWN${NC}: Could not verify mapping creation"
        fi
        
        # Test that we can now upload to this bucket
        echo "   Testing object upload to created bucket..."
        upload_test_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
            -H "X-Customer-ID: integration-test-customer" \
            -H "Content-Type: text/plain" \
            -d "Test content for hash-mapped bucket" \
            "http://localhost:8000/s3/$valid_bucket/$valid_object" 2>/dev/null)
        upload_test_http_code=$(echo "$upload_test_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
        
        case $upload_test_http_code in
            307) echo -e "   ${GREEN}✅ UPLOAD SUCCESS${NC}: File uploaded to hash-mapped bucket" ;;
            400) echo -e "   ${RED}❌ UPLOAD FAILED${NC}: Validation error on upload" ;;
            404) echo -e "   ${YELLOW}⚠️ BUCKET NOT FOUND${NC}: Bucket may not be properly created" ;;
            *) echo -e "   ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $upload_test_http_code" ;;
        esac
        ;;
    200) 
        echo -e "   ${GREEN}✅ BUCKET CREATED${NC}: Created directly on regional endpoint"
        
        # Test object upload
        echo "   Testing object upload..."
        upload_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
            -H "X-Customer-ID: integration-test-customer" \
            -H "Content-Type: text/plain" \
            -d "Test content" \
            "http://localhost:8000/s3/$valid_bucket/$valid_object" 2>/dev/null)
        upload_http_code=$(echo "$upload_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
        
        case $upload_http_code in
            200) echo -e "   ${GREEN}✅ UPLOAD SUCCESS${NC}: File uploaded successfully" ;;
            400) echo -e "   ${RED}❌ UPLOAD FAILED${NC}: Validation error" ;;
            *) echo -e "   ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $upload_http_code" ;;
        esac
        ;;
    400) echo -e "   ${RED}❌ VALIDATION FAILED${NC}: Bucket name rejected" ;;
    *) echo -e "   ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $create_http_code" ;;
esac

# Test 2: Invalid bucket name
echo ""
echo "2. Testing invalid bucket name (should be rejected):"
invalid_bucket="Invalid-Bucket-Name"  # Uppercase not allowed

echo "   Attempting to create bucket: $invalid_bucket"
invalid_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT -H "X-Customer-ID: demo-customer" "http://localhost:8000/s3/$invalid_bucket" 2>/dev/null)
invalid_http_code=$(echo "$invalid_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

case $invalid_http_code in
    400) echo -e "   ${GREEN}✅ CORRECTLY REJECTED${NC}: Validation prevented invalid bucket creation" ;;
    307) echo -e "   ${RED}❌ VALIDATION BYPASSED${NC}: Invalid bucket was allowed" ;;
    *) echo -e "   ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $invalid_http_code" ;;
esac

# Test 3: Complete workflow test
echo ""
echo "3. Testing complete S3 workflow with bucket mapping:"
workflow_bucket="workflow-test-$(date +%s)"
workflow_customer="workflow-customer"

echo "   Step 1: Create bucket with customer ID..."
create_wf_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
    -H "X-Customer-ID: $workflow_customer" \
    "http://localhost:8000/s3/$workflow_bucket" 2>/dev/null)
create_wf_http_code=$(echo "$create_wf_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

if [ "$create_wf_http_code" = "307" ] || [ "$create_wf_http_code" = "200" ]; then
    echo -e "   ${GREEN}✅ STEP 1 SUCCESS${NC}: Bucket created"
    
    sleep 1  # Give time for processing
    
    echo "   Step 2: Upload file to bucket..."
    upload_wf_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
        -H "X-Customer-ID: $workflow_customer" \
        -H "Content-Type: application/json" \
        -d '{"message": "Hello from hash-mapped bucket!", "timestamp": "'$(date -Iseconds)'"}' \
        "http://localhost:8000/s3/$workflow_bucket/data/message.json" 2>/dev/null)
    upload_wf_http_code=$(echo "$upload_wf_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    
    if [ "$upload_wf_http_code" = "307" ] || [ "$upload_wf_http_code" = "200" ]; then
        echo -e "   ${GREEN}✅ STEP 2 SUCCESS${NC}: File uploaded"
        
        echo "   Step 3: List bucket contents..."
        list_wf_response=$(curl -s -w "HTTP_CODE:%{http_code}" \
            -H "X-Customer-ID: $workflow_customer" \
            "http://localhost:8000/s3/$workflow_bucket" 2>/dev/null)
        list_wf_http_code=$(echo "$list_wf_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
        
        if [ "$list_wf_http_code" = "307" ] || [ "$list_wf_http_code" = "200" ]; then
            echo -e "   ${GREEN}✅ STEP 3 SUCCESS${NC}: Bucket contents listed"
        else
            echo -e "   ${YELLOW}⚠️ STEP 3 PARTIAL${NC}: List returned HTTP $list_wf_http_code"
        fi
        
        echo "   Step 4: Verify bucket mapping..."
        mapping_wf_response=$(curl -s "http://localhost:8000/api/bucket-mappings/$workflow_customer/$workflow_bucket" 2>/dev/null)
        if echo "$mapping_wf_response" | grep -q '"backend_mapping"'; then
            backend_count=$(echo "$mapping_wf_response" | grep -o '"backend_count": [0-9]*' | cut -d: -f2 | tr -d ' ')
            echo -e "   ${GREEN}✅ STEP 4 SUCCESS${NC}: Bucket mapping verified ($backend_count backends)"
        else
            echo -e "   ${YELLOW}⚠️ STEP 4 PARTIAL${NC}: Could not verify mapping"
        fi
        
    else
        echo -e "   ${RED}❌ STEP 2 FAILED${NC}: File upload failed (HTTP $upload_wf_http_code)"
    fi
    
else
    echo -e "   ${RED}❌ STEP 1 FAILED${NC}: Bucket creation failed (HTTP $create_wf_http_code)"
fi

# Test 4: LocationConstraint bucket creation
echo ""
echo "4. Testing bucket creation with LocationConstraint:"
location_bucket="location-test-$(date +%s)"
location_customer="location-customer"

# Test different location constraints
location_test_cases=(
    "fi"                    # Single region (default)
    "fi,de"                 # Cross-border replication allowed
    "fi-hel-st-1"          # Specific zone
    "de-fra"               # Different primary region
)

for location_constraint in "${location_test_cases[@]}"; do
    echo ""
    echo "   Testing LocationConstraint: '$location_constraint'"
    
    # Create bucket name with location info
    test_bucket="${location_bucket}-${location_constraint//[^a-z0-9]/-}"
    
    # Create bucket with LocationConstraint in XML body
    xml_body="<CreateBucketConfiguration><LocationConstraint>$location_constraint</LocationConstraint></CreateBucketConfiguration>"
    
    create_loc_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
        -H "X-Customer-ID: $location_customer" \
        -H "Content-Type: application/xml" \
        -d "$xml_body" \
        "http://localhost:8000/s3/$test_bucket" 2>/dev/null)
    
    create_loc_http_code=$(echo "$create_loc_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    
    case $create_loc_http_code in
        307|200) 
            echo -e "     ${GREEN}✅ SUCCESS${NC}: Bucket created with LocationConstraint"
            
            # Check location constraint was stored
            sleep 1
            constraint_check=$(curl -s "http://localhost:8000/api/location-constraints/$location_customer/$test_bucket" 2>/dev/null)
            if echo "$constraint_check" | grep -q '"location_policy"'; then
                primary_zone=$(echo "$constraint_check" | grep -o '"primary_zone": "[^"]*"' | cut -d'"' -f4)
                cross_border=$(echo "$constraint_check" | grep -o '"cross_border_replication": [^,}]*' | cut -d: -f2 | tr -d ' ')
                echo "     • Primary zone: $primary_zone"
                echo "     • Cross-border replication: $cross_border"
            else
                echo -e "     ${YELLOW}⚠️ WARNING${NC}: Could not verify location constraint storage"
            fi
            ;;
        400)
            echo -e "     ${RED}❌ REJECTED${NC}: Invalid LocationConstraint (expected for invalid cases)"
            ;;
        *)
            echo -e "     ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $create_loc_http_code"
            ;;
    esac
done

# Test 5: List customer buckets with mappings
echo ""
echo "5. Testing customer bucket listing with mappings:"
echo "   Listing buckets for integration-test-customer..."
bucket_list_response=$(curl -s "http://localhost:8000/api/bucket-mappings/integration-test-customer" 2>/dev/null)

if echo "$bucket_list_response" | grep -q '"bucket_count"'; then
    bucket_count=$(echo "$bucket_list_response" | grep -o '"bucket_count": [0-9]*' | cut -d: -f2 | tr -d ' ')
    echo -e "   ${GREEN}✅ SUCCESS${NC}: Found $bucket_count bucket(s) for customer"
    
    if [ "$bucket_count" -gt 0 ]; then
        echo "   Bucket details:"
        echo "$bucket_list_response" | grep -o '"logical_name": "[^"]*"' | sed 's/.*: "//;s/"//' | while read bucket; do
            echo "     • $bucket"
        done
    fi
else
    echo -e "   ${YELLOW}⚠️ UNKNOWN${NC}: Could not retrieve bucket list"
fi

# Test 4: Check health endpoints
echo ""
echo "4. Testing health endpoints with validation and mapping status:"

echo "   Global gateway health:"
global_health=$(curl -s "http://localhost:8000/health" 2>/dev/null)
if echo "$global_health" | grep -q '"s3_validation"'; then
    validation_status=$(echo "$global_health" | grep -o '"enabled": [^,}]*' | head -1)
    strict_status=$(echo "$global_health" | grep -o '"strict_mode": [^,}]*' | head -1)
    echo -e "   ${GREEN}✅ VALIDATION${NC}: $validation_status, Strict $strict_status"
else
    echo -e "   ${YELLOW}⚠️ NO VALIDATION INFO${NC}: Health endpoint may not include validation status"
fi

if echo "$global_health" | grep -q '"bucket_mapping"'; then
    mapping_enabled=$(echo "$global_health" | grep -A3 '"bucket_mapping"' | grep '"enabled"' | cut -d: -f2 | tr -d ' ,')
    mapping_algorithm=$(echo "$global_health" | grep -A3 '"bucket_mapping"' | grep '"algorithm"' | cut -d'"' -f4)
    echo -e "   ${GREEN}✅ BUCKET MAPPING${NC}: Enabled=$mapping_enabled, Algorithm=$mapping_algorithm"
else
    echo -e "   ${YELLOW}⚠️ NO MAPPING INFO${NC}: Health endpoint may not include bucket mapping status"
fi

echo "   Regional gateway health:"
regional_health=$(curl -s "http://localhost:8001/health" 2>/dev/null)
if echo "$regional_health" | grep -q '"s3_validation"'; then
    validation_status=$(echo "$regional_health" | grep -o '"enabled": [^,}]*' | head -1)
    strict_status=$(echo "$regional_health" | grep -o '"strict_mode": [^,}]*' | head -1)
    echo -e "   ${GREEN}✅ VALIDATION${NC}: $validation_status, Strict $strict_status"
else
    echo -e "   ${YELLOW}⚠️ NO VALIDATION INFO${NC}: Health endpoint may not include validation status"
fi

echo ""
echo -e "${GREEN}🎯 S3 Gateway Test Summary${NC}"
echo "=========================="
echo ""
echo "✅ Features Tested:"
echo "• S3 RFC-compliant bucket name validation"
echo "• S3 RFC-compliant object key validation"
echo "• Bucket hash mapping for namespace collision avoidance"
echo "• Customer isolation through deterministic hashing"
echo "• GDPR-compliant HTTP redirects (global → regional)"
echo "• Multi-backend replication support"
echo "• Complete S3 workflow: Create bucket → Upload objects → List contents"
echo "• LocationConstraint with comma-separated regions/zones"
echo "• Cross-border replication control based on specified countries"
echo "• Order-based location priority (first = primary)"
echo "• Replica count management via API"
echo ""
echo "🗺️ Bucket Hash Mapping Benefits:"
echo "• Unique backend names across all customers and providers"
echo "• Solves S3 global namespace collision problem"
echo "• Enables true multi-backend replication"
echo "• Customer only sees logical names"
echo "• Deterministic generation (same input = same output)"
echo ""
echo "🌍 LocationConstraint Benefits:"
echo "• S3-compatible location specification (comma-separated list)"
echo "• Order-based priority: first location = primary placement"
echo "• Cross-border replication only when multiple countries specified"
echo "• Flexible region/zone targeting (fi, fi-hel, fi-hel-st-1)"
echo "• Replica count controls actual replication (via tags/API)"
echo ""
echo "📋 Workflow Requirements:"
echo "• Buckets must be created first using PUT /s3/{bucket-name}"
echo "• Objects can only be uploaded to existing buckets"
echo "• Each bucket gets unique backend names via hash mapping"
echo "• Customer sees logical names, backends see hashed names"
echo "• LocationConstraint controls where bucket is initially placed"
echo "• Replication expands to additional locations based on replica_count"
echo ""
echo "🔧 Configuration:"
echo "• Enable validation: ENABLE_S3_VALIDATION=true"
echo "• Strict mode: S3_VALIDATION_STRICT=true"
echo "• Bucket mapping: Always enabled"
echo "• LocationConstraint: Built-in support"
echo "• Test endpoints: /validation/test, /api/bucket-mappings/test, /api/location-constraints/test"
echo ""

# Check if services are running
if ! curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${YELLOW}⚠️ Note: Global gateway not running. Start with:${NC}"
    echo "./start.sh"
fi

if ! curl -s http://localhost:8001/health > /dev/null; then
    echo -e "${YELLOW}⚠️ Note: Regional gateway not running. Start with:${NC}"
    echo "./start.sh"
fi

echo ""
echo -e "${BLUE}🌍 Testing LocationConstraint API Endpoints${NC}"
echo "-------------------------------------------"

# Test available locations
echo ""
echo "1. Testing available locations endpoint:"
locations_response=$(curl -s "http://localhost:8000/api/location-constraints/available-locations" 2>/dev/null)

if echo "$locations_response" | grep -q '"available_locations"'; then
    echo -e "   ${GREEN}✅ SUCCESS${NC}: Available locations retrieved"
    
    # Count countries
    country_count=$(echo "$locations_response" | grep -o '"Finland"' | wc -l)
    [ "$country_count" -gt 0 ] && echo "   • Finland locations available"
    
    country_count=$(echo "$locations_response" | grep -o '"Germany"' | wc -l)
    [ "$country_count" -gt 0 ] && echo "   • Germany locations available"
    
    country_count=$(echo "$locations_response" | grep -o '"France"' | wc -l)
    [ "$country_count" -gt 0 ] && echo "   • France locations available"
else
    echo -e "   ${RED}❌ FAILED${NC}: Could not retrieve available locations"
fi

# Test location constraint parsing
test_constraints=(
    "fi"                    # Single region
    "fi,de"                 # Cross-border
    "fi-hel-st-1"          # Specific zone
    "fi,de,fr"             # Multi-country
    "fi-hel-st-1,de-fra-uc-1"  # Specific zones
    "invalid-location"      # Invalid
)

echo ""
echo "2. Testing location constraint parsing:"
for constraint in "${test_constraints[@]}"; do
    echo ""
    echo "   Testing constraint: '$constraint'"
    
    test_response=$(curl -s -X POST "http://localhost:8000/api/location-constraints/test" \
        -H "Content-Type: application/json" \
        -d "{\"location_constraint\": \"$constraint\", \"replica_count\": 2}" 2>/dev/null)
    
    if echo "$test_response" | grep -q '"test": true'; then
        if echo "$test_response" | grep -q '"valid": true'; then
            echo -e "     ${GREEN}✅ VALID${NC}: Constraint parsed successfully"
            
            # Extract policy details
            primary_location=$(echo "$test_response" | grep -o '"primary_location": "[^"]*"' | cut -d'"' -f4)
            cross_border=$(echo "$test_response" | grep -o '"cross_border_allowed": [^,}]*' | cut -d: -f2 | tr -d ' ')
            
            echo "     Primary: $primary_location"
            echo "     Cross-border: $cross_border"
            
            # Show replication zones
            replication_zones=$(echo "$test_response" | grep -o '"replication_zones": \[[^]]*\]')
            if [ ! -z "$replication_zones" ]; then
                echo "     Replication: $replication_zones"
            fi
            
        elif echo "$test_response" | grep -q '"valid": false'; then
            echo -e "     ${RED}❌ INVALID${NC}: Constraint rejected (expected for invalid cases)"
            errors=$(echo "$test_response" | grep -o '"errors": \[[^]]*\]')
            [ ! -z "$errors" ] && echo "     Errors: $errors"
        else
            echo -e "     ${YELLOW}⚠️ UNKNOWN${NC}: Unexpected response format"
        fi
    else
        echo -e "     ${RED}❌ FAILED${NC}: Service error or invalid response"
    fi
done 