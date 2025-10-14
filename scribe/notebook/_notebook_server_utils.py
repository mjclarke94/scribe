import base64
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests
from fastmcp.utilities.types import Image
from ._image_processing_utils import resize_image_if_needed


def find_safe_port(start_port=20000, max_port=30000):
    """Find a port that's not in use by anyone.

    Uses random selection to minimize conflicts between users.

    Args:
        start_port: Minimum port number (default: 20000)
        max_port: Maximum port number (default: 30000)

    Returns:
        int: Available port number, or None if none found
    """
    import socket
    import random

    # Try random ports first (more efficient and less likely to conflict)
    ports_to_try = list(range(start_port, max_port + 1))
    random.shuffle(ports_to_try)

    # Try up to 100 random ports
    for port in ports_to_try[:100]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            # Port in use
            continue

    return None


def clean_notebook_for_save(nb):
    """Remove cell IDs and other properties that cause validation warnings."""
    for cell in nb.cells:
        try:
            if hasattr(cell, "id"):
                delattr(cell, "id")
        except AttributeError:
            # Some notebook node types don't support attribute deletion
            pass
    return nb


def check_server_health(port: int) -> Optional[Dict[str, Any]]:
    """Check if scribe server is running on given port."""
    try:
        url = f"http://127.0.0.1:{port}/api/scribe/health"
        response = requests.get(url, timeout=1)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception:
        return None


def start_scribe_server(
    port: int, token: str, notebook_output_dir: Optional[str] = None
) -> subprocess.Popen:
    """Start a Scribe Jupyter server subprocess.

    Args:
        port: Port number to run server on
        token: Authentication token for the server
        notebook_output_dir: Optional directory for storing notebooks

    Returns:
        subprocess.Popen: The running server process

    Raises:
        Exception: If server fails to start or become ready
    """
    # Start the server process using module import
    cmd = [
        sys.executable,
        "-m",
        "scribe.notebook.notebook_server",
        f"--port={port}",
        "--no-browser",
        "--allow-root",
        f"--ServerApp.token={token}",  # Use provided token for auth
        "--ServerApp.password=",  # No password (empty value)
        "--ServerApp.disable_check_xsrf=True",  # Disable CSRF for API calls
    ]

    # Add notebook output directory if specified
    if notebook_output_dir:
        cmd.extend(["--ScribeServerApp.notebooks_dir", notebook_output_dir])

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    url = f"http://127.0.0.1:{port}"

    # Wait for server to be ready
    max_attempts = 30  # 30 seconds
    for _ in range(max_attempts):
        # Check if process crashed
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise Exception(f"Jupyter server process crashed. STDERR: {stderr[:500]}")

        try:
            response = requests.get(f"{url}/api/scribe/health", timeout=1)
            if response.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        # Server didn't start successfully
        process.terminate()
        process.wait()
        raise Exception(f"Jupyter server failed to start on port {port}")

    return process


