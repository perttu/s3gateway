#!/bin/bash

echo "🚀 Starting S3 Gateway with GDPR Compliance & Validation"
echo "========================================================"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Error: docker-compose not found${NC}"
    echo "Please install Docker Compose and try again."
    exit 1
fi

# Handle command line arguments
CLEAN=false
QUIET=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --quiet)
            QUIET=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --clean    Remove all data volumes and rebuild"
            echo "  --quiet    Minimal output"
            echo "  --help     Show this help message"
            echo ""
            echo "Features:"
            echo "  ✅ S3 RFC-compliant naming validation"
            echo "  ✅ GDPR-compliant HTTP redirects"
            echo "  ✅ Multi-regional support (FI-HEL, DE-FRA)"
            echo "  ✅ Comprehensive health checks"
            echo ""
            echo "Quick test after startup:"
            echo "  ./test.sh"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Stop any existing services
if [ "$QUIET" = false ]; then
    echo -e "${YELLOW}🛑 Stopping existing services...${NC}"
fi
docker-compose down > /dev/null 2>&1

# Clean up if requested
if [ "$CLEAN" = true ]; then
    if [ "$QUIET" = false ]; then
        echo -e "${YELLOW}🧹 Cleaning up old data...${NC}"
    fi
    docker-compose down -v > /dev/null 2>&1
    docker system prune -f > /dev/null 2>&1
fi

# Build and start services
if [ "$QUIET" = false ]; then
    echo -e "${BLUE}🏗️ Starting services...${NC}"
    docker-compose up --build -d
else
    docker-compose up --build -d > /dev/null 2>&1
fi

# Wait for services to be ready
if [ "$QUIET" = false ]; then
    echo -e "${BLUE}⏳ Waiting for services to be ready...${NC}"
fi
sleep 15

# Quick health check
if [ "$QUIET" = false ]; then
    echo -e "${BLUE}🏥 Checking service health...${NC}"
fi

all_healthy=true

# Check databases
for db in postgres-global postgres-fi-hel postgres-de-fra; do
    if docker-compose ps | grep -q "${db}.*healthy"; then
        if [ "$QUIET" = false ]; then
            echo -e "  ${GREEN}✅ $db${NC}: Ready"
        fi
    else
        echo -e "  ${RED}❌ $db${NC}: Not ready"
        all_healthy=false
    fi
done

# Check gateways
for service in gateway-global:8000 gateway-fi-hel:8001 gateway-de-fra:8002; do
    name=$(echo $service | cut -d: -f1)
    port=$(echo $service | cut -d: -f2)
    
    if curl -s "http://localhost:$port/health" > /dev/null 2>&1; then
        if [ "$QUIET" = false ]; then
            echo -e "  ${GREEN}✅ $name${NC}: Ready"
        fi
    else
        echo -e "  ${RED}❌ $name${NC}: Not ready"
        all_healthy=false
    fi
done

echo ""
if $all_healthy; then
    echo -e "${GREEN}🎉 All services are running!${NC}"
else
    echo -e "${YELLOW}⚠️ Some services need more time. Check: docker-compose logs${NC}"
fi

if [ "$QUIET" = false ]; then
    echo ""
    echo -e "${BLUE}📊 Service Endpoints:${NC}"
    echo "Global Gateway:    http://localhost:8000 (with validation & redirects)"
    echo "FI-HEL Gateway:    http://localhost:8001 (standard validation)" 
    echo "DE-FRA Gateway:    http://localhost:8002 (strict validation)"
    echo "S3Proxy:          http://localhost:8080 (fallback)"
    echo ""
    echo -e "${BLUE}🧪 Quick Test:${NC}"
    echo "./test.sh"
    echo ""
    echo -e "${BLUE}📖 View Logs:${NC}"
    echo "docker-compose logs -f"
    echo ""
    echo -e "${BLUE}🛑 Stop:${NC}"
    echo "docker-compose down"
fi 