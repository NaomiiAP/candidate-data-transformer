"""
Normalization utilities for candidate data fields.

Provides deterministic, idempotent normalization functions for all
field types in the candidate pipeline. Each normalizer accepts a raw
string and returns a cleaned, canonical representation. All functions
are pure — no side effects, no I/O.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

import phonenumbers
import pycountry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill alias mapping (lowercase key -> canonical name)
# ---------------------------------------------------------------------------
_SKILL_ALIASES: dict[str, str] = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "python3": "Python",
    "python": "Python",
    "golang": "Go",
    "go": "Go",
    "reactjs": "React",
    "react.js": "React",
    "react": "React",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node": "Node.js",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "aws": "Amazon Web Services",
    "amazon web services": "Amazon Web Services",
    "gcp": "Google Cloud Platform",
    "google cloud platform": "Google Cloud Platform",
    "c#": "C#",
    "csharp": "C#",
    "c++": "C++",
    "cpp": "C++",
    "html5": "HTML5",
    "css3": "CSS3",
    "pg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "tf": "TensorFlow",
    "tensorflow": "TensorFlow",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "angularjs": "Angular",
    "dotnet": ".NET",
    ".net": ".NET",
    "ruby on rails": "Ruby on Rails",
    "rails": "Ruby on Rails",
    "ror": "Ruby on Rails",
    "docker": "Docker",
    "sql": "SQL",
    "nosql": "NoSQL",
    "graphql": "GraphQL",
    "rest": "REST",
    "restful": "REST",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "devops": "DevOps",
}

# Common country name aliases -> ISO-3166 Alpha-2
_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "united states of america": "US",
    "united states": "US",
    "america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "uae": "AE",
    "united arab emirates": "AE",
}

# Month name -> number mapping
_MONTH_MAP: dict[str, str] = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}

# Known uppercase acronyms that should NOT be title-cased
_SKILL_ACRONYMS: set[str] = {
    "JavaScript", "TypeScript", "Python", "Go", "React", "Node.js",
    "Kubernetes", "Machine Learning", "Artificial Intelligence",
    "Amazon Web Services", "Google Cloud Platform", "C#", "C++",
    "HTML5", "CSS3", "PostgreSQL", "MongoDB", "TensorFlow", "Vue.js",
    "Angular", ".NET", "Ruby on Rails", "Docker", "SQL", "NoSQL",
    "GraphQL", "REST", "CI/CD", "DevOps",
}

# Email validation regex (RFC 5322 simplified)
_EMAIL_REGEX: re.Pattern[str] = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def normalize_phone(raw: str, default_region: str = "US") -> str:
    """Normalize a phone number to E.164 format.

    Handles international formats, parentheses, dashes, dots, and spaces.
    Falls back to default_region country code when no country code is provided.

    Args:
        raw: Raw phone number string.
        default_region: Default region code (e.g. 'US', 'GB') to assume.

    Returns:
        E.164 formatted phone string, or empty string on failure.

    Examples:
        >>> normalize_phone("(555) 123-4567")
        '+15551234567'
        >>> normalize_phone("+44 20 7946 0958")
        '+442079460958'
        >>> normalize_phone("garbage")
        ''
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip()
    if not cleaned:
        return ""

    try:
        # If it starts with + or looks international, try parsing with no default region first
        if cleaned.startswith("+"):
            parsed = phonenumbers.parse(cleaned, None)
        else:
            parsed = phonenumbers.parse(cleaned, default_region)
    except phonenumbers.NumberParseException:
        try:
            parsed = phonenumbers.parse(cleaned, default_region)
        except phonenumbers.NumberParseException:
            logger.debug("Failed to parse phone number: %s", raw)
            return ""

    if not (phonenumbers.is_valid_number(parsed) or phonenumbers.is_possible_number(parsed)):
        logger.debug("Invalid phone number: %s", raw)
        return ""

    formatted: str = phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.E164
    )
    return formatted


