FROM python:3.11-slim

# Install git and essential system build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Trust all workspace directories mounted into the container to bypass dubious ownership errors
RUN git config --system --add safe.directory "*"

WORKDIR /app

# Copy dependency specifications and install packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ /app/src/

# Ensure src modules are resolvable by Python
ENV PYTHONPATH=/app

# Execute runner entrypoint
ENTRYPOINT ["python", "-m", "src.runner"]