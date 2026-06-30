"""
Confidence scoring for merged candidate profiles.

Computes per-field and overall confidence scores for a CanonicalProfile.
Confidence is derived from source trustworthiness (SOURCE_BASE_CONFIDENCE),
the number of corroborating sources, and data completeness.
"""

from __future__ import annotations

import logging
from typing import Any

from candidate_transformer.models import (
    SOURCE_BASE_CONFIDENCE,
    CanonicalProfile,
    SourceType,
)

logger = logging.getLogger(__name__)

# Field weights for overall confidence calculation (must sum to 1.0)
FIELD_WEIGHTS: dict[str, float] = {
    "full_name": 0.20,
    "emails": 0.15,
    "phones": 0.10,
    "location": 0.10,
    "skills": 0.15,
    "experience": 0.15,
    "education": 0.10,
    "headline": 0.05,
}

# Corroboration bonus per additional source (beyond the first)
_CORROBORATION_BONUS: float = 0.1

# Maximum confidence value
_MAX_CONFIDENCE: float = 1.0


def compute_field_confidence(
    source: SourceType,
    corroboration_count: int,
) -> float:
    """Compute confidence for a single field value.

    Formula: base_confidence * (1 + 0.1 * (corroboration_count - 1))
    Capped at 1.0.

    Args:
        source: The source type that provided the winning value.
        corroboration_count: Total number of sources that agree on
            this value (including the primary source). Minimum 1.

    Returns:
        Confidence score in [0.0, 1.0], rounded to 4 decimal places.
    """
    if corroboration_count < 1:
        corroboration_count = 1

    base = SOURCE_BASE_CONFIDENCE.get(source, 0.5)
    bonus_factor = 1.0 + _CORROBORATION_BONUS * (corroboration_count - 1)
    confidence = base * bonus_factor

    return round(min(confidence, _MAX_CONFIDENCE), 4)


def compute_empty_field_confidence() -> float:
    """Return confidence for a field with no value.

    Returns:
        0.0 — fields with no value contribute zero confidence.
    """
    return 0.0


def _has_value(value: Any) -> bool:
    """Check whether a field has a meaningful (non-empty) value.

    Args:
        value: The field value to check.

    Returns:
        True if the value is present and non-empty.
    """
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True


def _count_sources_for_field(
    profile: CanonicalProfile,
    field_name: str,
) -> tuple[SourceType | None, int]:
    """Determine the winning source and corroboration count for a field.

    Examines provenance records attached to the profile to find how many
    distinct sources contributed to a particular field.

    Args:
        profile: The canonical profile with provenance records.
        field_name: The field name to query.

    Returns:
        Tuple of (winning_source, corroboration_count).
        winning_source is None if the field has no provenance.
    """
    matching_provenance = [
        p for p in profile.provenance if p.field_name == field_name
    ]

    if not matching_provenance:
        return None, 0

    # The winning source is the one with the highest priority
    from candidate_transformer.models import SOURCE_PRIORITY

    best_source: SourceType | None = None
    best_priority: int = -1
    unique_sources: set[SourceType] = set()

    for prov in matching_provenance:
        unique_sources.add(prov.source)
        priority = SOURCE_PRIORITY.get(prov.source, 0)
        if priority > best_priority:
            best_priority = priority
            best_source = prov.source

    return best_source, len(unique_sources)


def compute_profile_confidence(
    profile: CanonicalProfile,
) -> CanonicalProfile:
    """Compute all confidence scores for a CanonicalProfile.

    Calculates per-field confidence based on source priority and
    corroboration, then computes an overall weighted average.

    Mutates the profile in-place by setting:
      - profile.field_confidence (dict of field -> confidence)
      - profile.overall_confidence (weighted average)

    Args:
        profile: The canonical profile to score. Modified in-place.

    Returns:
        The same profile instance with confidence scores populated.
    """
    logger.info(
        "Computing confidence scores for candidate: %s",
        profile.candidate_id,
    )

    field_values: dict[str, Any] = {
        "full_name": profile.full_name,
        "emails": profile.emails,
        "phones": profile.phones,
        "location": profile.location,
        "skills": profile.skills,
        "experience": profile.experience,
        "education": profile.education,
        "headline": profile.headline,
    }

    field_confidence: dict[str, float] = {}

    for field_name, value in field_values.items():
        if not _has_value(value):
            field_confidence[field_name] = compute_empty_field_confidence()
            logger.debug("Field '%s' is empty — confidence 0.0", field_name)
            continue

        # For location, check if any sub-field has a value
        if field_name == "location" and profile.location is not None:
            has_location_data = bool(
                profile.location.city
                or profile.location.region
                or profile.location.country
            )
            if not has_location_data:
                field_confidence[field_name] = compute_empty_field_confidence()
                continue

        source, corroboration = _count_sources_for_field(profile, field_name)

        if source is None:
            # Field has a value but no provenance — use a default low confidence
            field_confidence[field_name] = 0.5
            logger.debug(
                "Field '%s' has value but no provenance — default confidence 0.5",
                field_name,
            )
        else:
            confidence = compute_field_confidence(source, corroboration)
            field_confidence[field_name] = confidence
            logger.debug(
                "Field '%s': source=%s, corroboration=%d, confidence=%.4f",
                field_name,
                source.value,
                corroboration,
                confidence,
            )

    profile.field_confidence = field_confidence

    # Compute overall confidence as weighted average
    overall = 0.0
    total_weight = 0.0

    for field_name, weight in FIELD_WEIGHTS.items():
        conf = field_confidence.get(field_name, 0.0)
        overall += conf * weight
        total_weight += weight

    # Normalize by total weight (should be 1.0 but guard against rounding)
    if total_weight > 0:
        profile.overall_confidence = round(overall / total_weight, 4)
    else:
        profile.overall_confidence = 0.0

    logger.info(
        "Confidence computed: overall=%.4f, fields=%s",
        profile.overall_confidence,
        {k: round(v, 4) for k, v in field_confidence.items()},
    )

    return profile
