FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set up working directory
WORKDIR /workspace

# Install Jupyter globally (the server itself runs from system Python)
# but kernels will be installed in the venv
RUN uv pip install --system jupyter-server jupyter-client nbformat

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/workspace/.venv

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
