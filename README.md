# Scribe — Jupyter Server + Notebooks for CLI Agents
Give Claude Code, Codex, and Gemini CLI agents access to Jupyter servers + notebooks.

## Installation

```bash
# Install from GitHub using uv
uv add git+https://github.com/goodfire-ai/scribe.git
```

### Development Installation

For local development with editable install:

```bash
# Clone the repository
git clone https://github.com/goodfire-ai/scribe.git

# From your project directory, install scribe in editable mode
uv add --editable /path/to/scribe
```

## Usage  
Once installed, you can run the `scribe` command from within your virtual environment.  

This command will launch a CLI agent (the default is Claude Code, but you can update `DEFAULT_PROVIDER` in [constants.py](scribe/cli/constants.py)) with a notebook MCP server automatically enabled. Behind the scenes, a Jupyter server has been started and the agent has tools to run code that will be executed in an IPython kernel. The scribe server sits in between the agent and the Jupyter kernel, passing input code to the kernel and automatically writing all input code + kernel outputs (text, errors, images, etc.) to a Jupyter notebook.  

To specify a particular CLI agent, use `scribe claude`, `scribe codex`, or `scribe gemini`. These commands wrap calls to the underlying CLI agents — they will use your default auth method and other configurations, and you can pass CLI flags (e.g. `scribe claude -c` to continue a session).    


#### Start a new session
Once you've launched the CLI agent, ask it to start a new session. This will create a `notebooks/` directory wherever you launched the `scribe` command from, and will create a notebook with the current timestamp and a name provided by the agent.
```
You: Start a new session for us to run some experiments on GPT-2.

Agent: I'll start a new Scribe session for image generation. [Tool call]

Agent: Session started successfully! I've created a new notebook at notebooks/2025-01-09-10-30_GPT-2_Experiments.ipynb. Where should we begin?
```

## Containerized Execution (Security)

For enhanced security, you can run the Jupyter kernel in a Docker container. This provides isolation from your host system while still giving the kernel access to your project's dependencies.

### Requirements
- Docker installed and running
- A `pyproject.toml` file in your project directory (uv-based project)

### Usage

```bash
# Run with containerized kernel
scribe claude --container

# With resource limits
scribe claude --container --memory-limit 2g --cpu-limit 1.0

# Specify a custom project directory
scribe claude --container --project-dir /path/to/project
```

### How it works

When `--container` is enabled:
1. A Docker image is built (cached after first build) with Python, uv, and Jupyter
2. Your project directory is mounted into the container
3. `uv sync` runs inside the container to install your project's dependencies (with native Linux binaries)
4. The Jupyter server starts inside the container with full access to your synced environment
5. Notebooks are saved to your host filesystem (mounted as a volume)

**Benefits:**
- **Filesystem isolation**: Code execution is isolated from your host system
- **Resource limits**: Optional CPU and memory constraints
- **Dependency isolation**: Packages are installed in the container, not on your host
- **Easy cleanup**: Simply stop the container to remove all execution artifacts

**Limitations:**
- Slightly slower first startup (Docker build + uv sync)
- Requires Docker to be installed and running
- Project must use uv for dependency management

## Automatic MCP Permissions
**Claude Code**  
When running `scribe claude`, Claude Code is launched with a command-line argument that enables the MCP server and automatically enables most specific tool calls (e.g. starting a new session and executing code).  

**Codex**  
When running `scribe codex`, Codex is launched with a command-line argument that enables the MCP server using the `--config` flag [documented here](https://github.com/openai/codex/blob/main/docs/config.md).  

**Gemini CLI**  
When running `scribe gemini`, a `.gemini/settings.json` file is created (or updated if one already exists) with settings prepopulated to enable the MCP server with tool calls automatically enabled.  

## Security Note
Agents can execute arbitrary Python code via the Jupyter kernel. For production use or when working with untrusted code, use the `--container` flag to run the kernel in an isolated Docker container. See the [Containerized Execution](#containerized-execution-security) section above for details.  
