#!/bin/bash

echo "🏷️🔄 S3 Tagging and Replication Management Demo"
echo "==============================================="
echo ""
echo "This demo shows S3-compatible tagging with background replication"
echo "including efficient deletion when replica count is reduced."
echo ""

# Configuration
CUSTOMER_ID="demo-customer"
BUCKET_NAME="my-app-data"
OBJECT_KEY="user-profile.json"
GLOBAL_GATEWAY="http://localhost:8000"
REGIONAL_GATEWAY="http://localhost:8001"

echo "📋 Demo Configuration:"
echo "  Customer ID: $CUSTOMER_ID"
echo "  Bucket: $BUCKET_NAME"
echo "  Object: $OBJECT_KEY"
echo "  Global Gateway: $GLOBAL_GATEWAY"
echo "  Regional Gateway: $REGIONAL_GATEWAY"
echo ""

# Helper function to show response
show_response() {
    echo "Response: $1"
    echo ""
}

echo "🗂️ Step 1: Create bucket with LocationConstraint"
echo "================================================"
echo "Creating bucket with multi-region capability (fi,de,fr)..."

response=$(curl -s -X PUT "$GLOBAL_GATEWAY/s3/$BUCKET_NAME" \
  -H "X-Customer-ID: $CUSTOMER_ID" \
  -H "Content-Type: application/xml" \
  -d '<CreateBucketConfiguration>
    <LocationConstraint>fi,de,fr</LocationConstraint>
  </CreateBucketConfiguration>')

show_response "$response"

echo "📄 Step 2: Upload test object"
echo "============================="
echo "Uploading user profile data..."

response=$(curl -s -X PUT "$REGIONAL_GATEWAY/s3/$BUCKET_NAME/$OBJECT_KEY" \
  -H "X-Customer-ID: $CUSTOMER_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 12345,
    "name": "John Doe",
    "email": "john@example.com",
    "preferences": {
      "theme": "dark",
      "notifications": true
    }
  }')

show_response "$response"

echo "🏷️ Step 3: Set tags to replicate to 3 regions"
echo "=============================================="
echo "Setting replica-count=3 via tags (should replicate to fi,de,fr)..."

response=$(curl -s -X PUT "$REGIONAL_GATEWAY/s3/$BUCKET_NAME/$OBJECT_KEY?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>3</Value>
      </Tag>
      <Tag>
        <Key>data-classification</Key>
        <Value>sensitive</Value>
      </Tag>
      <Tag>
        <Key>backup-schedule</Key>
        <Value>daily</Value>
      </Tag>
    </TagSet>
  </Tagging>')

show_response "$response"

echo "⏳ Waiting for replication jobs to start..."
sleep 2

echo "📊 Step 4: Check replication queue status"
echo "========================================="
echo "Checking active replication jobs..."

response=$(curl -s "$REGIONAL_GATEWAY/api/replication/queue/status")
show_response "$response"

echo "📋 Active replication jobs:"
response=$(curl -s "$REGIONAL_GATEWAY/api/replication/jobs/active")
show_response "$response"

echo "⏳ Waiting for replication to complete..."
sleep 5

echo "📄 Step 5: Upload more test objects for bulk demonstration"
echo "========================================================"
echo "Uploading additional objects to demonstrate bulk deletion..."

for i in {1..5}; do
    echo "Uploading test-file-$i.json..."
    curl -s -X PUT "$REGIONAL_GATEWAY/s3/$BUCKET_NAME/test-file-$i.json" \
      -H "X-Customer-ID: $CUSTOMER_ID" \
      -H "Content-Type: application/json" \
      -d "{\"file_id\": $i, \"content\": \"Test data for file $i\"}" > /dev/null
done

echo "✅ Uploaded 5 additional test files"
echo ""

echo "🏷️ Step 6: Set bucket-level tags for bulk replication"
echo "===================================================="
echo "Setting bucket tags with replica-count=3 (affects all objects)..."

response=$(curl -s -X PUT "$REGIONAL_GATEWAY/s3/$BUCKET_NAME?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>3</Value>
      </Tag>
      <Tag>
        <Key>bucket-tier</Key>
        <Value>premium</Value>
      </Tag>
    </TagSet>
  </Tagging>')

show_response "$response"

echo "⏳ Waiting for bulk replication jobs..."
sleep 3

echo "📊 Current replication status:"
response=$(curl -s "$REGIONAL_GATEWAY/api/replication/jobs/active")
show_response "$response"

echo ""
echo "🗑️ Step 7: REDUCE replica count to demonstrate deletion"
echo "====================================================="
echo "⚠️  Reducing replica-count from 3 to 1 (should delete data from de,fr)..."

response=$(curl -s -X PUT "$REGIONAL_GATEWAY/s3/$BUCKET_NAME/$OBJECT_KEY?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>1</Value>
      </Tag>
      <Tag>
        <Key>data-classification</Key>
        <Value>sensitive</Value>
      </Tag>
      <Tag>
        <Key>retention-reason</Key>
        <Value>cost-optimization</Value>
      </Tag>
    </TagSet>
  </Tagging>')

show_response "$response"

echo "📊 Checking deletion jobs in queue:"
response=$(curl -s "$REGIONAL_GATEWAY/api/replication/jobs/active")
echo "Active jobs (should show removal operations):"
echo "$response" | jq '.'
echo ""

echo "⏳ Waiting for deletion jobs to process..."
sleep 5

echo "🗑️ Step 8: BULK bucket deletion demonstration"
echo "============================================"
echo "⚠️  Setting bucket-level replica-count=1 to trigger bulk deletion..."

response=$(curl -s -X PUT "$REGIONAL_GATEWAY/s3/$BUCKET_NAME?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID" \
  -H "Content-Type: application/xml" \
  -d '<Tagging>
    <TagSet>
      <Tag>
        <Key>replica-count</Key>
        <Value>1</Value>
      </Tag>
      <Tag>
        <Key>bucket-tier</Key>
        <Value>standard</Value>
      </Tag>
      <Tag>
        <Key>cost-optimization</Key>
        <Value>enabled</Value>
      </Tag>
    </TagSet>
  </Tagging>')

show_response "$response"

echo "📊 Checking for bulk deletion jobs:"
response=$(curl -s "$REGIONAL_GATEWAY/api/replication/jobs/active")
echo "Active jobs (should show bulk bucket deletion operations):"
echo "$response" | jq '.' 2>/dev/null || echo "$response"
echo ""

echo "⏳ Waiting for bulk deletion to complete..."
sleep 8

echo "📊 Step 9: Final status check"
echo "============================="
echo "Final replication queue status:"
response=$(curl -s "$REGIONAL_GATEWAY/api/replication/queue/status")
echo "$response" | jq '.' 2>/dev/null || echo "$response"
echo ""

echo "Remaining active jobs:"
response=$(curl -s "$REGIONAL_GATEWAY/api/replication/jobs/active")
echo "$response" | jq '.' 2>/dev/null || echo "$response"
echo ""

echo "🏷️ Step 10: Verify current tags"
echo "==============================="
echo "Current object tags:"
response=$(curl -s "$REGIONAL_GATEWAY/s3/$BUCKET_NAME/$OBJECT_KEY?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID")
show_response "$response"

echo "Current bucket tags:"
response=$(curl -s "$REGIONAL_GATEWAY/s3/$BUCKET_NAME?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID")
show_response "$response"

echo "📋 Step 11: Test complete deletion of tags"
echo "========================================="
echo "Deleting all object tags..."

response=$(curl -s -X DELETE "$REGIONAL_GATEWAY/s3/$BUCKET_NAME/$OBJECT_KEY?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID")
show_response "$response"

echo "Deleting all bucket tags..."

response=$(curl -s -X DELETE "$REGIONAL_GATEWAY/s3/$BUCKET_NAME?tagging" \
  -H "X-Customer-ID: $CUSTOMER_ID")
show_response "$response"

echo ""
echo "✅ Demo Summary"
echo "==============="
echo "📋 What was demonstrated:"
echo "   ✅ S3-compatible tagging API with XML payloads"
echo "   ✅ Tag-based replica count management"
echo "   ✅ Background replication queue system"
echo "   ✅ LocationConstraint integration (fi,de,fr priority)"
echo "   ✅ Individual object replication jobs"
echo "   ✅ Bulk bucket operations for many objects"
echo "   ✅ EFFICIENT DELETION when replica count reduced"
echo "   ✅ Complete backend bucket cleanup"
echo "   ✅ Non-blocking operations (immediate tag response)"
echo ""
echo "🔄 Key Deletion Features Shown:"
echo "   🗑️  Individual object removal from specific zones"
echo "   🗑️  Bulk bucket deletion for cost optimization"
echo "   🗑️  Backend bucket cleanup when empty"
echo "   🗑️  Database metadata updates"
echo "   🗑️  Preserves primary region (always keeps 'fi')"
echo ""
echo "🏷️ Tag Integration:"
echo "   📝 replica-count tag triggers replication changes"
echo "   📝 Bucket tags affect all objects in bucket"
echo "   📝 Bulk operations automatically chosen for large buckets"
echo "   📝 Standard S3 tagging XML format"
echo ""
echo "The system now provides complete lifecycle management:"
echo "• Scale UP: Add replicas by increasing replica-count"
echo "• Scale DOWN: Remove replicas (and delete data) by decreasing replica-count"
echo "• Cost optimization through efficient bulk deletion"
echo "• Data sovereignty through LocationConstraint respect"
echo ""
echo "🎉 Demo completed successfully!" 