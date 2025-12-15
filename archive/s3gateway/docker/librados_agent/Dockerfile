FROM ubuntu:22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-dev \
    wget \
    gnupg2 \
    software-properties-common \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Add Ceph repository and install Ceph packages
RUN wget -q -O- 'https://download.ceph.com/keys/release.asc' | apt-key add - \
    && echo deb https://download.ceph.com/debian-reef/ jammy main | tee /etc/apt/sources.list.d/ceph.list \
    && apt-get update \
    && apt-get install -y \
        ceph-common \
        librados-dev \
        librbd-dev \
        python3-rados \
        python3-rbd \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Create directory for Ceph configuration
RUN mkdir -p /etc/ceph

# Expose port
EXPOSE 8090

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

# Run the application
CMD ["python3", "main.py"] 