def cleanup_scribe_server(process: subprocess.Popen) -> None:
    """Clean up a Scribe Jupyter server process.

    Args:
        process: The server process to clean up
    """
    if process:
        print("Shutting down managed Jupyter server...", file=sys.stderr)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def build_scribe_docker_image() -> str:
    """Build the Scribe Docker image if it doesn't exist.

    Returns:
        str: Image name/tag

    Raises:
        Exception: If Docker is not available or build fails
    """
    image_name = "scribe-jupyter:latest"

    # Check if Docker is available
    try:
        subprocess.run(
            ["docker", "version"],
            capture_output=True,
            check=True,
            timeout=5,
            env=os.environ.copy()  # Inherit environment variables including PATH
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise Exception(
            f"Docker is not available: {type(e).__name__}. "
            "Please ensure Docker/colima is running or run without --container flag. "
            f"Try running 'docker version' manually to verify."
        )

    # Check if image already exists
    result = subprocess.run(
        ["docker", "images", "-q", image_name],
        capture_output=True,
        text=True,
        env=os.environ.copy()
    )

    if result.stdout.strip():
        print(f"✓ Using existing Docker image: {image_name}", file=sys.stderr)
        return image_name

    # Build the image
    print(f"🔨 Building Docker image: {image_name}...", file=sys.stderr)

    # Find the Dockerfile in the scribe package directory
    # Try package root first (development), then scribe package dir (installed)
    scribe_root = Path(__file__).parent.parent.parent
    dockerfile_path = scribe_root / "Dockerfile"

    if not dockerfile_path.exists():
        # Try in the scribe package directory (for installed packages)
        dockerfile_path = Path(__file__).parent.parent / "Dockerfile"

    if not dockerfile_path.exists():
        raise Exception(
            f"Dockerfile not found. Checked:\n"
            f"  - {scribe_root / 'Dockerfile'}\n"
            f"  - {Path(__file__).parent.parent / 'Dockerfile'}\n"
            "Please ensure scribe is properly installed."
        )

    # Build context should be the directory containing the Dockerfile
    build_context = dockerfile_path.parent

    try:
        subprocess.run(
            ["docker", "build", "-t", image_name, "-f", str(dockerfile_path), str(build_context)],
            check=True,
            timeout=300,  # 5 minute timeout for build
            env=os.environ.copy()
        )
        print(f"✓ Docker image built successfully", file=sys.stderr)
        return image_name
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to build Docker image: {e}")
    except subprocess.TimeoutExpired:
        raise Exception("Docker build timed out after 5 minutes")


def start_scribe_server_container(
    port: int,
    token: str,
    notebook_output_dir: Optional[str] = None,
    project_dir: Optional[str] = None,
    memory_limit: Optional[str] = None,
    cpu_limit: Optional[str] = None,
) -> str:
    """Start a Scribe Jupyter server in a Docker container.

    Args:
        port: Port number to run server on
        token: Authentication token for the server
        notebook_output_dir: Optional directory for storing notebooks
        project_dir: Project directory to mount (defaults to cwd)
        memory_limit: Optional memory limit (e.g., "2g", "512m")
        cpu_limit: Optional CPU limit (e.g., "1.0", "0.5")

    Returns:
        str: Container ID

    Raises:
        Exception: If container fails to start or become ready
    """
    # Build image if needed
    image_name = build_scribe_docker_image()

    # Determine directories
    if project_dir is None:
        project_dir = os.getcwd()
    project_dir = os.path.abspath(project_dir)

    if notebook_output_dir is None:
        notebook_output_dir = os.path.join(project_dir, "notebooks")
    else:
        notebook_output_dir = os.path.abspath(notebook_output_dir)

    # Ensure notebooks directory exists
    os.makedirs(notebook_output_dir, exist_ok=True)

    # Build docker run command
    docker_cmd = [
        "docker", "run",
        "-d",  # Detached mode
        "-p", f"{port}:8888",  # Port mapping
        "-v", f"{project_dir}:/workspace",  # Project directory
        "-v", f"{notebook_output_dir}:/notebooks",  # Notebooks directory
        "-v", "/workspace/.venv",  # Anonymous volume to shadow host .venv (macOS binaries incompatible)
        "-e", f"JUPYTER_TOKEN={token}",  # Auth token
        "--name", f"scribe-jupyter-{port}",  # Container name
    ]

    # Add resource limits if specified
    if memory_limit:
        docker_cmd.extend(["-m", memory_limit])
    if cpu_limit:
        docker_cmd.extend(["--cpus", cpu_limit])

    # Add server arguments
    docker_cmd.extend([
        image_name,
        f"--port=8888",  # Internal port (mapped to host port)
        "--ip=0.0.0.0",  # Bind to all interfaces for Docker port forwarding
        "--no-browser",
        "--allow-root",
        f"--ServerApp.token={token}",
        "--ServerApp.password=",
        "--ServerApp.disable_check_xsrf=True",
        "--ScribeServerApp.notebooks_dir=/notebooks",
    ])

    print(f"🐳 Starting Scribe Jupyter server in container...", file=sys.stderr)
    print(f"   Project: {project_dir}", file=sys.stderr)
    print(f"   Notebooks: {notebook_output_dir}", file=sys.stderr)

    # Start container
    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
            env=os.environ.copy()
        )
        container_id = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to start Docker container: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise Exception("Docker container start timed out")

    # Wait for server to be ready
    url = f"http://127.0.0.1:{port}"
    max_attempts = 60  # 60 seconds (includes uv sync time)

    print(f"⏳ Waiting for container to be ready (this may take a moment for uv sync)...", file=sys.stderr)

    for attempt in range(max_attempts):
        # Check if container is still running
        check_result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"id={container_id}"],
            capture_output=True,
            text=True,
            env=os.environ.copy()
        )

        if not check_result.stdout.strip():
            # Container died, get logs
            logs_result = subprocess.run(
                ["docker", "logs", container_id],
                capture_output=True,
                text=True,
                env=os.environ.copy()
            )

            # Clean up the stopped container
            subprocess.run(
                ["docker", "rm", container_id],
                capture_output=True,
                env=os.environ.copy()
            )

            error_msg = f"Docker container exited unexpectedly.\n\nContainer logs:\n{logs_result.stdout}"
            if logs_result.stderr:
                error_msg += f"\n\nStderr:\n{logs_result.stderr}"

            raise Exception(error_msg)

        # Check if server is responding
        try:
            response = requests.get(f"{url}/api/scribe/health", timeout=1)
            if response.status_code == 200:
                print(f"✓ Container ready!", file=sys.stderr)
                return container_id
        except requests.RequestException:
            pass

        time.sleep(1)

    # Timeout - get logs and clean up
    logs_result = subprocess.run(
        ["docker", "logs", container_id],
        capture_output=True,
        text=True,
        env=os.environ.copy()
    )
    subprocess.run(["docker", "stop", container_id], capture_output=True, env=os.environ.copy())
    subprocess.run(["docker", "rm", container_id], capture_output=True, env=os.environ.copy())

    error_msg = f"Container failed to become ready after {max_attempts} seconds.\n\nContainer logs:\n{logs_result.stdout}"
    if logs_result.stderr:
        error_msg += f"\n\nStderr:\n{logs_result.stderr}"
    raise Exception(error_msg)


