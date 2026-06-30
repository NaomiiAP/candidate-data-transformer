"""LinkedIn profile ingestor.

Reads exported or cached LinkedIn profile JSON data and converts it to
a CandidateRecord.  LinkedIn profiles cannot be scraped via API without
OAuth, so this ingestor works with JSON files containing profile data.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from candidate_transformer.models import (
    CandidateRecord,
    Education,
    Experience,
    Links,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

# Month name → number mapping for date parsing
_MONTH_MAP: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _str(value: Any) -> str:
    """Coerce a value to a stripped string.

    Args:
        value: Any value.

    Returns:
        Stripped string, or empty string for ``None``.
    """
    if value is None:
        return ""
    return str(value).strip()


def _str_list(value: Any) -> list[str]:
    """Coerce a value to a list of non-empty strings.

    Args:
        value: A string, list, or ``None``.

    Returns:
        List of stripped strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        for sep in [",", ";", "|"]:
            if sep in value:
                return [s.strip() for s in value.split(sep) if s.strip()]
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _parse_date(raw: str) -> str:
    """Parse a LinkedIn date string to YYYY-MM format.

    Handles formats like ``"January 2021"``, ``"Jan 2021"``, ``"2021-01"``,
    ``"2021"``, ``"Present"``.

    Args:
        raw: Raw date string.

    Returns:
        Normalised date string in YYYY-MM format, ``"present"``, or the
        original string if parsing fails.
    """
    if not raw or not raw.strip():
        return ""

    cleaned = raw.strip()

    # "Present" / "current"
    if cleaned.lower() in ("present", "current", "now"):
        return "present"

    # Already YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", cleaned):
        return cleaned

    # "YYYY" alone
    if re.match(r"^\d{4}$", cleaned):
        return cleaned

    # "Month YYYY" or "Mon YYYY"
    match = re.match(r"^([A-Za-z]+)\s+(\d{4})$", cleaned)
    if match:
        month_str = match.group(1).lower()
        year = match.group(2)
        month_num = _MONTH_MAP.get(month_str)
        if month_num:
            return f"{year}-{month_num}"
        return f"{year}"

    # "YYYY-MM-DD" → trim to YYYY-MM
    match = re.match(r"^(\d{4}-\d{2})", cleaned)
    if match:
        return match.group(1)

    logger.debug("Could not parse date: %r, using raw value", raw)
    return cleaned


