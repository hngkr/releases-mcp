# Build stage - install dependencies with uv
FROM python:3.14-alpine AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Runtime stage - minimal image without uv
FROM python:3.14-alpine

WORKDIR /app

# Copy only the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY server.py version.py repo_mapping.json ./

EXPOSE 8000

# Run with the virtual environment
CMD ["/app/.venv/bin/uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "debug", "--proxy-headers", "--forwarded-allow-ips", "*"]
