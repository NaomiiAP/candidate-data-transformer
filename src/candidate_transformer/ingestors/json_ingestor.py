"""ATS JSON ingestor.

Reads ATS-exported JSON files and maps them to CandidateRecord objects.
Handles single object or array inputs, flexible field names,
nested structures, and invalid JSON gracefully.
"""

from __future__ import annotations

import json
import logging
import os
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


# ---------------------------------------------------------------------------
# Field-name resolution helpers
# ---------------------------------------------------------------------------

def _first_match(data: dict[str, Any], keys: list[str]) -> Any:
    """Return the value of the first matching key found in a dictionary.

    Args:
        data: The dictionary to search.
        keys: Ordered list of candidate key names (case-insensitive).

    Returns:
        The value for the first key that matches, or ``None``.
    """
    lower_map: dict[str, str] = {k.lower(): k for k in data}
    for candidate_key in keys:
        original_key = lower_map.get(candidate_key.lower())
        if original_key is not None:
            return data[original_key]
    return None


def _str(value: Any) -> str:
    """Coerce a value to a stripped string, handling None.

    Args:
        value: Any value.

    Returns:
        Stripped string representation, or empty string for ``None``.
    """
    if value is None:
        return ""
    return str(value).strip()


def _str_list(value: Any) -> list[str]:
    """Coerce a value to a list of strings.

    Handles strings (comma-separated), lists, and ``None``.

    Args:
        value: A string, list, or ``None``.

    Returns:
        List of non-empty stripped strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        # Try comma, semicolon, pipe splitting
        for sep in [",", ";", "|"]:
            if sep in value:
                return [s.strip() for s in value.split(sep) if s.strip()]
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            s = _str(item)
            if s:
                result.append(s)
        return result
    return [str(value).strip()] if str(value).strip() else []


def _email_list(value: Any) -> list[str]:
    """Normalise an email field to a list of email strings.

    Accepts a single string, a list of strings, or a list of dicts
    with an ``"email"`` or ``"address"`` key.

    Args:
        value: Raw email value from JSON.

    Returns:
        List of email strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    result.append(cleaned)
            elif isinstance(item, dict):
                email = item.get("email") or item.get("address") or item.get("value", "")
                cleaned = str(email).strip()
                if cleaned:
                    result.append(cleaned)
        return result
    return []


def _phone_list(value: Any) -> list[str]:
    """Normalise a phone field to a list of phone strings.

    Accepts a single string, a list of strings, or a list of dicts.

    Args:
        value: Raw phone value from JSON.

    Returns:
        List of phone strings.
    """
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    result.append(cleaned)
            elif isinstance(item, dict):
                phone = (
                    item.get("phone")
                    or item.get("number")
                    or item.get("value", "")
                )
                cleaned = str(phone).strip()
                if cleaned:
                    result.append(cleaned)
        return result
    return []


def _safe_float(value: Any) -> float | None:
    """Safely parse a value to float.

    Args:
        value: Numeric or string value.

    Returns:
        Float value, or ``None`` on failure.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Experience and education parsing
# ---------------------------------------------------------------------------

def _parse_experience(data: dict[str, Any]) -> Experience:
    """Parse a single experience/work-history entry.

    Args:
        data: Dictionary representing one experience entry.

    Returns:
        An ``Experience`` object.
    """
    company = _str(
        _first_match(data, ["company", "company_name", "employer", "organization"])
    )
    title = _str(
        _first_match(data, ["title", "job_title", "position", "role"])
    )
    start = _str(
        _first_match(data, ["start_date", "start", "from", "from_date"])
    )
    end = _str(
        _first_match(data, ["end_date", "end", "to", "to_date"])
    )
    summary = _str(
        _first_match(data, [
            "description", "summary", "responsibilities", "details",
        ])
    )
    return Experience(
        company=company,
        title=title,
        start=start,
        end=end,
        summary=summary,
    )


def _parse_experience_list(value: Any) -> list[Experience]:
    """Parse experience data which may be a list of dicts or a single dict.

    Args:
        value: Raw experience value from JSON.

    Returns:
        List of ``Experience`` objects.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        return [_parse_experience(value)]
    if isinstance(value, list):
        result: list[Experience] = []
        for item in value:
            if isinstance(item, dict):
                result.append(_parse_experience(item))
            else:
                logger.debug("Skipping non-dict experience entry: %r", item)
        return result
    return []


def _parse_education(data: dict[str, Any]) -> Education:
    """Parse a single education entry.

    Args:
        data: Dictionary representing one education entry.

    Returns:
        An ``Education`` object.
    """
    institution = _str(
        _first_match(data, [
            "school", "institution", "university", "college",
            "school_name", "institution_name",
        ])
    )
    degree = _str(
        _first_match(data, ["degree", "degree_name", "qualification", "level"])
    )
    field_of_study = _str(
        _first_match(data, [
            "field_of_study", "field", "major", "specialization",
            "concentration", "subject",
        ])
    )
    end_year = _str(
        _first_match(data, [
            "graduation_year", "end_year", "year", "grad_year",
            "completion_year",
        ])
    )
    return Education(
        institution=institution,
        degree=degree,
        field=field_of_study,
        end_year=end_year,
    )