def _parse_location(value: Any) -> Location | None:
    """Parse a location value (string or dict) into a Location object.

    Args:
        value: Raw location value from the LinkedIn JSON.

    Returns:
        Location object, or ``None`` if empty.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        city = _str(value.get("city"))
        region = _str(
            value.get("state") or value.get("region") or value.get("province")
        )
        country = _str(
            value.get("country") or value.get("country_code")
        )
        if city or region or country:
            return Location(city=city, region=region, country=country)
        return None

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        city = parts[0] if len(parts) >= 1 else ""
        region = parts[1] if len(parts) >= 2 else ""
        country = parts[2] if len(parts) >= 3 else ""
        return Location(city=city, region=region, country=country)

    return None


def _parse_position(data: dict[str, Any]) -> Experience:
    """Parse a single LinkedIn position entry to an Experience.

    Args:
        data: Dictionary representing one position.

    Returns:
        An ``Experience`` object.
    """
    company = _str(
        data.get("company") or data.get("company_name") or data.get("companyName")
    )
    title = _str(
        data.get("title") or data.get("position") or data.get("role")
    )
    start_raw = _str(
        data.get("start_date") or data.get("startDate") or data.get("start")
    )
    end_raw = _str(
        data.get("end_date") or data.get("endDate") or data.get("end")
    )
    summary = _str(
        data.get("description") or data.get("summary") or data.get("responsibilities")
    )

    return Experience(
        company=company,
        title=title,
        start=_parse_date(start_raw),
        end=_parse_date(end_raw),
        summary=summary,
    )


def _parse_education_entry(data: dict[str, Any]) -> Education:
    """Parse a single LinkedIn education entry.

    Args:
        data: Dictionary representing one education entry.

    Returns:
        An ``Education`` object.
    """
    institution = _str(
        data.get("school")
        or data.get("institution")
        or data.get("schoolName")
        or data.get("university")
    )
    degree = _str(
        data.get("degree")
        or data.get("degree_name")
        or data.get("degreeName")
    )
    field_of_study = _str(
        data.get("field_of_study")
        or data.get("fieldOfStudy")
        or data.get("major")
        or data.get("field")
    )
    end_year = _str(
        data.get("end_year")
        or data.get("graduation_year")
        or data.get("endYear")
        or data.get("year")
    )

    return Education(
        institution=institution,
        degree=degree,
        field=field_of_study,
        end_year=end_year,
    )


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest_linkedin(file_path_or_url: str) -> list[CandidateRecord]:
    """Ingest a LinkedIn profile from a JSON file.

    LinkedIn profiles cannot be accessed via public API without OAuth.
    This ingestor accepts a path to a JSON file containing exported or
    cached LinkedIn profile data.

    If a LinkedIn URL is provided instead of a file path, a warning is
    logged and an empty list is returned (scraping is not supported).

    Args:
        file_path_or_url: Path to a LinkedIn profile JSON file, or a
            LinkedIn URL (which will be rejected with a warning).

    Returns:
        List containing one ``CandidateRecord``, or an empty list on
        failure.
    """
    logger.info("Starting LinkedIn ingestion from: %s", file_path_or_url)

    if not file_path_or_url or not file_path_or_url.strip():
        logger.warning("Empty input provided to LinkedIn ingestor")
        return []

    cleaned = file_path_or_url.strip()

    # Detect if a URL was passed instead of a file
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        if "linkedin.com" in cleaned.lower():
            logger.warning(
                "LinkedIn URL provided but scraping is not supported. "
                "Please provide a JSON file with exported profile data. "
                "URL: %s",
                cleaned,
            )
            return []
        # Might be a URL to a JSON file — but we don't download URLs
        logger.warning(
            "URL provided to LinkedIn ingestor but only local files are "
            "supported: %s",
            cleaned,
        )
        return []

    file_path = cleaned

    if not os.path.isfile(file_path):
        logger.warning("LinkedIn profile file not found: %s", file_path)
        raise FileNotFoundError(f"LinkedIn profile file not found: {file_path}")

    # Read file
    raw_content: str = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=encoding) as fh:
                raw_content = fh.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error(
                "OS error reading LinkedIn profile file %s: %s", file_path, exc
            )
            return []

    if not raw_content.strip():
        logger.warning("LinkedIn profile file is empty: %s", file_path)
        return []

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in LinkedIn file %s: %s", file_path, exc)
        return []

    if not isinstance(data, dict):
        logger.error(
            "Expected dict in LinkedIn file %s, got %s",
            file_path, type(data).__name__,
        )
        return []

    abs_path = os.path.abspath(file_path)

    try:
        # --- Name ---
        first = _str(data.get("first_name") or data.get("firstName"))
        last = _str(data.get("last_name") or data.get("lastName"))
        full_name = _str(data.get("full_name") or data.get("name"))
        if not full_name:
            full_name = f"{first} {last}".strip()

        # --- Headline / Summary ---
        headline = _str(data.get("headline"))
        summary = _str(data.get("summary") or data.get("about"))

        # Use summary as headline fallback
        if not headline and summary:
            # Truncate long summaries for headline use
            headline = summary[:200].rstrip()
            if len(summary) > 200:
                headline += "..."

        # --- Contact ---
        email_raw = data.get("email") or data.get("email_address")
        emails: list[str] = []
        if email_raw:
            if isinstance(email_raw, str) and email_raw.strip():
                emails.append(email_raw.strip())
            elif isinstance(email_raw, list):
                for e in email_raw:
                    s = _str(e)
                    if s:
                        emails.append(s)

        phone_raw = data.get("phone") or data.get("phone_number")
        phones: list[str] = []
        if phone_raw:
            if isinstance(phone_raw, str) and phone_raw.strip():
                phones.append(phone_raw.strip())
            elif isinstance(phone_raw, list):
                for p in phone_raw:
                    s = _str(p)
                    if s:
                        phones.append(s)

        # --- Location ---
        location = _parse_location(data.get("location"))

        # --- Links ---
        profile_url = _str(
            data.get("profile_url")
            or data.get("profileUrl")
            or data.get("linkedin_url")
        )
        github_url = _str(data.get("github_url") or data.get("github"))
        portfolio = _str(
            data.get("portfolio") or data.get("website") or data.get("blog")
        )
        links = Links(
            linkedin=profile_url,
            github=github_url,
            portfolio=portfolio,
        )

        # --- Skills ---
        skills = _str_list(data.get("skills"))

        # --- Experience ---
        positions_raw = data.get("positions") or data.get("experience") or []
        experience: list[Experience] = []
        if isinstance(positions_raw, list):
            for pos in positions_raw:
                if isinstance(pos, dict):
                    experience.append(_parse_position(pos))
                else:
                    logger.debug("Skipping non-dict position entry: %r", pos)

        # --- Education ---
        education_raw = data.get("education") or data.get("educations") or []
        education: list[Education] = []
        if isinstance(education_raw, list):
            for edu in education_raw:
                if isinstance(edu, dict):
                    education.append(_parse_education_entry(edu))
                else:
                    logger.debug("Skipping non-dict education entry: %r", edu)

        # --- Years of experience ---
        yoe = data.get("years_of_experience") or data.get("years_experience")
        years_experience: float | None = None
        if yoe is not None:
            try:
                years_experience = float(yoe)
            except (ValueError, TypeError):
                years_experience = None

        # --- Current company ---
        current_company = _str(
            data.get("current_company") or data.get("company")
        )
        # Infer from most recent position if not explicit
        if not current_company and experience:
            latest = experience[0]
            if latest.end.lower() in ("present", "current", "now", ""):
                current_company = latest.company

        # Skip if no identifying info at all
        if not full_name and not emails:
            logger.warning(
                "LinkedIn profile has no name or email in %s", file_path
            )
            return []

        record = CandidateRecord(
            source_type=SourceType.LINKEDIN,
            source_file=abs_path,
            full_name=full_name,
            emails=emails,
            phones=phones,
            headline=headline,
            current_company=current_company,
            years_experience=years_experience,
            skills=skills,
            experience=experience,
            education=education,
            location=location,
            links=links,
            raw_data=data,
        )

        logger.info(
            "LinkedIn ingestion complete: name=%r from %s",
            full_name, file_path,
        )
        return [record]

    except Exception as exc:
        logger.error(
            "Unexpected error processing LinkedIn file %s: %s", file_path, exc
        )
        return []
