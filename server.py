from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from packaging.version import parse, InvalidVersion
from typing import Any
import requests
import json
import re
import os


mcp = FastMCP("GitHub Releases")

GITHUB_API_BASE = "https://api.github.com"
REPO_MAPPING = {}

# Load repo mapping if available
mapping_file = os.path.join(os.path.dirname(__file__), "repo_mapping.json")
if os.path.exists(mapping_file):
    try:
        with open(mapping_file, "r") as f:
            REPO_MAPPING = json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load repo_mapping.json: {e}")


def is_stable_version(tag_name: str) -> bool:
    """
    Checks if a tag name represents a stable version.
    """
    if not tag_name:
        return False
        
    tag = tag_name.lower()
    
    # Quick filter for common patterns before expensive parsing
    unstable_patterns = [r"rc\d*", r"alpha", r"beta", r"dev", r"nightly", r"preview", r"canary", r"pre", r"enterprise", r"ent"]
    for pattern in unstable_patterns:
        if re.search(pattern, tag):
            return False
            
    # Try strict parsing if possible
    try:
        v = parse(tag_name)
        if v.is_prerelease or v.is_devrelease:
            return False
        return True
    except InvalidVersion:
        # Fallback to regex heuristics if packaging can't parse it
        return tag[0].isdigit() or tag.startswith('v')


def get_latest_github_release(owner: str, repo: str) -> dict[str, Any]:
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "releases-mcp-server"
    }
    
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    response = requests.get(url, headers=headers, allow_redirects=True)
    if response.status_code == 404:
        raise Exception(f"Repository {owner}/{repo} not found")
    response.raise_for_status()
    
    releases = response.json()
    candidates: list[tuple[Any, dict[str, Any]]] = []

    for release in releases:
        tag_name = release.get("tag_name", "")
        is_draft = release.get("draft", False)
        is_prerelease = release.get("prerelease", False)
        
        if not is_draft and not is_prerelease and is_stable_version(tag_name):
            try:
                v = parse(tag_name)
                candidates.append((v, release))
            except InvalidVersion:
                # If we can't parse it, we can't reliably sort it against others.
                # We could include it with a dummy logic or skip.
                # For now, let's treat it as a valid candidate but use published_at for sorting?
                # Or skipping for robustness.
                continue
    
    if candidates:
        # Sort by version strictly
        candidates.sort(key=lambda x: x[0], reverse=True)
        release = candidates[0][1]
        return {
            "tag_name": release.get("tag_name"),
            "name": release.get("name"),
            "published_at": release.get("published_at"),
            "html_url": release.get("html_url"),
            "body": release.get("body")
        }
            
    # If no release found in the list, try the /latest endpoint
    # ... fallback logic remains ...
    latest_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases/latest"
    response = requests.get(latest_url, headers=headers, allow_redirects=True)
    if response.status_code == 200:
        release = response.json()
        tag_name = release.get("tag_name", "")
        if is_stable_version(tag_name):
            return {
                "tag_name": tag_name,
                "name": release.get("name"),
                "published_at": release.get("published_at"),
                "html_url": release.get("html_url"),
                "body": release.get("body")
            }

    raise Exception(f"No stable release found for {owner}/{repo}")

@mcp.tool()
def get_latest_release(repo: str, owner: str | None = None) -> str:
    """
    Get the latest stable release version of a GitHub repository.
    
    Args:
        repo: The name of the repository (e.g., 'fastapi') or a known product alias (e.g. 'nomad')
        owner: The owner of the repository (e.g., 'fastapi'). Optional if 'repo' is a known alias.
    """
    # 1. Resolve alias if owner is missing
    target_repo = repo
    if not owner:
        # A. Check keys
        if repo.lower() in REPO_MAPPING:
             entry = REPO_MAPPING[repo.lower()]
             # Handle dict structure or legacy string
             if isinstance(entry, dict):
                 full_name = entry.get("repo", "")
             else:
                 full_name = entry
             
             if "/" in full_name:
                owner, target_repo = full_name.split("/", 1)
        
        # B. Check aliases (case-insensitive)
        if not owner:
            for key, entry in REPO_MAPPING.items():
                if isinstance(entry, dict):
                    aliases = [a.lower() for a in entry.get("aliases", [])]
                    if repo.lower() in aliases:
                        full_name = entry.get("repo", "")
                        if "/" in full_name:
                            owner, target_repo = full_name.split("/", 1)
                        break

    repo = target_repo

    # 2. Validation
    if not owner:
         return f"Error: Owner is required for repository '{repo}'. Please specify the owner or add '{repo}' to repo_mapping.json."

    try:
        release_info = get_latest_github_release(owner, repo)
        content = (
            f"Latest stable release for {owner}/{repo}:\n"
            f"Version: {release_info['tag_name']}\n"
            f"Name: {release_info['name']}\n"
            f"Published at: {release_info['published_at']}\n"
            f"URL: {release_info['html_url']}\n"
        )
        return content
    except Exception as e:
        return f"Error: {str(e)}"

app = FastAPI()
app.mount("/", mcp.sse_app())
