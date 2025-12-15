FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create directories
RUN mkdir -p /app/config /app/src

# Copy default application code (will be overridden by volume mounts)
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Create start script that can handle different main.py locations
RUN echo '#!/bin/bash\n\
if [ -f /app/main.py ]; then\n\
    echo "Using volume-mounted main.py"\n\
    exec python /app/main.py\n\
elif [ -f /app/src/main.py ]; then\n\
    echo "Using built-in main.py"\n\
    exec python /app/src/main.py\n\
else\n\
    echo "No main.py found, exiting"\n\
    exit 1\n\
fi' > /app/start.sh && chmod +x /app/start.sh

# Run the start script
CMD ["/app/start.sh"] 