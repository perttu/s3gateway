#!/bin/bash

echo "🚀 S3 Gateway - Unified Demo & Test Launcher"
echo "============================================"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Check if services are running
check_services() {
    if curl -s http://localhost:8000/health > /dev/null && curl -s http://localhost:8001/health > /dev/null; then
        return 0
    else
        return 1
    fi
}

show_menu() {
    echo -e "${CYAN}📋 Available Commands:${NC}"
    echo ""
    echo -e "${BLUE}🏗️  SETUP & MANAGEMENT${NC}"
    echo "  1. start     - Start all S3 gateway services"
    echo "  2. stop      - Stop all services"
    echo "  3. restart   - Restart services with fresh data"
    echo "  4. logs      - View service logs"
    echo "  5. status    - Check service health status"
    echo ""
    echo -e "${BLUE}🧪 CORE TESTING${NC}"
    echo "  6. test      - Comprehensive test suite (validation, mapping, compliance)"
    echo "  7. quick     - Quick smoke test of all features"
    echo ""
    echo -e "${BLUE}🔐 AUTHENTICATION & SECURITY${NC}"
    echo "  8. auth      - Full S3 authentication demo (AWS SigV4, credentials)"
    echo "  9. auth-arch - Test GDPR-compliant authentication architecture"
    echo ""
    echo -e "${BLUE}🗺️  BUCKET MAPPING & LOCATION${NC}"
    echo " 10. mapping   - Bucket hash mapping demo (namespace collision solution)"
    echo " 11. location  - LocationConstraint demo (fi,de,fr zones)"
    echo ""
    echo -e "${BLUE}🏷️  TAGGING & REPLICATION${NC}"
    echo " 12. tagging   - S3 tagging with background replication demo"
    echo " 13. replica   - Replication management and deletion demo"
    echo ""
    echo -e "${BLUE}⚖️  GDPR COMPLIANCE${NC}"
    echo " 14. gdpr      - GDPR compliance demo (proxy vs redirect)"
    echo " 15. privacy   - Data sovereignty and compliance verification"
    echo ""
    echo -e "${BLUE}📚 DOCUMENTATION${NC}"
    echo " 16. features  - List all S3 gateway features"
    echo " 17. help      - Show detailed help for each command"
    echo ""
    echo -e "${YELLOW}Usage: ./run.sh [command]${NC}"
    echo -e "${YELLOW}   or: ./run.sh (for interactive menu)${NC}"
}

show_features() {
    echo -e "${GREEN}✅ S3 Gateway Complete Feature List${NC}"
    echo "===================================="
    echo ""
    echo -e "${BLUE}🔐 Authentication & Authorization:${NC}"
    echo "  • AWS SigV4 signature validation"
    echo "  • GDPR-compliant authentication after redirect"
    echo "  • Fine-grained resource permissions"
    echo "  • Credential lifecycle management"
    echo "  • Regional credential storage"
    echo "  • Complete audit trails"
    echo ""
    echo -e "${BLUE}🗺️  Bucket Management:${NC}"
    echo "  • Deterministic hash-based bucket mapping"
    echo "  • Global namespace collision avoidance"
    echo "  • Multi-backend replication support"
    echo "  • Customer isolation"
    echo ""
    echo -e "${BLUE}🌍 Location & Compliance:${NC}"
    echo "  • S3-compatible LocationConstraint"
    echo "  • Order-based location priority"
    echo "  • Cross-border replication control"
    echo "  • GDPR-compliant HTTP redirects"
    echo "  • Data sovereignty enforcement"
    echo ""
    echo -e "${BLUE}🏷️  Tagging & Replication:${NC}"
    echo "  • Full S3-compatible tagging API"
    echo "  • Tag-based replica count management"
    echo "  • Background replication queue"
    echo "  • Efficient bulk deletion"
    echo "  • Non-blocking operations"
    echo ""
    echo -e "${BLUE}📋 Validation & Standards:${NC}"
    echo "  • S3 RFC-compliant naming validation"
    echo "  • Bucket name validation (3-63 chars, etc.)"
    echo "  • Object key validation (UTF-8 safe)"
    echo "  • Strict mode for enhanced compliance"
    echo ""
    echo -e "${BLUE}🏗️  Architecture:${NC}"
    echo "  • Two-layer global/regional design"
    echo "  • Multi-regional database support"
    echo "  • Provider-agnostic backend integration"
    echo "  • Comprehensive health monitoring"
}

