"""
Configurable projection layer for CanonicalProfile output.

Transforms a CanonicalProfile into a JSON-serializable dictionary
according to a runtime ProjectionConfig. Supports field selection,
path resolution, normalization, and configurable missing-value handling.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from candidate_transformer.models import CanonicalProfile
from candidate_transformer.normalizers import (
    normalize_email,
    normalize_phone,
    normalize_skill,
    normalize_url,
)

logger = logging.getLogger(__name__)


class FieldProjection(BaseModel):
    """Configuration for a single projected output field.

    Attributes:
        path: Output field name in the projected result.
        from_: Canonical path to the source field in the profile.
            Examples: 'emails[0]', 'skills[].name', 'phones[0]'.
        type: Expected output type ('string', 'list', 'number', 'object').
        required: Whether this field is required in the output.
        normalize: Optional normalization to apply ('E164', 'canonical').
    """

    path: str
    from_: str = Field(default="", alias="from")
    type: str = "string"
    required: bool = False
    normalize: str = ""

    model_config = {"populate_by_name": True}


class ProjectionConfig(BaseModel):
    """Runtime configuration for the projection layer.

    Attributes:
        fields: List of field projections to apply. If empty, outputs
            the full default schema.
        rename: Optional mapping to rename projected fields.
        include_confidence: Whether to include confidence scores.
        include_provenance: Whether to include provenance records.
        on_missing: Strategy for missing values:
            'null' — include field with None value.
            'omit' — exclude the field entirely.
            'error' — raise ValueError for missing required fields.
    """

    fields: list[str | FieldProjection] = Field(default_factory=list)
    rename: dict[str, str] = Field(default_factory=dict)
    include_confidence: bool = True
    include_provenance: bool = True
    on_missing: str = "null"


def _resolve_path(profile: CanonicalProfile, path: str) -> Any:
    """Resolve a canonical path against a CanonicalProfile.

    Supported path formats:
      - 'field_name' — direct attribute access
      - 'field[N]' — indexed access into a list attribute
      - 'field[].subfield' — map over list, extracting subfield
      - 'field.subfield' — nested attribute access

    Args:
        profile: The canonical profile to extract data from.
        path: The canonical path string.

    Returns:
        The resolved value, or None if the path cannot be resolved.
    """
    if not path:
        return None

    # Handle indexed access: 'field[N]'
    indexed_match = re.match(r"^(\w+)\[(\d+)\]$", path)
    if indexed_match:
        field_name = indexed_match.group(1)
        index = int(indexed_match.group(2))
        return _get_indexed(profile, field_name, index)

    # Handle list-map access: 'field[].subfield'
    list_map_match = re.match(r"^(\w+)\[\]\.(\w+)$", path)
    if list_map_match:
        field_name = list_map_match.group(1)
        sub_field = list_map_match.group(2)
        return _get_list_map(profile, field_name, sub_field)

    # Handle nested access: 'field.subfield'
    dot_match = re.match(r"^(\w+)\.(\w+)$", path)
    if dot_match:
        field_name = dot_match.group(1)
        sub_field = dot_match.group(2)
        return _get_nested(profile, field_name, sub_field)

    # Direct attribute access
    return _get_direct(profile, path)


def _get_direct(profile: CanonicalProfile, field_name: str) -> Any:
    """Get a direct attribute from the profile."""
    if not hasattr(profile, field_name):
        return None

    value = getattr(profile, field_name)

    # Serialize dataclass objects
    if hasattr(value, "to_dict"):
        return value.to_dict()

    # Serialize lists of dataclass objects
    if isinstance(value, list) and value and hasattr(value[0], "to_dict"):
        return [item.to_dict() for item in value]

    return value


def _get_indexed(
    profile: CanonicalProfile, field_name: str, index: int
) -> Any:
    """Get an indexed element from a list attribute."""
    value = _get_direct(profile, field_name)

    if not isinstance(value, list):
        return None

    if index < 0 or index >= len(value):
        return None

    item = value[index]

    # Serialize if it's a dataclass with to_dict
    if hasattr(item, "to_dict"):
        return item.to_dict()

    return item


def _get_list_map(
    profile: CanonicalProfile, field_name: str, sub_field: str
) -> list[Any]:
    """Map over a list attribute and extract a subfield from each element."""
    if not hasattr(profile, field_name):
        return []

    value = getattr(profile, field_name)

    if not isinstance(value, list):
        return []

    result: list[Any] = []
    for item in value:
        if hasattr(item, sub_field):
            result.append(getattr(item, sub_field))
        elif isinstance(item, dict) and sub_field in item:
            result.append(item[sub_field])

    return result


def _get_nested(
    profile: CanonicalProfile, field_name: str, sub_field: str
) -> Any:
    """Get a nested attribute (e.g., location.city)."""
    if not hasattr(profile, field_name):
        return None

    parent = getattr(profile, field_name)
    if parent is None:
        return None

    if hasattr(parent, sub_field):
        return getattr(parent, sub_field)

    if isinstance(parent, dict):
        return parent.get(sub_field)

    return None


def _apply_normalization(value: Any, normalize: str) -> Any:
    """Apply a named normalization to a value.

    Args:
        value: The value to normalize.
        normalize: Normalization name ('E164', 'canonical', 'url',
            'email', 'lowercase', 'uppercase').

    Returns:
        The normalized value.
    """
    if not normalize or value is None:
        return value

    norm_lower = normalize.lower()

    if isinstance(value, list):
        return [_apply_normalization(v, normalize) for v in value]

    if not isinstance(value, str):
        return value

    if norm_lower == "e164":
        return normalize_phone(value) or value
    elif norm_lower == "canonical":
        return normalize_skill(value) or value
    elif norm_lower == "url":
        return normalize_url(value) or value
    elif norm_lower == "email":
        return normalize_email(value) or value
    elif norm_lower == "lowercase":
        return value.lower()
    elif norm_lower == "uppercase":
        return value.upper()
    else:
        logger.warning("Unknown normalization: %s", normalize)
        return value


def _build_default_output(
    profile: CanonicalProfile,
    include_confidence: bool,
    include_provenance: bool,
) -> dict[str, Any]:
    """Build the full default schema output from a CanonicalProfile.

    Matches the canonical output format:
    {
        "candidate_id", "full_name", "emails", "phones",
        "location", "links", "headline", "years_experience",
        "skills", "experience", "education",
        "provenance" (optional), "overall_confidence" (optional)
    }

    Args:
        profile: The canonical profile to serialize.
        include_confidence: Whether to include confidence scores.
        include_provenance: Whether to include provenance records.

    Returns:
        JSON-serializable dictionary.
    """
    location_dict: dict[str, str] = {"city": "", "region": "", "country": ""}
    if profile.location:
        location_dict = {
            "city": profile.location.city or "",
            "region": profile.location.region or "",
            "country": profile.location.country or "",
        }

    links_dict: dict[str, Any] = {
        "linkedin": "",
        "github": "",
        "portfolio": "",
        "other": [],
    }
    if profile.links:
        links_dict = {
            "linkedin": profile.links.linkedin or "",
            "github": profile.links.github or "",
            "portfolio": profile.links.portfolio or "",
            "other": profile.links.other if profile.links.other else [],
        }

    skills_list: list[dict[str, Any]] = []
    for skill in profile.skills:
        skills_list.append({
            "name": skill.name,
            "confidence": round(skill.confidence, 4),
            "sources": skill.sources,
        })

    experience_list: list[dict[str, Any]] = []
    for exp in profile.experience:
        experience_list.append({
            "company": exp.company or "",
            "title": exp.title or "",
            "start": exp.start or "",
            "end": exp.end or "",
            "summary": exp.summary or "",
        })

    education_list: list[dict[str, Any]] = []
    for edu in profile.education:
        education_list.append({
            "institution": edu.institution or "",
            "degree": edu.degree or "",
            "field": edu.field or "",
            "end_year": edu.end_year or "",
        })

    result: dict[str, Any] = {
        "candidate_id": profile.candidate_id,
        "full_name": profile.full_name,
        "emails": sorted(set(profile.emails)),
        "phones": sorted(set(profile.phones)),
        "location": location_dict,
        "links": links_dict,
        "headline": profile.headline,
        "years_experience": profile.years_experience,
        "skills": skills_list,
        "experience": experience_list,
        "education": education_list,
    }

    if include_provenance:
        result["provenance"] = [
            {
                "field": p.field_name,
                "source": p.source.value,
                "method": ", ".join(p.normalizations_applied)
                if p.normalizations_applied
                else "direct",
                "original_value": str(p.original_value)
                if p.original_value is not None
                else None,
                "normalized_value": str(p.normalized_value)
                if p.normalized_value is not None
                else None,
            }
            for p in profile.provenance
        ]

    if include_confidence:
        result["overall_confidence"] = round(profile.overall_confidence, 4)
        result["field_confidence"] = {
            k: round(v, 4) for k, v in profile.field_confidence.items()
        }

    return result


def _is_missing(value: Any) -> bool:
    """Check if a value should be considered 'missing'.

    Args:
        value: The value to check.

    Returns:
        True if the value is None, empty string, or empty list.
    """
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def project(
    profile: CanonicalProfile,
    config: Optional[ProjectionConfig] = None,
) -> dict[str, Any]:
    """Project a CanonicalProfile into a JSON-serializable output dict.

    If no config is provided (or config has no fields), produces the
    full default schema. Otherwise, selects and transforms only the
    fields specified in the config.

    Args:
        profile: The canonical profile to project.
        config: Optional projection configuration.

    Returns:
        JSON-serializable dictionary matching the projection spec.

    Raises:
        ValueError: If on_missing='error' and a required field is missing.
    """
    if config is None:
        config = ProjectionConfig()

    # If no field projections specified, output the full default schema
    if not config.fields:
        logger.info("No field projections specified — using default schema.")
        res = _build_default_output(
            profile,
            include_confidence=config.include_confidence,
            include_provenance=config.include_provenance,
        )
        if config.rename:
            for k, new_k in config.rename.items():
                if k in res:
                    res[new_k] = res.pop(k)
        return res

    logger.info(
        "Projecting %d fields from profile %s.",
        len(config.fields),
        profile.candidate_id,
    )

    result: dict[str, Any] = {}

    for f in config.fields:
        if isinstance(f, str):
            field_proj = FieldProjection(path=f, from_=f)
        else:
            field_proj = f

        # Determine the source path
        source_path = field_proj.from_ if field_proj.from_ else field_proj.path

        # Resolve the value from the profile
        value = _resolve_path(profile, source_path)

        # Apply normalization if specified
        if field_proj.normalize:
            value = _apply_normalization(value, field_proj.normalize)

        # Handle missing values
        if _is_missing(value):
            if config.on_missing == "error":
                raise ValueError(
                    f"Field '{field_proj.path}' (from '{source_path}') "
                    f"is missing in profile {profile.candidate_id}."
                )
            elif config.on_missing == "omit":
                logger.debug(
                    "Omitting missing field: %s",
                    field_proj.path,
                )
                continue
            else:
                # 'null' strategy — include as None
                value = None

        output_key = field_proj.path
        if config.rename and output_key in config.rename:
            output_key = config.rename[output_key]

        result[output_key] = value

    # Include confidence and provenance based on config
    if config.include_confidence:
        result["overall_confidence"] = round(profile.overall_confidence, 4)

    if config.include_provenance:
        result["provenance"] = [
            {
                "field": p.field_name,
                "source": p.source.value,
                "method": ", ".join(p.normalizations_applied)
                if p.normalizations_applied
                else "direct",
            }
            for p in profile.provenance
        ]

    return result


project_profile = project
