#!/bin/bash

echo "🚀 Deploying S3 Gateway Two-Layer Architecture"
echo "=============================================="

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install it first."
    exit 1
fi

# Set working directory to s3gateway
cd "$(dirname "$0")"

echo "📁 Working directory: $(pwd)"

# Stop any existing containers
echo "🛑 Stopping existing containers..."
docker-compose -f docker-compose.two-layer.yml down

# Build and start services
echo "🏗️  Building and starting services..."
docker-compose -f docker-compose.two-layer.yml up -d --build

# Wait for services to start
echo "⏳ Waiting for services to start..."
sleep 15

# Check service health
echo "🔍 Checking service health..."

echo "Global Gateway (Port 8000):"
curl -s http://localhost:8000/health | jq '.' || echo "❌ Global gateway not responding"

echo -e "\nFI-HEL Regional Gateway (Port 8001):"
curl -s http://localhost:8001/health | jq '.' || echo "❌ FI-HEL gateway not responding"

echo -e "\nDE-FRA Regional Gateway (Port 8002):"
curl -s http://localhost:8002/health | jq '.' || echo "❌ DE-FRA gateway not responding"

# Show service status
echo -e "\n📊 Service Status:"
docker-compose -f docker-compose.two-layer.yml ps

echo -e "\n✅ Deployment Complete!"
echo ""
echo "🌐 Endpoints:"
echo "  Global Gateway:  http://localhost:8000"
echo "  FI-HEL Region:   http://localhost:8001"
echo "  DE-FRA Region:   http://localhost:8002"
echo ""
echo "📚 Next Steps:"
echo "  1. Register a customer: curl -X POST http://localhost:8000/routing/customers/my-customer?region_id=FI-HEL"
echo "  2. Register customer details: curl -X POST http://localhost:8001/api/customers/my-customer/register -H 'Content-Type: application/json' -d '{\"customer_name\": \"My Company\", \"country\": \"Finland\"}'"
echo "  3. Test S3 operations: curl -H 'X-Customer-ID: my-customer' http://localhost:8000/s3/test-bucket"
echo ""
echo "🔍 Monitor logs: docker-compose -f docker-compose.two-layer.yml logs -f"
echo "🛑 Stop services: docker-compose -f docker-compose.two-layer.yml down" 