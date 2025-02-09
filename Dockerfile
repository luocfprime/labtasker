FROM python:3.13.1-slim-bullseye

WORKDIR /app

# Install system dependencies and clean up in one layer
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pip --upgrade

# Copy project files first
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir "."

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${API_PORT:-8080}/health || exit 1

# Run the application
CMD ["python", "-m", "labtasker.server.run"]
