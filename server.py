import contextlib
import json
import logging
import os
import re
from typing import Any

import requests
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from packaging.version import InvalidVersion, parse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from version import __version__

# Configure logging - set root to INFO, only our module to DEBUG
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Reduce noise from FastMCP internals
logging.getLogger("docket").setLevel(logging.WARNING)
logging.getLogger("fakeredis").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.INFO)

# Print version on startup
print(f"Starting releases-mcp server version {__version__}")
logger.info(f"releases-mcp version {__version__}")

# Load environment variables from .env file if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is optional


mcp = FastMCP(
    "Newest Releases",
    instructions="""
        This server retrieves the newest versions from Github and PyPI for products
        and GitHub projects.
        Call get_latest_release() to get up-to-date release versions.
    """,
)

GITHUB_API_BASE = "https://api.github.com"
REPO_MAPPING = {}

# Load repo mapping if available
mapping_file = os.path.join(os.path.dirname(__file__), "repo_mapping.json")
if os.path.exists(mapping_file):
    try:
        with open(mapping_file) as f:
            REPO_MAPPING = json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load repo_mapping.json: {e}")


@mcp.tool()
def get_pypi_version(package_name: str) -> dict:
    """
    Get the latest stable production version of a package from PyPI.

    Args:
        package_name: The name of the package on PyPI (e.g., 'fastapi', 'requests', 'django')
    """
    try:
        return get_latest_pypi_version(package_name)
    except Exception as e:
        return {"error": f"Error: {str(e)}"}


@mcp.tool()
def get_latest_release(product: str, owner: str = "") -> dict:
    """
    Get the latest stable release version of a software package usually hosted on GitHub.

    Args:
        product: The name of the product (e.g., 'Nomad') or a Github repository name (e.g. 'fastapi')
        owner: The owner of the repository (e.g., 'fastapi'). Defaults to empty string if 'product' is a known alias.
    """
    return _get_latest_release_impl(product, owner)


def _get_latest_release_impl(product: str, owner: str = "") -> dict:
    """
    Internal implementation that returns a dict.
    """
    # Store original repo for PyPI fallback lookup
    original_repo = product

    # 1. Resolve alias if owner is missing
    target_repo = product
    if owner == "":
        # A. Check keys
        if product.lower() in REPO_MAPPING:
            entry = REPO_MAPPING[product.lower()]
            # Handle dict structure or legacy string
            full_name = entry.get("repo", "") if isinstance(entry, dict) else entry

            if "/" in full_name:
                owner, target_repo = full_name.split("/", 1)

        # B. Check aliases (case-insensitive)
        if owner == "":
            for _key, entry in REPO_MAPPING.items():
                if isinstance(entry, dict):
                    aliases = [a.lower() for a in entry.get("aliases", [])]
                    if product.lower() in aliases:
                        full_name = entry.get("repo", "")
                        if "/" in full_name:
                            owner, target_repo = full_name.split("/", 1)
                        break

    repo = target_repo

    # 2. Validation
    if not owner:
        return {
            "error": f"Error: Owner is required for repository '{repo}'. Please specify the owner or add '{repo}' to repo_mapping.json."
        }

    try:
        release_info = get_latest_github_release(owner, repo)
        return {
            "name": repo,
            "source": "github",
            "github-repo": f"{owner}/{repo}",
            "version": release_info["tag_name"],
            "published_at": release_info["published_at"],
            "url": release_info["html_url"],
        }
    except Exception as github_error:
        # Try PyPI as a fallback if package_name is available in repo_mapping
        pypi_package = None
        if original_repo.lower() in REPO_MAPPING:
            entry = REPO_MAPPING[original_repo.lower()]
            if isinstance(entry, dict):
                pypi_package = entry.get("pypi_package")

        if pypi_package:
            try:
                pypi_info = get_latest_pypi_version(pypi_package)
                content = {
                    "name": pypi_info["package_name"],
                    "source": "pypi",
                    "version": pypi_info["version"],
                    "summary": pypi_info["summary"],
                    "url": pypi_info["release_url"],
                }
                return content
            except Exception as pypi_error:
                return {
                    "error": f"Error: GitHub lookup failed: {str(github_error)}\nPyPI fallback also failed: {str(pypi_error)}"
                }

        return {"error": f"Error: {str(github_error)}"}


def is_stable_version(tag_name: str) -> bool:
    """
    Checks if a tag name represents a stable version.
    Handles various formats including:
    - Standard semver: 1.2.3, v1.2.3
    - Package@version: n8n@2.4.4, package@1.0.0
    """
    if not tag_name:
        return False

    # Handle package@version format (e.g., n8n@2.4.4)
    if "@" in tag_name:
        tag_name = tag_name.split("@", 1)[1]

    tag = tag_name.lower()

    # Quick filter for common patterns before expensive parsing
    unstable_patterns = [
        r"rc\d*",
        r"alpha",
        r"beta",
        r"dev",
        r"nightly",
        r"preview",
        r"canary",
        r"pre",
        r"enterprise",
        r"ent",
    ]
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
        return tag[0].isdigit() or tag.startswith("v")


def get_latest_pypi_version(package_name: str) -> dict[str, Any]:
    """
    Get the latest stable production version of a package from PyPI.

    Args:
        package_name: The name of the package on PyPI (e.g., 'fastapi', 'requests')

    Returns:
        A dictionary containing version information

    Raises:
        Exception: If the package is not found or there's an error querying PyPI
    """
    url = f"https://pypi.org/pypi/{package_name}/json"
    headers = {"Accept": "application/json", "User-Agent": "releases-mcp-server"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 404:
            raise Exception(f"Package '{package_name}' not found on PyPI")
        response.raise_for_status()

        data = response.json()
        info = data.get("info", {})
        version = info.get("version")

        if not version:
            raise Exception(f"No version information found for package '{package_name}'")

        # Parse version to ensure it's stable
        try:
            v = parse(version)
            if v.is_prerelease or v.is_devrelease:
                # Try to find the latest stable version from releases
                releases = data.get("releases", {})
                stable_versions = []
                for ver in releases:
                    try:
                        parsed_ver = parse(ver)
                        if not parsed_ver.is_prerelease and not parsed_ver.is_devrelease:
                            stable_versions.append(parsed_ver)
                    except InvalidVersion:
                        continue

                if stable_versions:
                    stable_versions.sort(reverse=True)
                    version = str(stable_versions[0])
                    # Refetch info for the stable version
                    info = (
                        data.get("releases", {}).get(version, [{}])[0]
                        if data.get("releases", {}).get(version)
                        else info
                    )
        except InvalidVersion:
            pass  # Use the version as-is if we can't parse it

        return {
            "version": version,
            "name": info.get("name", package_name),
            "summary": info.get("summary", ""),
            "home_page": info.get("home_page", ""),
            "package_url": info.get("package_url", f"https://pypi.org/project/{package_name}/"),
            "release_url": info.get(
                "release_url", f"https://pypi.org/project/{package_name}/{version}/"
            ),
        }
    except requests.RequestException as e:
        raise Exception(f"Failed to query PyPI for package '{package_name}': {str(e)}")


def get_latest_github_release(owner: str, repo: str) -> dict[str, Any]:
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "releases-mcp-server"}

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
                # Handle package@version format (e.g., n8n@2.4.4)
                version_str = tag_name.split("@", 1)[1] if "@" in tag_name else tag_name
                v = parse(version_str)
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
            "body": release.get("body"),
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
                "body": release.get("body"),
            }

    raise Exception(f"No stable release found for {owner}/{repo}")


# Create the FastAPI app from FastMCP
app = mcp.http_app()

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
