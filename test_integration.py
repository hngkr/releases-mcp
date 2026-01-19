import pytest
import requests
import os
from packaging.version import parse, InvalidVersion
from server import get_latest_github_release, is_stable_version
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# List of repositories to test against
# (owner, repo)
TEST_REPOS = [
    ("fastapi", "fastapi"),
    ("encode", "uvicorn"),
    ("pydantic", "pydantic"),
    ("astral-sh", "uv"),
    ("encode", "httpx"),
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
    Test the tool wrapper handles aliases correctly (e.g. 'nomad' -> 'hashicorp/nomad').
    """
    # Need to import the tool function which is adorned with @mcp.tool()
    # In main.py: def get_latest_release(repo: str, owner: str | None = None) -> str:
    from server import get_latest_release
    
    # We call it with just the alias
    result = get_latest_release(repo="nomad")
    
    # We expect success, meaning it found hashicorp/nomad
    # Since we can't easily mock the internal call without restructuring, 
    # we just check if it returns a string that looks like a success message, 
    # or at least DOES NOT return "Error: Owner is required"
    assert "Error: Owner is required" not in result
    assert "Latest stable release for hashicorp/nomad" in result

def test_get_latest_release_human_alias():
    """
    Test the tool wrapper handles human readable aliases (e.g. 'Nomad' -> 'hashicorp/nomad').
    """
    from server import get_latest_release
    
    # We call it with a capitalized Alias
    result = get_latest_release(repo="Nomad")
    
    assert "Error: Owner is required" not in result
    assert "Latest stable release for hashicorp/nomad" in result

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