show_detailed_help() {
    echo -e "${CYAN}📖 Detailed Command Help${NC}"
    echo "========================"
    echo ""
    echo -e "${BLUE}SETUP COMMANDS:${NC}"
    echo "  start    - Builds and starts all containers (global, regional, databases)"
    echo "  stop     - Gracefully stops all services"
    echo "  restart  - Stops, cleans volumes, and starts fresh"
    echo "  logs     - Shows real-time logs from all services"
    echo "  status   - Health check for all services with detailed status"
    echo ""
    echo -e "${BLUE}TESTING COMMANDS:${NC}"
    echo "  test     - Runs comprehensive test suite:"
    echo "             • S3 validation tests"
    echo "             • Bucket mapping verification"
    echo "             • LocationConstraint testing"
    echo "             • Complete workflow tests"
    echo "  quick    - Fast smoke test to verify basic functionality"
    echo ""
    echo -e "${BLUE}DEMO COMMANDS:${NC}"
    echo "  auth     - Complete authentication demonstration:"
    echo "             • Create AWS-style credentials"
    echo "             • Test AWS CLI integration"
    echo "             • Permission management"
    echo "             • Global → Regional routing"
    echo ""
    echo "  mapping  - Bucket hash mapping demonstration:"
    echo "             • Namespace collision avoidance"
    echo "             • Customer isolation"
    echo "             • Multi-backend unique names"
    echo ""
    echo "  tagging  - S3 tagging and replication:"
    echo "             • XML tagging payloads"
    echo "             • Replica count management"
    echo "             • Background replication jobs"
    echo "             • Bulk deletion when scaling down"
    echo ""
    echo "  gdpr     - GDPR compliance demonstration:"
    echo "             • Proxy vs redirect approaches"
    echo "             • Data sovereignty enforcement"
    echo "             • Compliance audit trails"
}

