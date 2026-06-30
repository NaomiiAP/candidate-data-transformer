"""
Merge engine for combining multiple CandidateRecords into a CanonicalProfile.

Resolves conflicts using SOURCE_PRIORITY, deduplicates collections by
merge_key(), and tracks provenance for every field value chosen. Produces
a deterministic candidate_id from sorted normalized identity signals.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from candidate_transformer.models import (
    SOURCE_PRIORITY,
    CanonicalProfile,
    CandidateRecord,
    Education,
    Experience,
    Links,
    Location,
    ProvenanceRecord,
    Skill,
    SourceType,
)
from candidate_transformer.normalizers import (
    normalize_country,
    normalize_date,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_skill,
    normalize_url,
)

logger = logging.getLogger(__name__)


def _source_priority(source: SourceType) -> int:
    """Return the priority for a source type. Higher is more trusted."""
    return SOURCE_PRIORITY.get(source, 0)


def _sort_records_by_priority(
    records: list[CandidateRecord],
) -> list[CandidateRecord]:
    """Sort records by source priority, highest first (most trusted first).

    Uses source_file as a secondary sort key for deterministic ordering
    when priorities are equal.

    Args:
        records: List of candidate records.

    Returns:
        New list sorted by priority descending, then source_file ascending.
    """
    return sorted(
        records,
        key=lambda r: (-_source_priority(r.source_type), r.source_file),
    )


def _generate_candidate_id(
    emails: list[str],
    full_name: str,
) -> str:
    """Generate a deterministic candidate_id from identity signals.

    Uses sorted normalized emails + normalized name to produce a
    consistent SHA-256 hash. This ensures the same person always gets
    the same ID regardless of record ordering.

    Args:
        emails: List of normalized email addresses.
        full_name: Normalized full name.

    Returns:
        A deterministic hex string (first 16 chars of SHA-256).
    """
    components: list[str] = sorted(set(emails))
    components.append(full_name.lower().strip())
    key_string = "|".join(components)
    return hashlib.sha256(key_string.encode("utf-8")).hexdigest()[:16]


def _make_provenance(
    source: SourceType,
    field_name: str,
    original_value: Any,
    normalized_value: Any,
    normalizations: tuple[str, ...] = (),
    confidence: float = 0.0,
    timestamp: str = "",
) -> ProvenanceRecord:
    """Create a ProvenanceRecord with a consistent timestamp.

    Args:
        source: The source type.
        field_name: Field this provenance is for.
        original_value: Original raw value.
        normalized_value: Value after normalization.
        normalizations: Tuple of normalization names applied.
        confidence: Confidence score for this value.
        timestamp: Timestamp string. If empty, uses current UTC time.

    Returns:
        A frozen ProvenanceRecord instance.
    """
    ts = timestamp if timestamp else datetime.utcnow().isoformat()
    return ProvenanceRecord(
        source=source,
        field_name=field_name,
        original_value=original_value,
        normalized_value=normalized_value,
        normalizations_applied=normalizations,
        confidence=confidence,
        timestamp=ts,
    )


def _merge_full_name(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> str:
    """Pick the full_name from the highest priority source.

    Args:
        records: Records sorted by priority (highest first).
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        Normalized full name string.
    """
    for record in records:
        if record.full_name and record.full_name.strip():
            normalized = normalize_name(record.full_name)
            if normalized:
                provenance.append(_make_provenance(
                    source=record.source_type,
                    field_name="full_name",
                    original_value=record.full_name,
                    normalized_value=normalized,
                    normalizations=("normalize_name",),
                    timestamp=timestamp,
                ))
                return normalized

    return ""


def _merge_emails(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> list[str]:
    """Union all unique normalized emails from all records.

    Args:
        records: All candidate records.
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        Sorted list of unique normalized email addresses.
    """
    seen: set[str] = set()
    result: list[str] = []

    for record in records:
        for raw_email in record.emails:
            normalized = normalize_email(raw_email)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
                provenance.append(_make_provenance(
                    source=record.source_type,
                    field_name="emails",
                    original_value=raw_email,
                    normalized_value=normalized,
                    normalizations=("normalize_email",),
                    timestamp=timestamp,
                ))

    return sorted(result)


def _merge_phones(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> list[str]:
    """Union all unique E.164 normalized phones from all records.

    Args:
        records: All candidate records.
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        Sorted list of unique E.164 phone numbers.
    """
    seen: set[str] = set()
    result: list[str] = []

    for record in records:
        for raw_phone in record.phones:
            normalized = normalize_phone(raw_phone)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
                provenance.append(_make_provenance(
                    source=record.source_type,
                    field_name="phones",
                    original_value=raw_phone,
                    normalized_value=normalized,
                    normalizations=("normalize_phone", "E.164"),
                    timestamp=timestamp,
                ))

    return sorted(result)


def _merge_location(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> Optional[Location]:
    """Pick location from highest priority source with any data.

    Country codes are normalized to ISO-3166 Alpha-2.

    Args:
        records: Records sorted by priority (highest first).
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        A Location instance, or None if no location data found.
    """
    for record in records:
        loc = record.location
        if loc is None:
            continue

        if not (loc.city or loc.region or loc.country):
            continue

        country = normalize_country(loc.country) if loc.country else ""
        merged_location = Location(
            city=loc.city.strip() if loc.city else "",
            region=loc.region.strip() if loc.region else "",
            country=country,
        )

        provenance.append(_make_provenance(
            source=record.source_type,
            field_name="location",
            original_value={
                "city": loc.city,
                "region": loc.region,
                "country": loc.country,
            },
            normalized_value={
                "city": merged_location.city,
                "region": merged_location.region,
                "country": merged_location.country,
            },
            normalizations=("normalize_country",) if loc.country else (),
            timestamp=timestamp,
        ))

        return merged_location

    return None


def _merge_links(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> Optional[Links]:
    """Merge link fields from all records, preferring highest priority for conflicts.

    Args:
        records: Records sorted by priority (highest first).
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        A Links instance, or None if no links found.
    """
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    other: list[str] = []
    other_seen: set[str] = set()

    linkedin_source: Optional[SourceType] = None
    github_source: Optional[SourceType] = None
    portfolio_source: Optional[SourceType] = None

    for record in records:
        if record.links is None:
            continue

        # LinkedIn — first (highest priority) wins
        if record.links.linkedin and not linkedin:
            linkedin = normalize_url(record.links.linkedin)
            linkedin_source = record.source_type

        # GitHub — first (highest priority) wins
        if record.links.github and not github:
            github = normalize_url(record.links.github)
            github_source = record.source_type

        # Portfolio — first (highest priority) wins
        if record.links.portfolio and not portfolio:
            portfolio = normalize_url(record.links.portfolio)
            portfolio_source = record.source_type

        # Other — union all unique
        for url in record.links.other:
            normalized = normalize_url(url)
            if normalized and normalized not in other_seen:
                other_seen.add(normalized)
                other.append(normalized)

    if not any([linkedin, github, portfolio, other]):
        return None

    # Record provenance for each link type
    if linkedin and linkedin_source:
        provenance.append(_make_provenance(
            source=linkedin_source,
            field_name="links",
            original_value={"type": "linkedin"},
            normalized_value=linkedin,
            normalizations=("normalize_url",),
            timestamp=timestamp,
        ))
    if github and github_source:
        provenance.append(_make_provenance(
            source=github_source,
            field_name="links",
            original_value={"type": "github"},
            normalized_value=github,
            normalizations=("normalize_url",),
            timestamp=timestamp,
        ))
    if portfolio and portfolio_source:
        provenance.append(_make_provenance(
            source=portfolio_source,
            field_name="links",
            original_value={"type": "portfolio"},
            normalized_value=portfolio,
            normalizations=("normalize_url",),
            timestamp=timestamp,
        ))

    return Links(
        linkedin=linkedin,
        github=github,
        portfolio=portfolio,
        other=sorted(other),
    )


def _merge_headline(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> str:
    """Pick headline from highest priority source.

    Args:
        records: Records sorted by priority (highest first).
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        Headline string.
    """
    for record in records:
        if record.headline and record.headline.strip():
            headline = record.headline.strip()
            provenance.append(_make_provenance(
                source=record.source_type,
                field_name="headline",
                original_value=headline,
                normalized_value=headline,
                timestamp=timestamp,
            ))
            return headline

    return ""


def _compute_years_from_experience(
    experience_list: list[Experience],
) -> Optional[float]:
    """Estimate total years of experience from experience date ranges.

    Handles overlapping date ranges by computing total unique months.

    Args:
        experience_list: List of experience entries with start/end dates.

    Returns:
        Estimated years of experience, or None if no dates are available.
    """
    if not experience_list:
        return None

    # Collect all date ranges as (start_ym, end_ym) tuples
    ranges: list[tuple[int, int]] = []

    for exp in experience_list:
        if not exp.start:
            continue

        start_ym = _date_to_year_month(exp.start)
        if start_ym is None:
            continue

        if exp.end and exp.end.lower() != "present":
            end_ym = _date_to_year_month(exp.end)
        else:
            # "present" or empty end → use current date
            now = datetime.utcnow()
            end_ym = now.year * 12 + now.month

        if end_ym is None:
            continue

        if end_ym >= start_ym:
            ranges.append((start_ym, end_ym))

    if not ranges:
        return None

    # Merge overlapping ranges and compute total months
    ranges.sort()
    merged: list[tuple[int, int]] = [ranges[0]]
    for start, end in ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    total_months = sum(end - start for start, end in merged)
    return round(total_months / 12.0, 1)


def _date_to_year_month(date_str: str) -> Optional[int]:
    """Convert a YYYY-MM date string to a single year*12+month integer.

    Args:
        date_str: Date in YYYY-MM format.

    Returns:
        Integer representing year*12+month, or None on failure.
    """
    normalized = normalize_date(date_str)
    if not normalized or normalized == "present":
        return None

    parts = normalized.split("-")
    if len(parts) != 2:
        return None

    try:
        year = int(parts[0])
        month = int(parts[1])
        return year * 12 + month
    except ValueError:
        return None


def _merge_years_experience(
    records: list[CandidateRecord],
    experience_list: list[Experience],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> Optional[float]:
    """Determine years_experience from records or computed from dates.

    Picks the explicitly provided value from the highest priority source.
    Falls back to computing from experience date ranges if no explicit
    value is provided.

    Args:
        records: Records sorted by priority (highest first).
        experience_list: Merged experience entries.
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        Years of experience, or None if not determinable.
    """
    # Try explicit values first
    for record in records:
        if record.years_experience is not None and record.years_experience >= 0:
            provenance.append(_make_provenance(
                source=record.source_type,
                field_name="years_experience",
                original_value=record.years_experience,
                normalized_value=record.years_experience,
                timestamp=timestamp,
            ))
            return record.years_experience

    # Compute from experience dates
    computed = _compute_years_from_experience(experience_list)
    if computed is not None:
        provenance.append(_make_provenance(
            source=SourceType.ATS_JSON,  # Mark as computed
            field_name="years_experience",
            original_value=None,
            normalized_value=computed,
            normalizations=("computed_from_experience",),
            timestamp=timestamp,
        ))

    return computed


def _merge_skills(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> list[Skill]:
    """Union all skills, canonicalize names, and compute per-skill confidence.

    Confidence is based on how many distinct sources mention the skill.

    Args:
        records: All candidate records.
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        Sorted list of Skill instances with confidence scores.
    """
    # Map: canonical_name -> set of source type values
    skill_sources: dict[str, set[str]] = {}
    # Track which SourceTypes contributed each skill for confidence
    skill_source_types: dict[str, set[SourceType]] = {}

    for record in records:
        for raw_skill in record.skills:
            canonical = normalize_skill(raw_skill)
            if not canonical:
                continue

            if canonical not in skill_sources:
                skill_sources[canonical] = set()
                skill_source_types[canonical] = set()

            skill_sources[canonical].add(record.source_type.value)
            skill_source_types[canonical].add(record.source_type)

    # Build Skill instances with confidence
    skills: list[Skill] = []
    for name in sorted(skill_sources.keys()):
        sources = sorted(skill_sources[name])
        source_types = skill_source_types[name]
        count = len(source_types)

        # Use the highest-priority source for base confidence
        best_source = max(source_types, key=lambda s: _source_priority(s))
        from candidate_transformer.confidence import compute_field_confidence

        confidence = compute_field_confidence(best_source, count)

        skills.append(Skill(
            name=name,
            confidence=confidence,
            sources=sources,
        ))

    if skills:
        provenance.append(_make_provenance(
            source=records[0].source_type,
            field_name="skills",
            original_value=[s.name for s in skills],
            normalized_value=[s.name for s in skills],
            normalizations=("normalize_skill", "union", "confidence"),
            timestamp=timestamp,
        ))

    return skills


def _merge_experience(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> list[Experience]:
    """Deduplicate and merge experience entries across records.

    Uses merge_key() for deduplication. When duplicates are found,
    fields from the highest priority source win. Dates are normalized.

    Args:
        records: Records sorted by priority (highest first).
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        List of merged Experience instances, sorted by start date descending.
    """
    # Map: merge_key -> (Experience, SourceType)
    merged: dict[str, tuple[Experience, SourceType]] = {}

    for record in records:
        for exp in record.experience:
            key = exp.merge_key()
            if key not in merged:
                # First occurrence (highest priority) — normalize dates
                normalized_exp = Experience(
                    company=exp.company.strip() if exp.company else "",
                    title=exp.title.strip() if exp.title else "",
                    start=normalize_date(exp.start) if exp.start else "",
                    end=normalize_date(exp.end) if exp.end else "",
                    summary=exp.summary.strip() if exp.summary else "",
                )
                merged[key] = (normalized_exp, record.source_type)
            else:
                # Fill in empty fields from lower-priority sources
                existing, _ = merged[key]
                if not existing.company and exp.company:
                    existing.company = exp.company.strip()
                if not existing.title and exp.title:
                    existing.title = exp.title.strip()
                if not existing.start and exp.start:
                    existing.start = normalize_date(exp.start)
                if not existing.end and exp.end:
                    existing.end = normalize_date(exp.end)
                if not existing.summary and exp.summary:
                    existing.summary = exp.summary.strip()

    # Sort by start date descending (most recent first)
    result: list[Experience] = []
    for key in sorted(merged.keys()):
        exp, source = merged[key]
        result.append(exp)

    result.sort(key=lambda e: e.start if e.start else "", reverse=True)

    if result:
        provenance.append(_make_provenance(
            source=records[0].source_type,
            field_name="experience",
            original_value=[e.company for e in result],
            normalized_value=[e.company for e in result],
            normalizations=("normalize_date", "deduplicate"),
            timestamp=timestamp,
        ))

    return result


def _merge_education(
    records: list[CandidateRecord],
    provenance: list[ProvenanceRecord],
    timestamp: str,
) -> list[Education]:
    """Deduplicate and merge education entries across records.

    Uses merge_key() for deduplication. When duplicates are found,
    fields from the highest priority source win.

    Args:
        records: Records sorted by priority (highest first).
        provenance: Provenance list to append to.
        timestamp: Consistent timestamp for provenance.

    Returns:
        List of merged Education instances, sorted by end_year descending.
    """
    merged: dict[str, tuple[Education, SourceType]] = {}

    for record in records:
        for edu in record.education:
            key = edu.merge_key()
            if key not in merged:
                normalized_edu = Education(
                    institution=edu.institution.strip() if edu.institution else "",
                    degree=edu.degree.strip() if edu.degree else "",
                    field=edu.field.strip() if edu.field else "",
                    end_year=edu.end_year.strip() if edu.end_year else "",
                )
                merged[key] = (normalized_edu, record.source_type)
            else:
                existing, _ = merged[key]
                if not existing.institution and edu.institution:
                    existing.institution = edu.institution.strip()
                if not existing.degree and edu.degree:
                    existing.degree = edu.degree.strip()
                if not existing.field and edu.field:
                    existing.field = edu.field.strip()
                if not existing.end_year and edu.end_year:
                    existing.end_year = edu.end_year.strip()

    result: list[Education] = []
    for key in sorted(merged.keys()):
        edu, source = merged[key]
        result.append(edu)

    result.sort(key=lambda e: e.end_year if e.end_year else "", reverse=True)

    if result:
        provenance.append(_make_provenance(
            source=records[0].source_type,
            field_name="education",
            original_value=[e.institution for e in result],
            normalized_value=[e.institution for e in result],
            normalizations=("deduplicate",),
            timestamp=timestamp,
        ))

    return result


def merge_records(
    records: list[CandidateRecord],
) -> CanonicalProfile:
    """Merge multiple CandidateRecords into a single CanonicalProfile.

    This is the main entry point for the merge engine. It:
      1. Sorts records by source priority (highest first)
      2. Merges each field using priority-based conflict resolution
      3. Deduplicates collections by merge_key()
      4. Normalizes all field values
      5. Tracks provenance for every chosen value
      6. Generates a deterministic candidate_id

    Args:
        records: List of CandidateRecords to merge. Must be non-empty.

    Returns:
        A fully populated CanonicalProfile.

    Raises:
        ValueError: If records list is empty.
    """
    if not records:
        raise ValueError("Cannot merge an empty list of records.")

    logger.info("Merging %d records into a canonical profile.", len(records))

    # Sort by priority (highest first) for conflict resolution
    sorted_records = _sort_records_by_priority(records)

    # Consistent timestamp for all provenance in this merge
    timestamp = datetime.utcnow().isoformat()

    provenance: list[ProvenanceRecord] = []

    # Merge each field
    full_name = _merge_full_name(sorted_records, provenance, timestamp)
    emails = _merge_emails(sorted_records, provenance, timestamp)
    phones = _merge_phones(sorted_records, provenance, timestamp)
    location = _merge_location(sorted_records, provenance, timestamp)
    links = _merge_links(sorted_records, provenance, timestamp)
    headline = _merge_headline(sorted_records, provenance, timestamp)
    experience = _merge_experience(sorted_records, provenance, timestamp)
    education = _merge_education(sorted_records, provenance, timestamp)
    skills = _merge_skills(sorted_records, provenance, timestamp)
    years_experience = _merge_years_experience(
        sorted_records, experience, provenance, timestamp
    )

    # Generate deterministic candidate ID
    candidate_id = _generate_candidate_id(emails, full_name)

    profile = CanonicalProfile(
        candidate_id=candidate_id,
        full_name=full_name,
        emails=emails,
        phones=phones,
        location=location,
        links=links,
        headline=headline,
        years_experience=years_experience,
        skills=skills,
        experience=experience,
        education=education,
        provenance=provenance,
        source_records=records,
    )

    logger.info(
        "Merge complete: candidate_id=%s, name=%s, %d emails, %d skills, "
        "%d experience, %d education.",
        candidate_id,
        full_name,
        len(emails),
        len(skills),
        len(experience),
        len(education),
    )

    return profile
