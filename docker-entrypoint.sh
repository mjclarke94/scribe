#!/bin/bash
set -e

echo "🐳 Container starting..."

# Check if we have a pyproject.toml (uv project)
if [ -f "/workspace/pyproject.toml" ]; then
    echo "📦 Found pyproject.toml, running uv sync..."
    cd /workspace

    # Try with --frozen first, fall back to regular sync if no lockfile
    if [ -f "uv.lock" ]; then
        echo "   Using uv.lock (frozen)"
        uv sync --frozen
    else
        echo "   No uv.lock found, running uv sync (may take longer)"
        uv sync
    fi

    # Make sure the venv Python is available
    export PATH="/workspace/.venv/bin:$PATH"
    export UV_PROJECT_ENVIRONMENT="/workspace/.venv"
    export JUPYTER_IN_CONTAINER="1"

    # Install ipykernel in the venv (needed for kernel to work properly)
    echo "🔧 Setting up ipykernel in project environment..."
    uv pip install ipykernel jupyter-client

    # Verify venv Python is available
    echo "   Python location: $(which python)"
    echo "   Python version: $(python --version)"

    # Override the default python3 kernel to use our venv Python
    echo "   Registering venv kernel as default python3 kernel..."
    /workspace/.venv/bin/python -m ipykernel install --prefix=/usr/local --name=python3 --display-name="Python 3 (venv)"

    # Verify kernel was registered
    if [ -f "/usr/local/share/jupyter/kernels/python3/kernel.json" ]; then
        echo "   ✓ Kernel registered successfully"
        cat /usr/local/share/jupyter/kernels/python3/kernel.json
    else
        echo "   ⚠️  Warning: Kernel registration may have failed"
    fi

    # Start Jupyter server using the synced environment
    echo "🚀 Starting Jupyter server with project environment..."
    exec uv run python -m scribe.notebook.notebook_server "$@"
else
    echo "⚠️  No pyproject.toml found"
    echo "   Container mode requires a uv-based project with scribe as a dependency"
    exit 1
fi
