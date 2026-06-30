"""GitHub profile ingestor.

Fetches public GitHub profile data via the REST API and converts it
to a CandidateRecord.  Also supports reading cached JSON files for
offline / test usage.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import requests

from candidate_transformer.models import (
    CandidateRecord,
    Links,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"
_REQUEST_TIMEOUT_SECONDS = 15
_REPOS_PER_PAGE = 100
_GITHUB_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_-]+)/?$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_username(username_or_url: str) -> str | None:
    """Extract a GitHub username from a URL or plain username string.

    Args:
        username_or_url: Either a plain username like ``"johndoe"`` or a
            full URL like ``"https://github.com/johndoe"``.

    Returns:
        The extracted username, or ``None`` if extraction fails.
    """
    raw = username_or_url.strip().rstrip("/")
    if not raw:
        return None

    match = _GITHUB_URL_PATTERN.match(raw)
    if match:
        return match.group(1)

    # Also handle "github.com/user" without scheme
    if "/" in raw:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            return path_parts[0]

    # Assume plain username (no slashes, no spaces)
    if re.match(r"^[A-Za-z0-9_-]+$", raw):
        return raw

    logger.warning("Cannot extract GitHub username from: %r", username_or_url)
    return None


def _is_file_path(value: str) -> bool:
    """Determine whether a string looks like a local file path.

    Args:
        value: Input string to test.

    Returns:
        ``True`` if the input appears to be a file path.
    """
    # Explicit file extension check
    if value.strip().lower().endswith(".json"):
        return True
    # Absolute or relative path markers
    if os.path.sep in value or value.startswith("./") or value.startswith(".."):
        return True
    # Windows drive letter
    if len(value) > 2 and value[1] == ":":
        return True
    # Check if it actually exists on disk
    if os.path.isfile(value):
        return True
    return False


def _parse_location_string(raw: str) -> Location | None:
    """Parse a free-form location string into a Location object.

    Args:
        raw: Raw location string, e.g. ``"San Francisco, CA"``.

    Returns:
        Location object, or ``None`` if the string is empty.
    """
    if not raw or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    city = parts[0] if len(parts) >= 1 else ""
    region = parts[1] if len(parts) >= 2 else ""
    country = parts[2] if len(parts) >= 3 else ""
    return Location(city=city, region=region, country=country)


def _aggregate_languages(repos: list[dict[str, Any]]) -> list[str]:
    """Aggregate programming languages across repositories.

    Languages are sorted by the number of repos using them (descending)
    so the most-used language comes first.

    Args:
        repos: List of repository dicts (from the GitHub API).

    Returns:
        Sorted list of unique language strings.
    """
    lang_counts: dict[str, int] = {}
    for repo in repos:
        lang = repo.get("language")
        if lang and isinstance(lang, str):
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    # Sort descending by count, then alphabetically for determinism
    sorted_langs = sorted(
        lang_counts.keys(), key=lambda l: (-lang_counts[l], l)
    )
    return sorted_langs


def _extract_repo_names(repos: list[dict[str, Any]]) -> list[str]:
    """Extract repository names for skills context.

    Args:
        repos: List of repository dicts.

    Returns:
        List of repo name strings.
    """
    names: list[str] = []
    for repo in repos:
        name = repo.get("name")
        if name and isinstance(name, str):
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Live API fetching
# ---------------------------------------------------------------------------

def _fetch_user(username: str) -> dict[str, Any] | None:
    """Fetch a GitHub user profile via the REST API.

    Args:
        username: GitHub username.

    Returns:
        User data dict, or ``None`` on failure.
    """
    url = f"{_GITHUB_API_BASE}/users/{username}"
    logger.debug("Fetching GitHub user profile: %s", url)
    try:
        resp = requests.get(
            url,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("HTTP request failed for GitHub user %s: %s", username, exc)
        return None

    if resp.status_code == 404:
        logger.warning("GitHub user not found: %s", username)
        return None
    if resp.status_code == 403:
        logger.warning(
            "GitHub API rate limit exceeded or forbidden for user %s. "
            "Headers: %s",
            username,
            dict(resp.headers),
        )
        return None
    if resp.status_code != 200:
        logger.warning(
            "GitHub API returned status %d for user %s",
            resp.status_code, username,
        )
        return None

    try:
        data: dict[str, Any] = resp.json()
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to decode GitHub API response for %s: %s", username, exc)
        return None


def _fetch_repos(username: str) -> list[dict[str, Any]]:
    """Fetch public repositories for a GitHub user.

    Args:
        username: GitHub username.

    Returns:
        List of repository dicts. Empty list on failure.
    """
    url = (
        f"{_GITHUB_API_BASE}/users/{username}/repos"
        f"?per_page={_REPOS_PER_PAGE}&sort=updated"
    )
    logger.debug("Fetching GitHub repos: %s", url)
    try:
        resp = requests.get(
            url,
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.error("HTTP request failed for GitHub repos of %s: %s", username, exc)
        return []

    if resp.status_code != 200:
        logger.warning(
            "GitHub API returned status %d for repos of %s",
            resp.status_code, username,
        )
        return []

    try:
        data = resp.json()
        if isinstance(data, list):
            return data  # type: ignore[return-value]
        logger.warning("Unexpected repos response type for %s: %s", username, type(data).__name__)
        return []
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to decode repos response for %s: %s", username, exc)
        return []


# ---------------------------------------------------------------------------
# Offline / cached JSON ingestion
# ---------------------------------------------------------------------------

def _ingest_from_file(file_path: str) -> list[CandidateRecord]:
    """Ingest GitHub profile data from a cached JSON file.

    The JSON file is expected to have the same structure as the GitHub
    API response, optionally with a top-level ``"repos"`` key containing
    the repos array.

    Args:
        file_path: Path to the JSON file.

    Returns:
        List containing a single ``CandidateRecord``, or empty list.
    """
    logger.info("Reading cached GitHub profile from file: %s", file_path)

    if not os.path.isfile(file_path):
        logger.warning("GitHub cache file not found: %s", file_path)
        raise FileNotFoundError(f"GitHub cache file not found: {file_path}")

    raw_content: str = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(file_path, "r", encoding=encoding) as fh:
                raw_content = fh.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error("OS error reading GitHub cache file %s: %s", file_path, exc)
            return []

    if not raw_content.strip():
        logger.warning("GitHub cache file is empty: %s", file_path)
        return []

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in GitHub cache file %s: %s", file_path, exc)
        return []

    if not isinstance(data, dict):
        logger.error(
            "Expected dict in GitHub cache file %s, got %s",
            file_path, type(data).__name__,
        )
        return []

    repos: list[dict[str, Any]] = data.get("repos", [])
    if not isinstance(repos, list):
        repos = []

    return [_build_record(
        user_data=data,
        repos=repos,
        source_file=os.path.abspath(file_path),
    )]


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(
    user_data: dict[str, Any],
    repos: list[dict[str, Any]],
    source_file: str = "",
) -> CandidateRecord:
    """Build a CandidateRecord from GitHub user and repos data.

    Args:
        user_data: User profile dict from the GitHub API.
        repos: List of repo dicts from the GitHub API.
        source_file: Path or URL used as the source identifier.

    Returns:
        A populated ``CandidateRecord``.
    """
    full_name = str(user_data.get("name") or "").strip()
    login = str(user_data.get("login") or "").strip()
    bio = str(user_data.get("bio") or "").strip()
    email_raw = user_data.get("email")
    location_raw = str(user_data.get("location") or "").strip()
    blog = str(user_data.get("blog") or "").strip()
    html_url = str(user_data.get("html_url") or "").strip()

    # Use login as fallback name
    if not full_name:
        full_name = login

    emails: list[str] = []
    if email_raw and isinstance(email_raw, str) and email_raw.strip():
        emails.append(email_raw.strip())

    # Aggregate languages from repos as skills
    languages = _aggregate_languages(repos)
    repo_names = _extract_repo_names(repos)

    # Build links
    github_url = html_url or (
        f"https://github.com/{login}" if login else ""
    )
    links = Links(
        github=github_url,
        portfolio=blog,
    )

    location = _parse_location_string(location_raw)

    # Combine raw data for debugging
    raw: dict[str, Any] = dict(user_data)
    if repos:
        raw["_repos_count"] = len(repos)
        raw["_repo_names"] = repo_names

    return CandidateRecord(
        source_type=SourceType.GITHUB,
        source_file=source_file,
        full_name=full_name,
        emails=emails,
        headline=bio,
        location=location,
        links=links,
        skills=languages,
        raw_data=raw,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_github(username_or_url: str) -> list[CandidateRecord]:
    """Ingest a GitHub profile and return a candidate record.

    If ``username_or_url`` looks like a file path (ends with ``.json``
    or is an existing file), it is read as a cached API response.
    Otherwise, the GitHub REST API is called.

    Args:
        username_or_url: A GitHub username, profile URL, or path to a
            cached JSON file.

    Returns:
        A list containing one ``CandidateRecord``, or an empty list
        on failure.
    """
    logger.info("Starting GitHub ingestion for: %s", username_or_url)

    if not username_or_url or not username_or_url.strip():
        logger.warning("Empty input provided to GitHub ingestor")
        return []

    cleaned = username_or_url.strip()

    # Check if this is a file path for offline testing
    if _is_file_path(cleaned):
        return _ingest_from_file(cleaned)

    # Extract username
    username = _extract_username(cleaned)
    if not username:
        logger.warning("Could not extract GitHub username from: %r", cleaned)
        return []

    # Fetch profile
    user_data = _fetch_user(username)
    if user_data is None:
        return []

    # Fetch repos
    repos = _fetch_repos(username)

    record = _build_record(
        user_data=user_data,
        repos=repos,
        source_file=f"https://github.com/{username}",
    )

    logger.info("GitHub ingestion complete for user: %s", username)
    return [record]