def normalize_email(raw: str) -> str:
    """Normalize an email address.

    Lowercases, strips whitespace, and performs basic format validation.

    Args:
        raw: Raw email string.

    Returns:
        Normalized email string, or empty string if invalid.

    Examples:
        >>> normalize_email("  John.Doe@Gmail.COM  ")
        'john.doe@gmail.com'
        >>> normalize_email("not-an-email")
        ''
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip().lower()
    if not cleaned:
        return ""

    if not _EMAIL_REGEX.match(cleaned):
        logger.debug("Invalid email format: %s", raw)
        return ""

    return cleaned


def normalize_country(raw: str) -> str:
    """Convert a country name or code to ISO-3166 Alpha-2.

    Handles full names (e.g., 'United States'), common abbreviations
    (e.g., 'USA'), and existing Alpha-2 / Alpha-3 codes.

    Args:
        raw: Raw country string.

    Returns:
        ISO-3166 Alpha-2 code (uppercase), or empty string on failure.

    Examples:
        >>> normalize_country("United States")
        'US'
        >>> normalize_country("india")
        'IN'
        >>> normalize_country("GBR")
        'GB'
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip()
    if not cleaned:
        return ""

    lookup_key = cleaned.lower()

    # Check our custom alias map first
    if lookup_key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[lookup_key]

    # Try exact Alpha-2 match (e.g., "US", "IN")
    if len(cleaned) == 2:
        try:
            country = pycountry.countries.get(alpha_2=cleaned.upper())
            if country:
                return country.alpha_2
        except (KeyError, AttributeError):
            pass

    # Try Alpha-3 match (e.g., "USA", "IND")
    if len(cleaned) == 3:
        try:
            country = pycountry.countries.get(alpha_3=cleaned.upper())
            if country:
                return country.alpha_2
        except (KeyError, AttributeError):
            pass

    # Try full name lookup via pycountry
    try:
        country = pycountry.countries.get(name=cleaned)
        if country:
            return country.alpha_2
    except (KeyError, AttributeError):
        pass

    # Try official_name lookup
    try:
        country = pycountry.countries.get(official_name=cleaned)
        if country:
            return country.alpha_2
    except (KeyError, AttributeError):
        pass

    # Try fuzzy search as last resort
    try:
        results = pycountry.countries.search_fuzzy(cleaned)
        if results:
            return results[0].alpha_2
    except LookupError:
        pass

    logger.debug("Could not normalize country: %s", raw)
    return ""


def normalize_date(raw: str) -> str:
    """Convert various date formats to YYYY-MM.

    Handles: 'Jan 2020', '2020-01', '01/2020', 'January 2020',
    '2020', 'present', 'current'.

    Args:
        raw: Raw date string.

    Returns:
        YYYY-MM formatted string, 'present' for current dates,
        or empty string on failure.

    Examples:
        >>> normalize_date("Jan 2020")
        '2020-01'
        >>> normalize_date("present")
        'present'
        >>> normalize_date("2020")
        '2020-01'
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip().lower()
    if not cleaned:
        return ""

    # Handle 'present' / 'current' / 'now' / 'ongoing'
    if cleaned in {"present", "current", "now", "ongoing", "today"}:
        return "present"

    # Try YYYY-MM-DD format (e.g., "2021-03-15" or "2021/03/15", with optional time)
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ t]|$)", cleaned)
    if match:
        year, month = match.group(1), match.group(2).zfill(2)
        if _is_valid_year_month(year, month):
            return f"{year}-{month}"

    # Try YYYY-MM format (e.g., "2020-01")
    match = re.match(r"^(\d{4})-(\d{1,2})$", cleaned)
    if match:
        year, month = match.group(1), match.group(2).zfill(2)
        if _is_valid_year_month(year, month):
            return f"{year}-{month}"

    # Try MM/YYYY format (e.g., "01/2020")
    match = re.match(r"^(\d{1,2})/(\d{4})$", cleaned)
    if match:
        month, year = match.group(1).zfill(2), match.group(2)
        if _is_valid_year_month(year, month):
            return f"{year}-{month}"

    # Try MM-YYYY format (e.g., "01-2020")
    match = re.match(r"^(\d{1,2})-(\d{4})$", cleaned)
    if match:
        month, year = match.group(1).zfill(2), match.group(2)
        if _is_valid_year_month(year, month):
            return f"{year}-{month}"

    # Try "Month YYYY" format (e.g., "January 2020", "Jan 2020")
    match = re.match(r"^([a-z]+)\s+(\d{4})$", cleaned)
    if match:
        month_name, year = match.group(1), match.group(2)
        month_num = _MONTH_MAP.get(month_name, "")
        if month_num and _is_valid_year_month(year, month_num):
            return f"{year}-{month_num}"

    # Try "YYYY Month" format (e.g., "2020 January")
    match = re.match(r"^(\d{4})\s+([a-z]+)$", cleaned)
    if match:
        year, month_name = match.group(1), match.group(2)
        month_num = _MONTH_MAP.get(month_name, "")
        if month_num and _is_valid_year_month(year, month_num):
            return f"{year}-{month_num}"

    # Try standalone YYYY (e.g., "2020")
    match = re.match(r"^(\d{4})$", cleaned)
    if match:
        year = match.group(1)
        if 1900 <= int(year) <= 2100:
            return f"{year}-01"

    logger.debug("Could not normalize date: %s", raw)
    return ""


def normalize_skill(raw: str) -> str:
    """Canonicalize a skill name.

    Maps known aliases to canonical names. For unknown skills, applies
    title-casing while preserving known acronyms.

    Args:
        raw: Raw skill string.

    Returns:
        Canonical skill name, or empty string if input is empty.

    Examples:
        >>> normalize_skill("JS")
        'JavaScript'
        >>> normalize_skill("k8s")
        'Kubernetes'
        >>> normalize_skill("  machine learning  ")
        'Machine Learning'
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip()
    if not cleaned:
        return ""

    lookup_key = cleaned.lower()

    # Check the alias map
    if lookup_key in _SKILL_ALIASES:
        return _SKILL_ALIASES[lookup_key]

    # For unrecognized skills, apply intelligent casing
    return _smart_title_case(cleaned)


