"""
Pipeline orchestrator for the Candidate Data Transformer.

Ties together all pipeline stages: loading sources, extracting fields,
normalizing, entity matching, merging, confidence scoring, provenance
tracking, projection, and validation. Provides a single entry point
``run_pipeline()`` that accepts raw source paths and returns a validated,
projected JSON-serializable output.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Optional

from candidate_transformer.confidence import compute_profile_confidence
from candidate_transformer.entity_matcher import match_records
from candidate_transformer.ingestors import (
    ingest_csv,
    ingest_json,
    ingest_github,
    ingest_linkedin,
    ingest_resume_pdf,
    ingest_resume_docx,
    ingest_notes,
)
from candidate_transformer.merge_engine import merge_records
from candidate_transformer.models import (
    CandidateRecord,
    Education,
    Experience,
    Links,
    Location,
    SourceType,
)
from candidate_transformer.normalizers import (
    normalize_date,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_skill,
    normalize_url,
)
from candidate_transformer.projection import ProjectionConfig, project
from candidate_transformer.schema_validator import validate_output

logger = logging.getLogger(__name__)

# Map of source type name strings to SourceType enum values
_SOURCE_TYPE_MAP: dict[str, SourceType] = {
    "recruiter_csv": SourceType.RECRUITER_CSV,
    "ats_json": SourceType.ATS_JSON,
    "github": SourceType.GITHUB,
    "linkedin": SourceType.LINKEDIN,
    "resume_pdf": SourceType.RESUME_PDF,
    "resume_docx": SourceType.RESUME_DOCX,
    "recruiter_notes": SourceType.RECRUITER_NOTES,
}


def _resolve_source_type(name: str) -> Optional[SourceType]:
    """Resolve a source type name string to a SourceType enum value.

    Args:
        name: Source type name (case-insensitive).

    Returns:
        SourceType enum value, or None if not recognized.
    """
    normalized = name.strip().lower()
    source_type = _SOURCE_TYPE_MAP.get(normalized)
    if source_type is None:
        logger.warning("Unknown source type: '%s'", name)
    return source_type


def _load_csv_records(
    file_path: str, source_type: SourceType
) -> list[CandidateRecord]:
    """Load candidate records from a CSV file.

    Expected CSV columns (all optional):
        full_name, email, phone, city, region, country,
        linkedin, github, portfolio, headline, years_experience,
        skills (semicolon-delimited), company, title, start, end,
        summary, institution, degree, field_of_study, end_year

    Args:
        file_path: Path to the CSV file.
        source_type: The source type for provenance.

    Returns:
        List of CandidateRecord instances extracted from the file.
    """
    records: list[CandidateRecord] = []
    path = Path(file_path)

    if not path.exists():
        logger.error("CSV file not found: %s", file_path)
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):
                try:
                    record = _csv_row_to_record(row, source_type, file_path)
                    records.append(record)
                except Exception as e:
                    logger.warning(
                        "Skipping CSV row %d in %s: %s",
                        row_num,
                        file_path,
                        str(e),
                    )
    except Exception as e:
        logger.error("Failed to read CSV file %s: %s", file_path, str(e))

    logger.info("Loaded %d records from CSV: %s", len(records), file_path)
    return records


def _csv_row_to_record(
    row: dict[str, str],
    source_type: SourceType,
    file_path: str,
) -> CandidateRecord:
    """Convert a single CSV row dictionary to a CandidateRecord.

    Args:
        row: Dictionary from csv.DictReader.
        source_type: Source type for the record.
        file_path: Source file path.

    Returns:
        A populated CandidateRecord.
    """
    emails: list[str] = []
    raw_email = row.get("email", "").strip()
    if raw_email:
        emails = [e.strip() for e in raw_email.split(";") if e.strip()]

    phones: list[str] = []
    raw_phone = row.get("phone", "").strip()
    if raw_phone:
        phones = [p.strip() for p in raw_phone.split(";") if p.strip()]

    # Location
    location: Optional[Location] = None
    city = row.get("city", "").strip()
    region = row.get("region", "").strip()
    country = row.get("country", "").strip()
    if city or region or country:
        location = Location(city=city, region=region, country=country)

    # Links
    links: Optional[Links] = None
    linkedin = row.get("linkedin", "").strip()
    github = row.get("github", "").strip()
    portfolio = row.get("portfolio", "").strip()
    if linkedin or github or portfolio:
        links = Links(linkedin=linkedin, github=github, portfolio=portfolio)

    # Skills
    raw_skills = row.get("skills", "").strip()
    skills = [s.strip() for s in raw_skills.split(";") if s.strip()] if raw_skills else []

    # Years of experience
    years_exp: Optional[float] = None
    raw_years = row.get("years_experience", "").strip()
    if raw_years:
        try:
            years_exp = float(raw_years)
        except ValueError:
            logger.debug("Invalid years_experience: %s", raw_years)

    # Experience
    experience: list[Experience] = []
    company = row.get("company", "").strip()
    title = row.get("title", "").strip()
    if company or title:
        experience.append(Experience(
            company=company,
            title=title,
            start=row.get("start", "").strip(),
            end=row.get("end", "").strip(),
            summary=row.get("summary", "").strip(),
        ))

    # Education
    education: list[Education] = []
    institution = row.get("institution", "").strip()
    degree = row.get("degree", "").strip()
    if institution or degree:
        education.append(Education(
            institution=institution,
            degree=degree,
            field=row.get("field_of_study", "").strip(),
            end_year=row.get("end_year", "").strip(),
        ))

    return CandidateRecord(
        source_type=source_type,
        source_file=file_path,
        full_name=row.get("full_name", "").strip(),
        emails=emails,
        phones=phones,
        location=location,
        links=links,
        headline=row.get("headline", "").strip(),
        years_experience=years_exp,
        current_company=company,
        skills=skills,
        experience=experience,
        education=education,
        raw_data=dict(row),
    )


def _load_json_records(
    file_path: str, source_type: SourceType
) -> list[CandidateRecord]:
    """Load candidate records from a JSON file.

    Supports both a single JSON object and a JSON array of objects.

    Expected JSON fields (all optional):
        full_name, emails (array), phones (array),
        location: {city, region, country},
        links: {linkedin, github, portfolio, other},
        headline, years_experience, skills (array of strings),
        experience: [{company, title, start, end, summary}],
        education: [{institution, degree, field, end_year}]

    Args:
        file_path: Path to the JSON file.
        source_type: The source type for provenance.

    Returns:
        List of CandidateRecord instances extracted from the file.
    """
    records: list[CandidateRecord] = []
    path = Path(file_path)

    if not path.exists():
        logger.error("JSON file not found: %s", file_path)
        raise FileNotFoundError(f"JSON file not found: {file_path}")

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error("Failed to read JSON file %s: %s", file_path, str(e))
        return records

    # Normalize to list of dicts
    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
    else:
        logger.error(
            "Unexpected JSON structure in %s: expected dict or list.",
            file_path,
        )
        return records

    for idx, item in enumerate(items):
        try:
            record = _json_item_to_record(item, source_type, file_path)
            records.append(record)
        except Exception as e:
            logger.warning(
                "Skipping JSON item %d in %s: %s", idx, file_path, str(e)
            )

    logger.info("Loaded %d records from JSON: %s", len(records), file_path)
    return records


def _json_item_to_record(
    item: dict[str, Any],
    source_type: SourceType,
    file_path: str,
) -> CandidateRecord:
    """Convert a single JSON item to a CandidateRecord.

    Args:
        item: Dictionary from JSON parsing.
        source_type: Source type for the record.
        file_path: Source file path.

    Returns:
        A populated CandidateRecord.
    """
    # Emails
    raw_emails = item.get("emails", item.get("email", []))
    if isinstance(raw_emails, str):
        emails = [raw_emails] if raw_emails.strip() else []
    elif isinstance(raw_emails, list):
        emails = [str(e).strip() for e in raw_emails if str(e).strip()]
    else:
        emails = []

    # Phones
    raw_phones = item.get("phones", item.get("phone", []))
    if isinstance(raw_phones, str):
        phones = [raw_phones] if raw_phones.strip() else []
    elif isinstance(raw_phones, list):
        phones = [str(p).strip() for p in raw_phones if str(p).strip()]
    else:
        phones = []

    # Location
    location: Optional[Location] = None
    raw_location = item.get("location")
    if isinstance(raw_location, dict):
        city = str(raw_location.get("city", "")).strip()
        region = str(raw_location.get("region", "")).strip()
        country = str(raw_location.get("country", "")).strip()
        if city or region or country:
            location = Location(city=city, region=region, country=country)

    # Links
    links: Optional[Links] = None
    raw_links = item.get("links")
    if isinstance(raw_links, dict):
        linkedin = str(raw_links.get("linkedin", "")).strip()
        github = str(raw_links.get("github", "")).strip()
        portfolio = str(raw_links.get("portfolio", "")).strip()
        other_raw = raw_links.get("other", [])
        other_links = (
            [str(u).strip() for u in other_raw if str(u).strip()]
            if isinstance(other_raw, list)
            else []
        )
        if linkedin or github or portfolio or other_links:
            links = Links(
                linkedin=linkedin,
                github=github,
                portfolio=portfolio,
                other=other_links,
            )

    # Skills
    raw_skills = item.get("skills", [])
    if isinstance(raw_skills, list):
        skills = [str(s).strip() for s in raw_skills if str(s).strip()]
    elif isinstance(raw_skills, str):
        skills = [s.strip() for s in raw_skills.split(";") if s.strip()]
    else:
        skills = []

    # Years of experience
    years_exp: Optional[float] = None
    raw_years = item.get("years_experience")
    if raw_years is not None:
        try:
            years_exp = float(raw_years)
        except (ValueError, TypeError):
            logger.debug("Invalid years_experience: %s", raw_years)

    # Experience
    experience: list[Experience] = []
    raw_experience = item.get("experience", [])
    if isinstance(raw_experience, list):
        for exp_item in raw_experience:
            if isinstance(exp_item, dict):
                experience.append(Experience(
                    company=str(exp_item.get("company", "")).strip(),
                    title=str(exp_item.get("title", "")).strip(),
                    start=str(exp_item.get("start", "")).strip(),
                    end=str(exp_item.get("end", "")).strip(),
                    summary=str(exp_item.get("summary", "")).strip(),
                ))

    # Education
    education: list[Education] = []
    raw_education = item.get("education", [])
    if isinstance(raw_education, list):
        for edu_item in raw_education:
            if isinstance(edu_item, dict):
                education.append(Education(
                    institution=str(edu_item.get("institution", "")).strip(),
                    degree=str(edu_item.get("degree", "")).strip(),
                    field=str(edu_item.get("field", "")).strip(),
                    end_year=str(edu_item.get("end_year", "")).strip(),
                ))

    return CandidateRecord(
        source_type=source_type,
        source_file=file_path,
        full_name=str(item.get("full_name", "")).strip(),
        emails=emails,
        phones=phones,
        location=location,
        links=links,
        headline=str(item.get("headline", "")).strip(),
        years_experience=years_exp,
        current_company=str(item.get("current_company", "")).strip(),
        skills=skills,
        experience=experience,
        education=education,
        raw_data=item,
    )


def _load_records_from_file(
    file_path: str, source_type: SourceType
) -> list[CandidateRecord]:
    """Load candidate records using the appropriate ingestor for the source type.

    Args:
        file_path: Path to the source file or username/URL.
        source_type: The source type for provenance tracking.

    Returns:
        List of CandidateRecord instances.
    """
    if source_type == SourceType.RECRUITER_CSV:
        return ingest_csv(file_path)
    elif source_type == SourceType.ATS_JSON:
        return ingest_json(file_path)
    elif source_type == SourceType.GITHUB:
        return ingest_github(file_path)
    elif source_type == SourceType.LINKEDIN:
        return ingest_linkedin(file_path)
    elif source_type == SourceType.RESUME_PDF:
        if file_path.lower().endswith(".txt"):
            from candidate_transformer.ingestors.resume_ingestor import ingest_resume_txt
            return ingest_resume_txt(file_path)
        return ingest_resume_pdf(file_path)
    elif source_type == SourceType.RESUME_DOCX:
        if file_path.lower().endswith(".txt"):
            from candidate_transformer.ingestors.resume_ingestor import ingest_resume_txt
            return ingest_resume_txt(file_path)
        return ingest_resume_docx(file_path)
    elif source_type == SourceType.RECRUITER_NOTES:
        return ingest_notes(file_path)
    else:
        logger.warning("Unsupported source type: %s", source_type)
        return []


def run_pipeline(
    sources: dict[str, str | list[str]],
    config: Optional[ProjectionConfig] = None,
) -> dict[str, Any]:
    """Run the full candidate data transformation pipeline.

    Orchestrates all pipeline stages in order:
      1. Load Sources — read files for each source type
      2. Extract Fields — parse records from raw data
      3. Normalize — apply field normalizers
      4. Entity Matching — group records referring to the same person
      5. Merge — combine groups into canonical profiles
      6. Confidence — compute per-field and overall confidence
      7. Provenance — track origin of every field value
      8. Projection — transform to output schema
      9. Validation — validate against JSON Schema
      10. Output — return the final result

    If multiple candidate groups are found, returns a dict with a
    'candidates' key containing a list. For a single candidate, returns
    the profile dict directly.

    Args:
        sources: Dictionary mapping source type names to file paths.
            Keys are source type names (e.g., 'recruiter_csv', 'ats_json').
            Values are a single file path string or a list of file paths.
        config: Optional ProjectionConfig for customizing output. If None,
            uses default projection (full schema).

    Returns:
        JSON-serializable dictionary with the pipeline output.
        Contains either a single candidate profile or a 'candidates'
        list if multiple distinct candidates are found.

    Example:
        >>> result = run_pipeline({
        ...     "recruiter_csv": "data/recruiter.csv",
        ...     "ats_json": ["data/ats1.json", "data/ats2.json"],
        ... })
    """
    logger.info("=" * 60)
    logger.info("PIPELINE START")
    logger.info("=" * 60)

    if config is None:
        config = ProjectionConfig()

    # ---------------------------------------------------------------
    # Stage 1: Load Sources
    # ---------------------------------------------------------------
    logger.info("Stage 1/10: Loading sources...")
    all_records: list[CandidateRecord] = []

    for source_name, paths in sorted(sources.items()):
        source_type = _resolve_source_type(source_name)
        if source_type is None:
            logger.warning("Skipping unknown source type: %s", source_name)
            continue

        # Normalize paths to list
        if isinstance(paths, str):
            path_list = [paths]
        elif isinstance(paths, list):
            path_list = [str(p) for p in paths]
        else:
            logger.warning(
                "Invalid paths for source '%s': expected str or list, "
                "got %s.",
                source_name,
                type(paths).__name__,
            )
            continue

        for file_path in path_list:
            logger.info(
                "Loading %s from: %s", source_type.value, file_path
            )
            records = _load_records_from_file(file_path, source_type)
            all_records.extend(records)

    logger.info(
        "Stage 1 complete: loaded %d total records.", len(all_records)
    )

    if not all_records:
        logger.warning("No records loaded — returning empty result.")
        return _build_empty_result(config)

    # ---------------------------------------------------------------
    # Stage 2–3: Extract Fields & Normalize (done during loading)
    # ---------------------------------------------------------------
    logger.info("Stage 2-3/10: Field extraction and normalization complete.")

    # ---------------------------------------------------------------
    # Stage 4: Entity Matching
    # ---------------------------------------------------------------
    logger.info("Stage 4/10: Entity matching...")
    groups = match_records(all_records)
    logger.info(
        "Stage 4 complete: %d record group(s) identified.", len(groups)
    )

    # ---------------------------------------------------------------
    # Stage 5–7: Merge, Confidence, Provenance
    # ---------------------------------------------------------------
    logger.info("Stage 5-7/10: Merging, confidence scoring, provenance...")
    profiles: list[dict[str, Any]] = []

    for group_idx, group in enumerate(groups):
        logger.info(
            "Merging group %d/%d (%d records)...",
            group_idx + 1,
            len(groups),
            len(group),
        )

        # Stage 5: Merge
        profile = merge_records(group)

        # Stage 6: Confidence
        profile = compute_profile_confidence(profile)

        # Stage 7: Provenance is tracked during merge (already done)

        # ---------------------------------------------------------------
        # Stage 8: Projection
        # ---------------------------------------------------------------
        logger.info("Stage 8/10: Projecting output...")
        projected = project(profile, config)
        projected["_sources"] = sorted(list(set(p.source.value for p in profile.provenance if p.source)))
        projected["_overall_confidence"] = profile.overall_confidence


        # ---------------------------------------------------------------
        # Stage 9: Validation
        # ---------------------------------------------------------------
        if not config.fields:
            logger.info("Stage 9/10: Validating default output schema...")
            errors = validate_output(projected)
            if errors:
                logger.warning(
                    "Validation errors for group %d: %s",
                    group_idx + 1,
                    errors,
                )
                projected["_validation_errors"] = errors
            else:
                logger.info("Validation passed for group %d.", group_idx + 1)
        else:
            logger.info("Stage 9/10: Custom fields projected; skipping default schema validation.")

        profiles.append(projected)

    # ---------------------------------------------------------------
    # Stage 10: Output
    # ---------------------------------------------------------------
    logger.info("Stage 10/10: Building final output...")

    if len(profiles) == 1:
        result = profiles[0]
    else:
        result = {"candidates": profiles, "count": len(profiles)}

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE — %d candidate(s) produced.", len(profiles))
    logger.info("=" * 60)

    return result


def _build_empty_result(config: ProjectionConfig) -> dict[str, Any]:
    """Build an empty result when no records are loaded.

    Args:
        config: The projection config (used for confidence/provenance flags).

    Returns:
        A dictionary with empty fields matching the output schema.
    """
    result: dict[str, Any] = {
        "candidate_id": "",
        "full_name": "",
        "emails": [],
        "phones": [],
        "location": {"city": "", "region": "", "country": ""},
        "links": {
            "linkedin": "",
            "github": "",
            "portfolio": "",
            "other": [],
        },
        "headline": "",
        "years_experience": None,
        "skills": [],
        "experience": [],
        "education": [],
    }

    if config.include_provenance:
        result["provenance"] = []

    if config.include_confidence:
        result["overall_confidence"] = 0.0

    result["_validation_errors"] = [
        "No records loaded — empty result."
    ]

    return result
