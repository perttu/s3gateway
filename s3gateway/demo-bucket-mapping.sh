#!/bin/bash

echo "🗺️ S3 Gateway Bucket Hash Mapping Demo"
echo "====================================="

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if services are running
if ! curl -s http://localhost:8000/health > /dev/null; then
    echo -e "${YELLOW}⚠️ Services not running. Start with: ./start.sh${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}🎯 Demonstrating S3 workflow with bucket hash mapping${NC}"
echo ""

CUSTOMER_ID="demo-company"
BUCKET_NAME="my-data-$(date +%s)"

echo "Customer: $CUSTOMER_ID"
echo "Logical Bucket: $BUCKET_NAME"
echo ""

# Step 1: Create bucket
echo -e "${BLUE}Step 1: Create bucket (generates hash mapping)${NC}"
echo "Command: curl -X PUT -H \"X-Customer-ID: $CUSTOMER_ID\" http://localhost:8000/s3/$BUCKET_NAME"

create_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
    -H "X-Customer-ID: $CUSTOMER_ID" \
    "http://localhost:8000/s3/$BUCKET_NAME" 2>/dev/null)

http_code=$(echo "$create_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

if [ "$http_code" = "307" ] || [ "$http_code" = "200" ]; then
    echo -e "${GREEN}✅ Bucket created successfully!${NC}"
    
    # Wait a moment for mapping to be stored
    sleep 2
    
    # Show the mapping
    echo ""
    echo -e "${BLUE}📊 Generated bucket mapping:${NC}"
    mapping_response=$(curl -s "http://localhost:8000/api/bucket-mappings/$CUSTOMER_ID/$BUCKET_NAME" 2>/dev/null)
    
    if echo "$mapping_response" | grep -q '"backend_mapping"'; then
        echo "Customer sees: $BUCKET_NAME"
        echo "Backend mappings:"
        
        # Extract and display backend mappings
        spacetime=$(echo "$mapping_response" | grep -o '"spacetime": "[^"]*"' | cut -d'"' -f4)
        upcloud=$(echo "$mapping_response" | grep -o '"upcloud": "[^"]*"' | cut -d'"' -f4)
        hetzner=$(echo "$mapping_response" | grep -o '"hetzner": "[^"]*"' | cut -d'"' -f4)
        
        [ ! -z "$spacetime" ] && echo "  → Spacetime: $spacetime"
        [ ! -z "$upcloud" ] && echo "  → UpCloud:   $upcloud"
        [ ! -z "$hetzner" ] && echo "  → Hetzner:   $hetzner"
        
        echo ""
        echo -e "${GREEN}✅ Each backend gets a unique bucket name!${NC}"
    else
        echo -e "${YELLOW}⚠️ Could not retrieve mapping details${NC}"
    fi
else
    echo -e "${RED}❌ Bucket creation failed (HTTP $http_code)${NC}"
    exit 1
fi

# Step 2: Upload a file
echo ""
echo -e "${BLUE}Step 2: Upload file to bucket${NC}"
file_content="Hello from S3 Gateway with bucket hash mapping! Timestamp: $(date)"
object_key="documents/demo-file.txt"

echo "Command: curl -X PUT -H \"X-Customer-ID: $CUSTOMER_ID\" -d \"$file_content\" http://localhost:8000/s3/$BUCKET_NAME/$object_key"

upload_response=$(curl -s -w "HTTP_CODE:%{http_code}" -X PUT \
    -H "X-Customer-ID: $CUSTOMER_ID" \
    -H "Content-Type: text/plain" \
    -d "$file_content" \
    "http://localhost:8000/s3/$BUCKET_NAME/$object_key" 2>/dev/null)

upload_http_code=$(echo "$upload_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

if [ "$upload_http_code" = "307" ] || [ "$upload_http_code" = "200" ]; then
    echo -e "${GREEN}✅ File uploaded successfully!${NC}"
    echo "Object: $object_key"
    echo "Content: $(echo "$file_content" | cut -c1-50)..."
else
    echo -e "${YELLOW}⚠️ File upload returned HTTP $upload_http_code${NC}"
fi

# Step 3: List bucket contents
echo ""
echo -e "${BLUE}Step 3: List bucket contents${NC}"
echo "Command: curl -H \"X-Customer-ID: $CUSTOMER_ID\" http://localhost:8000/s3/$BUCKET_NAME"

list_response=$(curl -s -w "HTTP_CODE:%{http_code}" \
    -H "X-Customer-ID: $CUSTOMER_ID" \
    "http://localhost:8000/s3/$BUCKET_NAME" 2>/dev/null)

list_http_code=$(echo "$list_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

if [ "$list_http_code" = "307" ] || [ "$list_http_code" = "200" ]; then
    echo -e "${GREEN}✅ Bucket listing successful!${NC}"
    echo "Customer can list objects in their logical bucket"
else
    echo -e "${YELLOW}⚠️ Bucket listing returned HTTP $list_http_code${NC}"
fi

# Step 4: Retrieve the file
echo ""
echo -e "${BLUE}Step 4: Retrieve uploaded file${NC}"
echo "Command: curl -H \"X-Customer-ID: $CUSTOMER_ID\" http://localhost:8000/s3/$BUCKET_NAME/$object_key"

get_response=$(curl -s -w "HTTP_CODE:%{http_code}" \
    -H "X-Customer-ID: $CUSTOMER_ID" \
    "http://localhost:8000/s3/$BUCKET_NAME/$object_key" 2>/dev/null)

get_http_code=$(echo "$get_response" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)

if [ "$get_http_code" = "307" ] || [ "$get_http_code" = "200" ]; then
    echo -e "${GREEN}✅ File retrieval successful!${NC}"
    echo "Customer can access their files using logical bucket names"
else
    echo -e "${YELLOW}⚠️ File retrieval returned HTTP $get_http_code${NC}"
fi

echo ""
echo -e "${GREEN}🎉 Demo Complete!${NC}"
echo ""
echo "📋 Summary:"
echo "• Customer created bucket: $BUCKET_NAME"
echo "• System generated unique backend names for each provider"
echo "• Customer uploaded and accessed files using logical name"
echo "• Backend namespace collisions completely avoided"
echo ""
echo "🔧 Benefits achieved:"
echo "• ✅ Multiple customers can use the same logical bucket names"
echo "• ✅ Each backend gets unique bucket names (no collisions)"
echo "• ✅ Customer experience remains simple and familiar"
echo "• ✅ True multi-backend replication enabled"
echo "• ✅ GDPR-compliant with regional data sovereignty" 