def normalize_name(raw: str) -> str:
    """Normalize a person's name to title case.

    Strips extra whitespace, handles all-caps input, and applies
    proper title casing.

    Args:
        raw: Raw name string.

    Returns:
        Normalized name string, or empty string if input is empty.

    Examples:
        >>> normalize_name("JOHN DOE")
        'John Doe'
        >>> normalize_name("  jane   smith  ")
        'Jane Smith'
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip()
    if not cleaned:
        return ""

    # Collapse multiple whitespace into single spaces
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Split and title-case each part, handling special prefixes
    parts: list[str] = []
    for part in cleaned.split(" "):
        parts.append(_title_case_name_part(part))

    return " ".join(parts)


def normalize_url(raw: str) -> str:
    """Normalize a URL.

    Ensures the URL has a scheme (defaults to https), lowercases the
    domain, and strips trailing slashes from the path.

    Args:
        raw: Raw URL string.

    Returns:
        Normalized URL string, or empty string if invalid.

    Examples:
        >>> normalize_url("linkedin.com/in/johndoe/")
        'https://linkedin.com/in/johndoe'
        >>> normalize_url("HTTP://GITHUB.COM/user")
        'http://github.com/user'
    """
    if not raw or not isinstance(raw, str):
        return ""

    cleaned = raw.strip()
    if not cleaned:
        return ""

    # Add scheme if missing
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
        cleaned = f"https://{cleaned}"

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        logger.debug("Could not parse URL: %s", raw)
        return ""

    if not parsed.netloc:
        logger.debug("URL has no network location: %s", raw)
        return ""

    # Lowercase the domain, strip trailing slashes from path
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    normalized = urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        parsed.query,
        "",  # Drop fragment
    ))

    return normalized


# ---------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------

def _is_valid_year_month(year: str, month: str) -> bool:
    """Validate that year and month are in reasonable ranges."""
    try:
        y = int(year)
        m = int(month)
        return 1900 <= y <= 2100 and 1 <= m <= 12
    except ValueError:
        return False


def _smart_title_case(text: str) -> str:
    """Apply title case while preserving common acronyms.

    Words that are all uppercase and 2-4 chars are kept uppercase
    (likely acronyms). Everything else is title-cased.
    """
    words: list[str] = text.split()
    result: list[str] = []

    for word in words:
        if word.isupper() and 2 <= len(word) <= 4:
            result.append(word)
        else:
            result.append(word.capitalize())

    return " ".join(result)


_NAME_PREFIXES: set[str] = {
    "mc", "mac", "de", "di", "da", "del", "van", "von",
    "le", "la", "el", "al", "bin", "ibn",
}


def _title_case_name_part(part: str) -> str:
    """Title-case a single name part, handling prefixes like Mc, Mac, O'."""
    if not part:
        return part

    lower = part.lower()

    # Handle O'Connor style
    if "'" in lower and len(lower) > 2:
        segments = lower.split("'", 1)
        return f"{segments[0].capitalize()}'{segments[1].capitalize()}"

    # Handle McSomething / MacDonald
    if lower.startswith("mc") and len(lower) > 2:
        return f"Mc{lower[2:].capitalize()}"
    if lower.startswith("mac") and len(lower) > 3:
        return f"Mac{lower[3:].capitalize()}"

    # Handle lowercase particles (keep lowercase if not first word)
    if lower in {"de", "di", "da", "del", "van", "von", "le", "la", "el", "al"}:
        return lower

    return lower.capitalize()
