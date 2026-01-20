import os

import pytest
import requests
from dotenv import load_dotenv
from packaging.version import InvalidVersion, parse

from server import get_latest_github_release, get_latest_pypi_version, get_pypi_version

# Load environment variables from .env file if present
load_dotenv()

# List of repositories to test against
# (owner, repo)
TEST_REPOS = [
    ("fastapi", "fastapi"),
    ("astral-sh", "uv"),
    ("hashicorp", "nomad"),
    ("hashicorp", "consul"),
    ("hashicorp", "vault"),
]

def fetch_releases_raw(owner: str, repo: str):
    """
    Helper to fetch releases directly from GitHub for verification.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "releases-mcp-test"
    }
    api_token = os.getenv("GITHUB_TOKEN")
    if api_token:
        headers["Authorization"] = f"token {api_token}"

    response = requests.get(url, headers=headers, allow_redirects=True)
    if response.status_code == 403 and "rate limit" in response.text.lower():
        pytest.skip("GitHub API rate limit exceeded")
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return response.json()

def find_latest_stable_via_packaging(releases):
    """
    Oracle Logic:
    Uses the 'packaging' library to find the highest version that isn't a pre-release.
    This acts as our 'source of truth' to verify the tool's logic.
    """
    valid_versions = []
    for r in releases:
        tag = r.get("tag_name", "")
        if r.get("draft") or r.get("prerelease"):
            continue
            
        try:
            # parsing the tag creates a Version object that handles semantics
            v = parse(tag)
            # We explicitly check for pre-release status in the version object
            if not v.is_prerelease and not v.is_devrelease:
                valid_versions.append((v, tag))
        except InvalidVersion:
            continue
            
    if not valid_versions:
        return None
        
    # Sort by version object (SemVer aware), descending
    valid_versions.sort(key=lambda x: x[0], reverse=True)
    return valid_versions[0][1]

@pytest.mark.parametrize("owner, repo", TEST_REPOS)
def test_latest_release_matches_semver_oracle(owner, repo):
    """
    Verifies that get_latest_github_release returns the same version 
    as a strict SemVer search using the 'packaging' library.
    """
    print(f"\nTesting {owner}/{repo}...")
    
    # 1. Get the result from our tool
    try:
        tool_result = get_latest_github_release(owner, repo)
        tool_version = tool_result["tag_name"]
    except Exception as e:
        if "403" in str(e) and "rate limit" in str(e).lower():
            pytest.skip("GitHub API rate limit exceeded during tool execution")
        pytest.fail(f"Tool failed to fetch release: {e}")

    # 2. Oracle: Fetch raw releases and calculate what WE think is the latest
    raw_releases = fetch_releases_raw(owner, repo)
    oracle_version = find_latest_stable_via_packaging(raw_releases)
    
    if oracle_version is None:
        pytest.skip(f"Could not calculate stable version for {owner}/{repo} (maybe no stable releases?)")

    print(f"Tool: {tool_version} | Oracle: {oracle_version}")

    # 3. Assertions
    # We expect the tool to satisfy one of two conditions:
    # A) It matches the Oracle exactly
    # B) It found something valid that our strict Oracle missed (or vice versa), 
    #    but let's start with strict equality.
    
    # Note: Sometimes tags have 'v' prefix and sometimes not. 
    # Let's normalize for comparison if needed, but usually they are consistent within a repo.
    assert tool_version == oracle_version, \
        f"Tool picked {tool_version} but Oracle (packaging lib) picked {oracle_version}"

    # 4. Property Checks
    # Even if it matches, let's verify checking specific properties
    assert "https://" in tool_result["html_url"]
    assert tool_result["name"] is not None


def test_get_latest_release_tool_alias():
    """
    Test the tool wrapper handles aliases correctly (e.g. 'vault' -> 'hashicorp/vault').
    """
    # Need to import the tool function which is adorned with @mcp.tool()
    # In main.py: def get_latest_release(repo: str, owner: str | None = None) -> str:
    from server import get_latest_release
    
    # We call it with just the alias
    result = get_latest_release(product="vault")
    
    # We expect success, meaning it found hashicorp/vault
    # Since we can't easily mock the internal call without restructuring, 
    # we just check if it returns a string that looks like a success message, 
    # or at least DOES NOT return an "error" key
    assert "error" not in result
    assert "version" in result
    assert result["github-repo"] == "hashicorp/vault"


def test_get_latest_release_human_input():
    """
    Test the tool wrapper handles aliases correctly (e.g. 'vault' -> 'hashicorp/vault').
    """
    # Need to import the tool function which is adorned with @mcp.tool()
    # In main.py: def get_latest_release(repo: str, owner: str | None = None) -> str:
    from server import get_latest_release
    
    # We call it with just the alias
    result = get_latest_release(product="Vault", owner="")

    # We expect success, meaning it found hashicorp/vault
    # Since we can't easily mock the internal call without restructuring, 
    # we just check if it returns a string that looks like a success message, 
    # or at least DOES NOT return an "error" key
    assert "error" not in result
    assert "version" in result
    assert result["github-repo"] == "hashicorp/vault"

def test_get_latest_release_human_alias():
    """
    Test the tool wrapper handles human readable aliases (e.g. 'Nomad' -> 'hashicorp/nomad').
    """
    from server import get_latest_release
    
    # We call it with a capitalized Alias
    result = get_latest_release(product="Nomad")
    
    assert "error" not in result
    assert "version" in result
    assert result["github-repo"] == "hashicorp/nomad"

def test_invalid_repo_handled():
    try:
        get_latest_github_release("fake-owner-123", "fake-repo-456")
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            assert True  # Expected behavior
        elif "403" in str(e) and "rate limit" in str(e).lower():
            pytest.skip("GitHub API rate limit exceeded during invalid repo test")
        else:
            raise e
    except requests.HTTPError as e:
        if e.response.status_code == 403 and "rate limit" in str(e).lower():
            pytest.skip("GitHub API rate limit exceeded during invalid repo test")
        raise e


# PyPI Tests

PYPI_TEST_PACKAGES = [
    "requests",
    "fastapi", 
    "django",
    "flask",
    "numpy",
]

@pytest.mark.parametrize("package_name", PYPI_TEST_PACKAGES)
def test_get_latest_pypi_version(package_name):
    """
    Test that get_latest_pypi_version returns valid version information for known packages.
    """
    print(f"\nTesting PyPI package {package_name}...")
    
    result = get_latest_pypi_version(package_name)
    
    # Verify all expected fields are present
    assert "version" in result
    assert "name" in result
    assert "summary" in result
    assert "package_url" in result
    assert "release_url" in result
    
    # Verify version is not empty and can be parsed
    assert result["version"]
    version = parse(result["version"])
    
    # Verify it's a stable version (not pre-release or dev)
    assert not version.is_prerelease, f"Expected stable version, got pre-release: {result['version']}"
    assert not version.is_devrelease, f"Expected stable version, got dev release: {result['version']}"
    
    # Verify URLs are properly formed
    assert "https://pypi.org/project/" in result["release_url"]
    
    print(f"Package: {result['name']}, Version: {result['version']}")


def test_pypi_version_tool_wrapper():
    """
    Test the get_pypi_version MCP tool wrapper returns formatted string.
    """
    result = get_pypi_version("requests")
    
    # Should return a dict
    assert isinstance(result, dict)
    assert "name" in result
    assert "version" in result
    assert result["name"].lower() == "requests"


def test_pypi_nonexistent_package():
    """
    Test that get_latest_pypi_version handles non-existent packages gracefully.
    """
    with pytest.raises(Exception) as exc_info:
        get_latest_pypi_version("this-package-definitely-does-not-exist-12345")
    
    assert "not found" in str(exc_info.value).lower()


def test_pypi_version_is_stable():
    """
    Test that PyPI function filters out pre-release versions correctly.
    """
    # Test with a well-known package that has stable releases
    result = get_latest_pypi_version("requests")
    version = parse(result["version"])
    
    # Should be a stable version
    assert not version.is_prerelease
    assert not version.is_devrelease
    
    # Version should be reasonable (major version >= 2 for requests as of 2026)
    assert version.major >= 2


def test_github_fallback_to_pypi():
    """
    Test that get_latest_release falls back to PyPI when GitHub fails and pypi_package is configured.
    Note: This test requires adding a test entry to repo_mapping.json or mocking.
    For now, we test the function behavior with a real package.
    """
    from server import get_latest_release, REPO_MAPPING
    
    # Temporarily add a test entry to REPO_MAPPING
    original_mapping = REPO_MAPPING.copy()
    REPO_MAPPING["test-pypi-fallback"] = {
        "repo": "nonexistent-owner/nonexistent-repo",
        "pypi_package": "requests"
    }
    
    try:
        result = get_latest_release("test-pypi-fallback")
        
        # Should have fallen back to PyPI
        assert "error" in result
        assert "PyPI" in result["error"]
        assert "fallback" in result["error"].lower()
        
    finally:
        # Restore original mapping
        REPO_MAPPING.clear()
        REPO_MAPPING.update(original_mapping)

