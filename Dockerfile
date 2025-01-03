FROM python:3.8-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# Copy application code
COPY labtasker/ labtasker/

# Run the application
CMD ["python", "-m", "labtasker.server"]
