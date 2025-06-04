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

# Test the validation module directly
echo ""
echo -e "${BLUE}📋 Testing S3 Validation Module Directly${NC}"
echo "----------------------------------------"

echo "Running Python validation tests..."
cd code/gateway
python3 s3_validation.py
cd ../..

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
    
    # Test actual S3 endpoint (should redirect with validation)
    echo "  Testing S3 endpoint redirect..."
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

echo "Testing complete S3 workflow with validation..."

# Test 1: Valid bucket and object
echo ""
echo "1. Testing valid bucket and object creation:"
valid_bucket="test-bucket-$(date +%s)"
valid_object="documents/test-file.txt"

echo "   Creating bucket: $valid_bucket"
create_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT -H "X-Customer-ID: demo-customer" "http://localhost:8000/s3/$valid_bucket" 2>/dev/null)
create_http_code=$(echo "$create_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

case $create_http_code in
    307) echo -e "   ${GREEN}✅ SUCCESS${NC}: Redirected to regional endpoint" ;;
    400) echo -e "   ${RED}❌ VALIDATION FAILED${NC}: Bucket name rejected" ;;
    *) echo -e "   ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $create_http_code" ;;
esac

echo "   Uploading object: $valid_object"
upload_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT -H "X-Customer-ID: demo-customer" -d "Test content" "http://localhost:8000/s3/$valid_bucket/$valid_object" 2>/dev/null)
upload_http_code=$(echo "$upload_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

case $upload_http_code in
    307) echo -e "   ${GREEN}✅ SUCCESS${NC}: Redirected to regional endpoint" ;;
    400) echo -e "   ${RED}❌ VALIDATION FAILED${NC}: Object key rejected" ;;
    *) echo -e "   ${YELLOW}⚠️ UNEXPECTED${NC}: HTTP $upload_http_code" ;;
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

# Test 3: Check health endpoints
echo ""
echo "3. Testing health endpoints with validation status:"

echo "   Global gateway health:"
global_health=$(curl -s "http://localhost:8000/health" 2>/dev/null)
if echo "$global_health" | grep -q '"s3_validation"'; then
    validation_status=$(echo "$global_health" | grep -o '"enabled": [^,}]*' | head -1)
    strict_status=$(echo "$global_health" | grep -o '"strict_mode": [^,}]*' | head -1)
    echo -e "   ${GREEN}✅ AVAILABLE${NC}: Validation $validation_status, Strict $strict_status"
else
    echo -e "   ${YELLOW}⚠️ NO VALIDATION INFO${NC}: Health endpoint may not include validation status"
fi

echo "   Regional gateway health:"
regional_health=$(curl -s "http://localhost:8001/health" 2>/dev/null)
if echo "$regional_health" | grep -q '"s3_validation"'; then
    validation_status=$(echo "$regional_health" | grep -o '"enabled": [^,}]*' | head -1)
    strict_status=$(echo "$regional_health" | grep -o '"strict_mode": [^,}]*' | head -1)
    echo -e "   ${GREEN}✅ AVAILABLE${NC}: Validation $validation_status, Strict $strict_status"
else
    echo -e "   ${YELLOW}⚠️ NO VALIDATION INFO${NC}: Health endpoint may not include validation status"
fi

echo ""
echo -e "${GREEN}🎯 S3 Validation Test Summary${NC}"
echo "============================"
echo ""
echo "✅ Benefits of S3 Validation:"
echo "• Prevents backend creation failures due to invalid names"
echo "• Validates both bucket names and object keys"
echo "• Provides clear error messages in S3-compatible XML format"
echo "• Supports both standard and strict validation modes"
echo "• Integrates with GDPR-compliant routing architecture"
echo ""
echo "🔧 Configuration:"
echo "• Enable with ENABLE_S3_VALIDATION=true"
echo "• Strict mode with S3_VALIDATION_STRICT=true"
echo "• Test endpoint: /validation/test"
echo ""
echo "📚 Validation Rules:"
echo "• Bucket names: 3-63 chars, lowercase, no consecutive dots, no IP format"
echo "• Object keys: max 1024 bytes, UTF-8 safe, optional strict character filtering"
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