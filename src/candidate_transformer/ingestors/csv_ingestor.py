"""Recruiter CSV ingestor.

Reads recruiter-exported CSV files and maps rows to CandidateRecord objects.
Handles BOM markers, different delimiters (comma, semicolon, tab, pipe),
flexible column names, empty rows, and encoding issues.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

from candidate_transformer.models import (
    CandidateRecord,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

# Mapping of canonical field names to possible CSV column header variants.
# Each key is the canonical name; the value list contains lowercase variations
# that we accept in the CSV header.
_COLUMN_ALIASES: dict[str, list[str]] = {
    "full_name": [
        "full_name", "fullname", "name", "candidate_name", "candidate",
        "applicant_name", "applicant", "person_name", "person",
    ],
    "email": [
        "email", "email_address", "e-mail", "e_mail", "candidate_email",
        "primary_email", "contact_email",
    ],
    "phone": [
        "phone", "phone_number", "telephone", "mobile", "cell",
        "contact_phone", "primary_phone", "tel",
    ],
    "current_company": [
        "current_company", "company", "employer", "organization",
        "organisation", "current_employer", "firm",
    ],
    "title": [
        "title", "job_title", "position", "role", "current_title",
        "designation", "current_role",
    ],
    "location": [
        "location", "city", "address", "region", "area",
    ],
    "linkedin": [
        "linkedin", "linkedin_url", "linkedin_profile",
    ],
    "github": [
        "github", "github_url", "github_profile",
    ],
    "skills": [
        "skills", "skill_list", "technologies", "tech_stack",
    ],
    "years_experience": [
        "years_experience", "years_of_experience", "yoe", "experience_years",
    ],
}


def _detect_delimiter(sample: str) -> str:
    """Detect the most likely CSV delimiter from a sample of text.

    Args:
        sample: A sample of the CSV file content (first few KB).

    Returns:
        The detected delimiter character. Defaults to comma.
    """
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        detected: str = dialect.delimiter
        logger.debug("Detected CSV delimiter: %r", detected)
        return detected
    except csv.Error:
        logger.debug("Delimiter detection failed, defaulting to comma")
        return ","


def _strip_bom(text: str) -> str:
    """Remove UTF-8 BOM if present at the start of the text.

    Args:
        text: Raw file text that may start with a BOM marker.

    Returns:
        Text with BOM removed.
    """
    if text.startswith("\ufeff"):
        logger.debug("Stripped UTF-8 BOM from CSV content")
        return text[1:]
    return text


def _resolve_columns(
    headers: list[str],
) -> dict[str, int | None]:
    """Map canonical field names to column indices using flexible matching.

    Args:
        headers: List of raw header strings from the CSV.

    Returns:
        Dictionary mapping canonical field names to their column index,
        or ``None`` if no matching column was found.
    """
    # Normalize headers: lowercase, strip whitespace and quotes
    normalized: list[str] = [
        h.strip().strip('"').strip("'").lower().replace(" ", "_")
        for h in headers
    ]

    mapping: dict[str, int | None] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        found_index: int | None = None
        for alias in aliases:
            if alias in normalized:
                found_index = normalized.index(alias)
                break
        mapping[canonical] = found_index

    logger.debug("Column mapping resolved: %s", mapping)
    return mapping


def _parse_location_string(raw: str) -> Location | None:
    """Parse a free-form location string into a Location object.

    Handles formats like ``"San Francisco, CA, US"`` or ``"New York"``.

    Args:
        raw: Raw location string.

    Returns:
        A Location object, or ``None`` if the string is empty.
    """
    if not raw or not raw.strip():
        return None

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    city = parts[0] if len(parts) >= 1 else ""
    region = parts[1] if len(parts) >= 2 else ""
    country = parts[2] if len(parts) >= 3 else ""
    return Location(city=city, region=region, country=country)


def _parse_skills_string(raw: str) -> list[str]:
    """Parse a delimited skills string into a list.

    Accepts comma, semicolon, or pipe delimiters.

    Args:
        raw: Raw skills string.

    Returns:
        List of skill strings with whitespace stripped.
    """
    if not raw or not raw.strip():
        return []

    for sep in ["|", ";", ","]:
        if sep in raw:
            return [s.strip() for s in raw.split(sep) if s.strip()]

    # Single skill or space-separated — return as one item
    return [raw.strip()] if raw.strip() else []


def _safe_float(value: str) -> float | None:
    """Safely parse a string to float, returning None on failure.

    Args:
        value: String representation of a number.

    Returns:
        Parsed float, or ``None`` if parsing fails.
    """
    if not value or not value.strip():
        return None
    cleaned = value.strip().rstrip("+")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _cell(row: dict[str, str] | list[str], index: int | None) -> str:
    """Safely extract a cell value by index.

    Args:
        row: A row of CSV data (as a dict keyed by header or a list).
        index: The column index to extract, or ``None``.

    Returns:
        Stripped cell value, or empty string if unavailable.
    """
    if index is None:
        return ""
    try:
        if isinstance(row, dict):
            keys = list(row.keys())
            if 0 <= index < len(keys):
                val = row[keys[index]]
                return str(val).strip() if val else ""
        elif isinstance(row, (list, tuple)):
            if 0 <= index < len(row):
                val = row[index]
                return str(val).strip() if val else ""
    except (IndexError, KeyError, TypeError):
        pass
    return ""


def ingest_csv(file_path: str) -> list[CandidateRecord]:
    """Ingest a recruiter CSV file and return candidate records.

    Reads the CSV, auto-detects the delimiter, maps columns flexibly,
    and converts each valid row into a ``CandidateRecord`` with
    ``source_type=RECRUITER_CSV``.

    Args:
        file_path: Absolute or relative path to the CSV file.

    Returns:
        List of ``CandidateRecord`` objects. Returns an empty list if
        the file is missing, empty, or entirely malformed.
    """
    logger.info("Starting CSV ingestion from: %s", file_path)

    if not file_path or not file_path.strip():
        logger.warning("Empty file path provided to CSV ingestor")
        return []

    if not os.path.isfile(file_path):
        logger.warning("CSV file not found: %s", file_path)
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    # Read file content with encoding fallback
    raw_content: str = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=encoding) as fh:
                raw_content = fh.read()
            logger.debug("Successfully read CSV with encoding: %s", encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            logger.debug("Encoding %s failed for %s, trying next", encoding, file_path)
            continue
        except OSError as exc:
            logger.error("OS error reading CSV file %s: %s", file_path, exc)
            return []

    if not raw_content.strip():
        logger.warning("CSV file is empty: %s", file_path)
        return []

    # Strip BOM and detect delimiter
    raw_content = _strip_bom(raw_content)
    sample = raw_content[:8192]
    delimiter = _detect_delimiter(sample)

    # Parse CSV
    reader_input = io.StringIO(raw_content)
    try:
        reader = csv.reader(reader_input, delimiter=delimiter)
        rows: list[list[str]] = list(reader)
    except csv.Error as exc:
        logger.error("Failed to parse CSV file %s: %s", file_path, exc)
        return []

    if len(rows) < 2:
        logger.warning("CSV file has no data rows (only header or empty): %s", file_path)
        # If there's exactly one row, it might be a header-only file
        if len(rows) == 1:
            return []
        return []

    headers = rows[0]
    data_rows = rows[1:]
    col_map = _resolve_columns(headers)

    # Check that we have at least one useful column
    useful_fields = ["full_name", "email", "phone"]
    has_useful = any(col_map.get(f) is not None for f in useful_fields)
    if not has_useful:
        logger.warning(
            "CSV has no recognizable identity columns (name/email/phone) in: %s. "
            "Headers found: %s",
            file_path,
            headers,
        )

    records: list[CandidateRecord] = []
    for row_idx, row in enumerate(data_rows, start=2):
        try:
            # Skip entirely empty rows
            if not any(cell.strip() for cell in row):
                logger.debug("Skipping empty row %d in %s", row_idx, file_path)
                continue

            full_name = _cell(row, col_map.get("full_name"))
            email = _cell(row, col_map.get("email"))
            phone = _cell(row, col_map.get("phone"))
            company = _cell(row, col_map.get("current_company"))
            title = _cell(row, col_map.get("title"))
            location_raw = _cell(row, col_map.get("location"))
            linkedin = _cell(row, col_map.get("linkedin"))
            github = _cell(row, col_map.get("github"))
            skills_raw = _cell(row, col_map.get("skills"))
            yoe_raw = _cell(row, col_map.get("years_experience"))

            # Skip rows with no identifying information
            if not full_name and not email and not phone:
                logger.debug(
                    "Skipping row %d with no name, email, or phone in %s",
                    row_idx, file_path,
                )
                continue

            # Build raw_data for debugging
            raw_row: dict[str, Any] = {}
            for i, header in enumerate(headers):
                if i < len(row):
                    raw_row[header] = row[i]

            # Build Links if we have any
            from candidate_transformer.models import Links
            links = None
            if linkedin or github:
                links = Links(linkedin=linkedin, github=github)

            record = CandidateRecord(
                source_type=SourceType.RECRUITER_CSV,
                source_file=os.path.abspath(file_path),
                full_name=full_name,
                emails=[email] if email else [],
                phones=[phone] if phone else [],
                current_company=company,
                headline=title,
                location=_parse_location_string(location_raw),
                links=links,
                skills=_parse_skills_string(skills_raw),
                years_experience=_safe_float(yoe_raw),
                raw_data=raw_row,
            )
            records.append(record)
            logger.debug(
                "Parsed CSV row %d: name=%r, email=%r",
                row_idx, full_name, email,
            )

        except Exception as exc:
            logger.warning(
                "Failed to parse CSV row %d in %s: %s",
                row_idx, file_path, exc,
            )
            continue

    logger.info(
        "CSV ingestion complete: %d records from %s", len(records), file_path
    )
    return records