def _parse_education_list(value: Any) -> list[Education]:
    """Parse education data which may be a list of dicts or a single dict.

    Args:
        value: Raw education value from JSON.

    Returns:
        List of ``Education`` objects.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        return [_parse_education(value)]
    if isinstance(value, list):
        result: list[Education] = []
        for item in value:
            if isinstance(item, dict):
                result.append(_parse_education(item))
            else:
                logger.debug("Skipping non-dict education entry: %r", item)
        return result
    return []


def _parse_location(value: Any) -> Location | None:
    """Parse a location value which may be a string or nested dict.

    Args:
        value: Raw location value — a string like ``"San Francisco, CA, US"``
            or a dict with ``city`` / ``state`` / ``country`` keys.

    Returns:
        A ``Location`` object, or ``None`` if empty.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        city = _str(
            _first_match(value, ["city", "town", "municipality"])
        )
        region = _str(
            _first_match(value, [
                "state", "region", "province", "county",
            ])
        )
        country = _str(
            _first_match(value, ["country", "country_code", "nation"])
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


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest_json(file_path: str) -> list[CandidateRecord]:
    """Ingest an ATS JSON file and return candidate records.

    The JSON can be a single object (one candidate) or an array of objects.
    Field names are matched flexibly to support different ATS systems.

    Args:
        file_path: Absolute or relative path to the JSON file.

    Returns:
        List of ``CandidateRecord`` objects. Returns an empty list if
        the file is missing, empty, or contains invalid JSON.
    """
    logger.info("Starting JSON ingestion from: %s", file_path)

    if not file_path or not file_path.strip():
        logger.warning("Empty file path provided to JSON ingestor")
        return []

    if not os.path.isfile(file_path):
        logger.warning("JSON file not found: %s", file_path)
        raise FileNotFoundError(f"JSON file not found: {file_path}")

    # Read file content with encoding fallback
    raw_content: str = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=encoding) as fh:
                raw_content = fh.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error("OS error reading JSON file %s: %s", file_path, exc)
            return []

    if not raw_content.strip():
        logger.warning("JSON file is empty: %s", file_path)
        return []

    # Parse JSON
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in %s: %s", file_path, exc)
        raise ValueError(f"Invalid JSON in {file_path}") from exc

    # Normalize to a list of dicts
    entries: list[dict[str, Any]]
    if isinstance(parsed, dict):
        entries = [parsed]
        logger.debug("JSON contains a single object")
    elif isinstance(parsed, list):
        entries = [e for e in parsed if isinstance(e, dict)]
        if len(entries) != len(parsed):
            skipped = len(parsed) - len(entries)
            logger.warning(
                "Skipped %d non-dict entries in JSON array from %s",
                skipped, file_path,
            )
        logger.debug("JSON contains an array with %d entries", len(entries))
    else:
        logger.error(
            "Unexpected JSON root type %s in %s", type(parsed).__name__, file_path
        )
        return []

    records: list[CandidateRecord] = []
    abs_path = os.path.abspath(file_path)

    for idx, entry in enumerate(entries):
        try:
            # --- Identity ---
            full_name = _str(_first_match(entry, [
                "candidate_name", "name", "full_name", "fullname",
                "applicant_name",
            ]))

            # Handle first_name / last_name as fallback
            if not full_name:
                first = _str(_first_match(entry, [
                    "first_name", "firstname", "given_name",
                ]))
                last = _str(_first_match(entry, [
                    "last_name", "lastname", "family_name", "surname",
                ]))
                if first or last:
                    full_name = f"{first} {last}".strip()

            emails = _email_list(_first_match(entry, [
                "email_address", "email", "emails", "primary_email",
                "candidate_email", "email_addresses",
            ]))
            phones = _phone_list(_first_match(entry, [
                "phone_number", "phone", "phones", "primary_phone",
                "mobile", "telephone", "phone_numbers",
            ]))

            # --- Profile ---
            headline = _str(_first_match(entry, [
                "headline", "title", "current_title", "job_title",
                "position",
            ]))
            current_company = _str(_first_match(entry, [
                "current_company", "company", "employer",
            ]))
            yoe = _safe_float(_first_match(entry, [
                "years_of_experience", "yoe", "years_experience",
                "experience_years",
            ]))

            # --- Skills ---
            skills = _str_list(_first_match(entry, [
                "skills", "skill_list", "technologies", "tech_stack",
                "competencies",
            ]))

            # --- Experience ---
            experience = _parse_experience_list(_first_match(entry, [
                "work_history", "experience", "work_experience",
                "positions", "employment_history", "jobs",
            ]))

            # --- Education ---
            education = _parse_education_list(_first_match(entry, [
                "education_history", "education", "academic_history",
                "degrees", "schools",
            ]))

            # --- Location ---
            location = _parse_location(_first_match(entry, [
                "location", "address", "city", "region",
            ]))

            # --- Links ---
            linkedin = _str(_first_match(entry, [
                "linkedin_url", "linkedin", "linkedin_profile",
            ]))
            github = _str(_first_match(entry, [
                "github_url", "github", "github_profile",
            ]))
            portfolio = _str(_first_match(entry, [
                "portfolio_url", "portfolio", "website", "blog",
                "personal_website",
            ]))

            links: Links | None = None
            if linkedin or github or portfolio:
                links = Links(
                    linkedin=linkedin,
                    github=github,
                    portfolio=portfolio,
                )

            # Skip entries with no identifying info at all
            if not full_name and not emails and not phones:
                logger.debug(
                    "Skipping JSON entry %d with no identity info in %s",
                    idx, file_path,
                )
                continue

            record = CandidateRecord(
                source_type=SourceType.ATS_JSON,
                source_file=abs_path,
                full_name=full_name,
                emails=emails,
                phones=phones,
                headline=headline,
                current_company=current_company,
                years_experience=yoe,
                skills=skills,
                experience=experience,
                education=education,
                location=location,
                links=links,
                raw_data=entry,
            )
            records.append(record)
            logger.debug(
                "Parsed JSON entry %d: name=%r, emails=%r",
                idx, full_name, emails,
            )

        except Exception as exc:
            logger.warning(
                "Failed to parse JSON entry %d in %s: %s", idx, file_path, exc
            )
            continue

    logger.info(
        "JSON ingestion complete: %d records from %s", len(records), file_path
    )
    return records
