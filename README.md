# MCP Releases Server

An MCP (Model Context Protocol) server that provides GitHub release information and PyPI package versions.

## Features

- **GitHub Releases**: Query the latest stable release from any GitHub repository
- **PyPI Integration**: Look up the latest production version of Python packages
- **Smart Fallback**: Automatically falls back to PyPI when GitHub releases aren't available
- **Repository Aliases**: Configure short aliases for commonly used repositories

## Tools

- `get_latest_release` - Returns the latest stable release version of a GitHub repository (with PyPI fallback)
- `get_pypi_version` - Directly query PyPI for the latest stable version of any Python package

## Configuration

### Environment Variables

Create an optional `.env` file in the project root to configure the GitHub token:

```bash
export GITHUB_TOKEN="github_pat_TOKEN"
```

The GitHub token is optional but recommended to avoid API rate limits. The server will work without it, but with lower rate limits.

### Repository Mapping

Configure repository aliases and PyPI packages in `repo_mapping.json`:

```json
{
  "fastapi": {
    "repo": "tiangolo/fastapi",
    "aliases": ["FastAPI"],
    "pypi_package": "fastapi"
  },
  "nomad": {
    "repo": "hashicorp/nomad",
    "aliases": ["Nomad"]
  }
}
```

**Fields:**
- `repo`: GitHub repository in `owner/name` format (required)
- `aliases`: List of alternative names for this repository (optional)
- `pypi_package`: PyPI package name for fallback lookups (optional)

## Running with Docker

```bash
docker-compose up --build
```

The server will be available at `http://localhost:8000/mcp`.

## Running Locally

```bash
uv sync
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

## VSCode Integration

Add the following to your VSCode settings (`.vscode/mcp.json` or user settings):

```json
{
  "mcp": {
    "servers": {
      "releases-server": {
        "url": "http://localhost:8000/mcp"
      }
    }
  }
}
```

Or add to `~/.vscode/mcp.json`:

```json
{
  "servers": {
    "releases-server": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

After adding the configuration, restart VSCode or reload the window. The `get_latest_release` and `get_pypi_version` tools will be available to Copilot.

## PyPI Integration

### How It Works

The server includes two ways to query PyPI:

1. **Direct PyPI Lookup**: Use `get_pypi_version()` to directly query PyPI for any package
2. **Automatic Fallback**: When `get_latest_release()` can't find a GitHub release, it automatically checks PyPI if a `pypi_package` is configured in `repo_mapping.json`

### PyPI Features

- Filters out pre-release and dev versions
- Returns only stable production versions
- Includes package metadata (summary, homepage, URLs)
- Handles non-existent packages gracefully

### Usage Examples

**Direct PyPI lookup:**
```python
from server import get_pypi_version

# Query any package directly
result = get_pypi_version("django")
print(result)
# Output:
# Latest stable version for django (from PyPI):
# Version: 6.0.1
# Summary: A high-level Python web framework...
# PyPI URL: https://pypi.org/project/django/6.0.1/
```

**With automatic fallback:**
```python
from server import get_latest_release

# Configure in repo_mapping.json:
# {
#   "my-package": {
#     "repo": "owner/repo",
#     "pypi_package": "my-package"
#   }
# }

# If GitHub fails, automatically falls back to PyPI
result = get_latest_release("my-package")
```

**Test PyPI integration:**
```bash
uv run python3 -c "
from server import get_latest_pypi_version
result = get_latest_pypi_version('requests')
print(f\"Version: {result['version']}\")
"
```

## Running Integration Tests

To run the integration suite using `pytest` (dependencies are handled ephemerally by `uv`). The tests will automatically load the `GITHUB_TOKEN` from your `.env` file if present:

```bash
uv run pytest test_integration.py -v
```

Or run specific test categories:

```bash
# Test GitHub functionality
uv run pytest test_integration.py -k "github" -v

# Test PyPI functionality
uv run pytest test_integration.py -k "pypi" -v

# Test with verbose output
uv run pytest test_integration.py -v -s
```