run_command() {
    local cmd=$1
    
    case $cmd in
        "1"|"start")
            echo -e "${BLUE}🏗️  Starting S3 Gateway services...${NC}"
            ./start.sh
            ;;
        "2"|"stop")
            echo -e "${YELLOW}🛑 Stopping all services...${NC}"
            docker-compose down
            echo -e "${GREEN}✅ Services stopped${NC}"
            ;;
        "3"|"restart")
            echo -e "${YELLOW}🔄 Restarting with fresh data...${NC}"
            ./start.sh --clean
            ;;
        "4"|"logs")
            echo -e "${BLUE}📋 Showing service logs (Ctrl+C to exit)...${NC}"
            docker-compose logs -f
            ;;
        "5"|"status")
            echo -e "${BLUE}🏥 Checking service health...${NC}"
            echo ""
            echo "Global Gateway (port 8000):"
            curl -s http://localhost:8000/health | jq '.status, .s3_authentication.status, .architecture.type' 2>/dev/null || echo "  Not responding"
            echo ""
            echo "Regional Gateway FI-HEL (port 8001):"
            curl -s http://localhost:8001/health | jq '.status, .s3_authentication.status, .architecture.type' 2>/dev/null || echo "  Not responding"
            echo ""
            echo "Regional Gateway DE-FRA (port 8002):"
            curl -s http://localhost:8002/health | jq '.status, .s3_authentication.status, .architecture.type' 2>/dev/null || echo "  Not responding"
            ;;
        "6"|"test")
            if check_services; then
                echo -e "${GREEN}🧪 Running comprehensive test suite...${NC}"
                ./test.sh
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "7"|"quick")
            if check_services; then
                echo -e "${GREEN}⚡ Running quick smoke test...${NC}"
                echo "Testing basic functionality..."
                
                echo "1. Global gateway health:"
                curl -s http://localhost:8000/health | jq '.status' 2>/dev/null || echo "❌ Failed"
                
                echo "2. Regional gateway health:"
                curl -s http://localhost:8001/health | jq '.status' 2>/dev/null || echo "❌ Failed"
                
                echo "3. S3 validation:"
                curl -s "http://localhost:8000/validation/test?bucket_name=test-bucket" | jq '.overall_valid' 2>/dev/null || echo "❌ Failed"
                
                echo "4. Authentication architecture:"
                curl -s http://localhost:8000/health | jq '.s3_authentication.strategy' 2>/dev/null || echo "❌ Failed"
                
                echo -e "${GREEN}✅ Quick test completed${NC}"
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "8"|"auth")
            if check_services; then
                echo -e "${GREEN}🔐 Running S3 authentication demo...${NC}"
                ./demo-s3-authentication.sh
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "9"|"auth-arch")
            if check_services; then
                echo -e "${GREEN}🏗️  Testing authentication architecture...${NC}"
                ./test-auth-architecture.sh
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "10"|"mapping")
            if check_services; then
                echo -e "${GREEN}🗺️  Running bucket mapping demo...${NC}"
                ./demo-bucket-mapping.sh
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "11"|"location")
            if check_services; then
                echo -e "${GREEN}🌍 Testing LocationConstraint features...${NC}"
                echo "Available locations:"
                curl -s "http://localhost:8000/api/location-constraints/available-locations" | jq '.available_locations' 2>/dev/null || echo "❌ Failed"
                echo ""
                echo "Testing location constraints:"
                for constraint in "fi" "fi,de" "fi-hel-st-1" "fi,de,fr"; do
                    echo "  Testing: $constraint"
                    curl -s -X POST "http://localhost:8000/api/location-constraints/test" \
                        -H "Content-Type: application/json" \
                        -d "{\"location_constraint\": \"$constraint\", \"replica_count\": 2}" | \
                        jq '.valid, .policy.primary_location, .policy.cross_border_replication' 2>/dev/null || echo "    ❌ Failed"
                done
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "12"|"tagging")
            if check_services; then
                echo -e "${GREEN}🏷️  Running S3 tagging demo...${NC}"
                ./demo-tagging-replication.sh
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "13"|"replica")
            if check_services; then
                echo -e "${GREEN}🔄 Testing replication management...${NC}"
                echo "Replication queue status:"
                curl -s "http://localhost:8001/api/replication/queue/status" | jq '.' 2>/dev/null || echo "❌ Failed"
                echo ""
                echo "Active replication jobs:"
                curl -s "http://localhost:8001/api/replication/jobs/active" | jq '.count' 2>/dev/null || echo "❌ Failed"
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "14"|"gdpr")
            echo -e "${GREEN}⚖️  Running GDPR compliance demo...${NC}"
            ./demo-gdpr-compliance.sh
            ;;
        "15"|"privacy")
            if check_services; then
                echo -e "${GREEN}🔒 Verifying data sovereignty...${NC}"
                echo "Global gateway architecture:"
                curl -s http://localhost:8000/health | jq '.s3_authentication.flow, .architecture' 2>/dev/null || echo "❌ Failed"
                echo ""
                echo "Regional gateway authentication:"
                curl -s http://localhost:8001/health | jq '.s3_authentication.status, .architecture.credential_storage' 2>/dev/null || echo "❌ Failed"
            else
                echo -e "${RED}❌ Services not running. Start with: ./run.sh start${NC}"
            fi
            ;;
        "16"|"features")
            show_features
            ;;
        "17"|"help")
            show_detailed_help
            ;;
        *)
            echo -e "${RED}❌ Unknown command: $cmd${NC}"
            echo ""
            show_menu
            return 1
            ;;
    esac
}

# Main execution
if [ $# -eq 0 ]; then
    # Interactive mode
    show_menu
    echo ""
    echo -n "Enter command number or name: "
    read -r choice
    echo ""
    run_command "$choice"
else
    # Direct command mode
    run_command "$1"
fi 