def cleanup_scribe_server_container(container_id: str) -> None:
    """Clean up a Scribe Jupyter server Docker container.

    Args:
        container_id: The container ID to clean up
    """
    if container_id:
        print("🐳 Shutting down Docker container...", file=sys.stderr)
        try:
            subprocess.run(
                ["docker", "stop", container_id],
                capture_output=True,
                timeout=10,
                check=True,
                env=os.environ.copy()
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Force kill if stop fails
            subprocess.run(
                ["docker", "kill", container_id],
                capture_output=True,
                env=os.environ.copy()
            )

        # Remove the container
        subprocess.run(
            ["docker", "rm", container_id],
            capture_output=True,
            env=os.environ.copy()
        )


def process_jupyter_outputs(
    outputs: List[Dict[str, Any]],
    session_id: Optional[str] = None,
    save_images_locally: bool = False,
    provider: str = None,
) -> Tuple[List[Dict[str, Any]], List[Image]]:
    """Process Jupyter notebook outputs into MCP format.

    Args:
        outputs: Raw Jupyter notebook output data
        session_id: Session ID for saving images (required if save_images_locally=True)
        save_images_locally: If True, save images to temp directory and return file paths

    Returns:
        Tuple of (processed_outputs, images)
        - If save_images_locally=False: images contains fastmcp.Image objects
        - If save_images_locally=True: processed_outputs contains image file paths, images is empty
    """
    processed_outputs = []
    images = []
    image_count = 0

    for output in outputs:
        if output["output_type"] == "stream":
            processed_outputs.append(
                {"type": "text", "content": output["text"].strip()}
            )
        elif output["output_type"] == "execute_result":
            # Handle different MIME types
            if "image/png" in output.get("data", {}):
                img_data = base64.b64decode(output["data"]["image/png"])
                # Resize image if needed to prevent 413 errors
                resized_img_data = resize_image_if_needed(img_data)
                # Convert resized PNG data to Image object
                image = Image(data=resized_img_data)
                images.append(image)
            elif "text/plain" in output["data"]:
                processed_outputs.append(
                    {"type": "result", "content": output["data"]["text/plain"]}
                )
        elif output["output_type"] == "display_data":
            # Handle display data (like images from .show())
            if "image/png" in output.get("data", {}):
                img_data = base64.b64decode(output["data"]["image/png"])
                # Resize image if needed to prevent 413 errors
                resized_img_data = resize_image_if_needed(img_data)
                # Convert resized PNG data to Image object
                image = Image(data=resized_img_data)
                images.append(image)
            elif "text/plain" in output.get("data", {}):
                processed_outputs.append(
                    {"type": "display", "content": output["data"]["text/plain"]}
                )
        elif output["output_type"] == "error":
            # Clean up traceback by removing ANSI escape codes
            cleaned_traceback = []
            for line in output["traceback"]:
                # Remove ANSI escape sequences
                clean_line = re.sub(r"\x1b\[[0-9;]*m", "", line)
                cleaned_traceback.append(clean_line)

            processed_outputs.append(
                {
                    "type": "error",
                    "name": output["ename"],
                    "message": output["evalue"],
                    "traceback": cleaned_traceback,
                }
            )

    return processed_outputs, images
