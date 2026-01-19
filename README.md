# MCP Releases Server

An MCP (Model Context Protocol) server that provides GitHub release information.

## Tools

- `get_latest_release` - Returns the latest stable release version of a GitHub repository

## Running with Docker

```bash
docker-compose up --build
```

The server will be available at `http://localhost:8000/sse`.

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
        "url": "http://localhost:8000/sse"
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
      "url": "http://localhost:8000/sse"
    }
  }
}
```

After adding the configuration, restart VSCode or reload the window. The `get_latest_release` tool will be available to Copilot.

## Running Integration Tests

To run the integration suite using `pytest` (dependencies are handled ephemerally by `uv`). We add `python-dotenv` to load the `GITHUB_TOKEN` from a `.env` file:

```bash
uv run --with pytest --with python-dotenv pytest -s test_integration.py
```
