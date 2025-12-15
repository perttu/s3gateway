#!/bin/bash

# Ceph Backend Setup Script for S3 Gateway
# This script helps configure Ceph clusters as backends for the S3 Gateway

set -e

echo "============================================"
echo "Ceph Backend Setup for S3 Gateway"
echo "============================================"

CONFIG_DIR="./config/ceph"
CEPH_CONF="$CONFIG_DIR/ceph.conf"
KEYRING_FILE="$CONFIG_DIR/ceph.client.s3gateway.keyring"

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"

echo "1. Setting up Ceph configuration files..."

# Check if configuration files exist
if [ ! -f "$CEPH_CONF" ]; then
    echo "   Creating Ceph configuration file: $CEPH_CONF"
    cp "$CONFIG_DIR/ceph.conf.example" "$CEPH_CONF" 2>/dev/null || {
        echo "   Example file not found. Creating basic configuration..."
        cat > "$CEPH_CONF" << 'EOF'
[global]
    cluster = ceph
    mon host = 127.0.0.1:6789
    auth cluster required = cephx
    auth service required = cephx
    auth client required = cephx

[client.s3gateway]
    keyring = /etc/ceph/ceph.client.s3gateway.keyring
EOF
    }
    echo "   ✓ Created $CEPH_CONF"
    echo "   → Please edit this file with your Ceph cluster details"
else
    echo "   ✓ Ceph configuration already exists: $CEPH_CONF"
fi

if [ ! -f "$KEYRING_FILE" ]; then
    echo "   Creating Ceph keyring file: $KEYRING_FILE"
    cp "$CONFIG_DIR/ceph.client.s3gateway.keyring.example" "$KEYRING_FILE" 2>/dev/null || {
        echo "   Example file not found. Creating placeholder keyring..."
        cat > "$KEYRING_FILE" << 'EOF'
[client.s3gateway]
    key = AQBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx==
    caps mon = "allow r"
    caps osd = "allow rwx pool=s3gateway"
EOF
    }
    echo "   ✓ Created $KEYRING_FILE"
    echo "   → Please replace with actual key from your Ceph cluster"
else
    echo "   ✓ Ceph keyring already exists: $KEYRING_FILE"
fi

echo ""
echo "2. Checking Ceph backend configuration..."

# Update ceph_backends.json with correct agent URL for local testing
CEPH_BACKENDS_CONFIG="./config/ceph_backends.json"
if [ -f "$CEPH_BACKENDS_CONFIG" ]; then
    echo "   ✓ Ceph backends configuration exists: $CEPH_BACKENDS_CONFIG"
    
    # Check if using localhost for local testing
    if grep -q "localhost" "$CEPH_BACKENDS_CONFIG"; then
        echo "   → Configuration appears to be set for local testing"
    elif grep -q "librados-agent-fi-hel" "$CEPH_BACKENDS_CONFIG"; then
        echo "   → Configuration appears to be set for Docker deployment"
    fi
else
    echo "   ✗ Ceph backends configuration not found!"
    echo "   → Please ensure $CEPH_BACKENDS_CONFIG exists"
fi

echo ""
echo "3. Instructions for Ceph cluster setup:"
echo ""
echo "   To create a user for the S3 Gateway in your Ceph cluster:"
echo "   $ ceph auth get-or-create client.s3gateway mon 'allow r' osd 'allow rwx pool=s3gateway'"
echo ""
echo "   To create the s3gateway pool:"
echo "   $ ceph osd pool create s3gateway 64 64"
echo "   $ ceph osd pool application enable s3gateway rgw"
echo ""
echo "   To get the keyring for an existing user:"
echo "   $ ceph auth get client.s3gateway"
echo ""

echo "4. Configuration steps:"
echo ""
echo "   a) Edit $CEPH_CONF:"
echo "      - Set 'mon host' to your Ceph monitor IPs"
echo "      - Update network settings if needed"
echo ""
echo "   b) Edit $KEYRING_FILE:"
echo "      - Replace the placeholder key with actual key from Ceph cluster"
echo ""
echo "   c) Edit $CEPH_BACKENDS_CONFIG:"
echo "      - Update agent URLs for your deployment"
echo "      - Enable/disable backends as needed"
echo "      - Configure Ceph cluster details"
echo ""

echo "5. Testing your configuration:"
echo ""
echo "   Start the services:"
echo "   $ docker-compose up -d librados-agent-fi-hel"
echo "   $ docker-compose logs -f librados-agent-fi-hel"
echo ""
echo "   Check agent health:"
echo "   $ curl http://localhost:8090/health"
echo ""
echo "   Check gateway with Ceph backends:"
echo "   $ curl http://localhost:8001/ceph/health"
echo ""

echo "============================================"
echo "Setup complete! Please follow the configuration steps above."
echo "============================================" 