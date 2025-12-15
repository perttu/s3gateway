FROM openjdk:11-jre-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create s3proxy directory
RUN mkdir -p /opt/s3proxy /tmp/s3proxy

# Download S3Proxy
WORKDIR /opt/s3proxy
RUN wget -O s3proxy.jar https://github.com/gaul/s3proxy/releases/download/s3proxy-2.2.0/s3proxy

# Make it executable
RUN chmod +x s3proxy.jar

# Create configuration file
COPY s3proxy.conf /opt/s3proxy/s3proxy.conf

# Expose port
EXPOSE 8080

# Set working directory
WORKDIR /opt/s3proxy

# Run S3Proxy
CMD ["java", "-jar", "s3proxy.jar", "--properties", "s3proxy.conf"] 