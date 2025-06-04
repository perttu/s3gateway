#!/bin/bash

echo "Starting S3 Gateway Service..."
echo "==============================="

# Check if providers_flat.csv exists
if [ ! -f "../providers_flat.csv" ]; then
    echo "Warning: providers_flat.csv not found in parent directory"
    echo "Please ensure the file exists for proper provider data loading"
fi

# Start services
echo "Starting Docker services..."
docker-compose up -d

echo ""
echo "Waiting for services to start..."
sleep 10

# Check service status
echo ""
echo "Service Status:"
echo "==============="
docker-compose ps

# Test endpoints
echo ""
echo "Testing endpoints..."
echo "==================="

echo "1. Health check:"
curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "Gateway not ready yet"

echo ""
echo "2. S3Proxy health check:"
curl -s -I http://localhost:8080 | head -1 || echo "S3Proxy not ready yet"

echo ""
echo "Services are starting up!"
echo ""
echo "Available endpoints:"
echo "- Gateway API: http://localhost:8000"
echo "- S3Proxy: http://localhost:8080"
echo "- PostgreSQL: localhost:5433"
echo ""
echo "Try these commands:"
echo "  curl http://localhost:8000/health"
echo "  curl http://localhost:8000/providers"
echo "  curl 'http://localhost:8000/sovereignty/check?country=Germany&replicas=3'"
echo ""
echo "View logs with:"
echo "  docker-compose logs -f gateway"
echo "  docker-compose logs -f s3proxy"
echo "  docker-compose logs -f postgres" 