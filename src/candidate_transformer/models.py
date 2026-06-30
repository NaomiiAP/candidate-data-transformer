"""
Canonical data models for the candidate transformer pipeline.

These models represent the internal canonical representation of candidate data.
They are completely decoupled from the output projection layer.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class SourceType(str, Enum):
    """Enumeration of all supported data source types."""
    RECRUITER_CSV = "recruiter_csv"
    ATS_JSON = "ats_json"
    GITHUB = "github"
    LINKEDIN = "linkedin"
    RESUME_PDF = "resume_pdf"
    RESUME_DOCX = "resume_docx"
    RECRUITER_NOTES = "recruiter_notes"


# Source priority: higher number = higher trust
SOURCE_PRIORITY: dict[SourceType, int] = {
    SourceType.RECRUITER_NOTES: 1,    # Lowest — free text, error-prone
    SourceType.GITHUB: 2,             # Public profile, self-reported
    SourceType.LINKEDIN: 3,           # Semi-structured, self-reported
    SourceType.RESUME_PDF: 4,         # Candidate-authored document
    SourceType.RESUME_DOCX: 4,        # Candidate-authored document
    SourceType.ATS_JSON: 5,           # Semi-structured system export
    SourceType.RECRUITER_CSV: 6,      # Highest — recruiter-verified
}

# Base confidence per source type (0.0 to 1.0)
SOURCE_BASE_CONFIDENCE: dict[SourceType, float] = {
    SourceType.RECRUITER_NOTES: 0.40,
    SourceType.GITHUB: 0.55,
    SourceType.LINKEDIN: 0.65,
    SourceType.RESUME_PDF: 0.70,
    SourceType.RESUME_DOCX: 0.70,
    SourceType.ATS_JSON: 0.80,
    SourceType.RECRUITER_CSV: 0.90,
}


@dataclass(frozen=True)
class ProvenanceRecord:
    """Tracks the origin and transformations applied to a field value.

    Every field in the canonical model carries provenance so that
    downstream consumers can trace exactly where each value came from
    and what normalizations were applied.
    """
    source: SourceType
    field_name: str
    original_value: Any = None
    normalized_value: Any = None
    normalizations_applied: tuple[str, ...] = ()
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON output."""
        return {
            "source": self.source.value,
            "field": self.field_name,
            "original_value": _safe_serialize(self.original_value),
            "normalized_value": _safe_serialize(self.normalized_value),
            "normalizations_applied": list(self.normalizations_applied),
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class Skill:
    """Represents a single skill with confidence and source tracking."""
    name: str
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "confidence": round(self.confidence, 4),
            "sources": self.sources,
        }


@dataclass
class Experience:
    """Represents a single work experience entry."""
    company: str = ""
    title: str = ""
    start: str = ""      # YYYY-MM format
    end: str = ""         # YYYY-MM format or "present"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.company:
            result["company"] = self.company
        if self.title:
            result["title"] = self.title
        if self.start:
            result["start"] = self.start
        if self.end:
            result["end"] = self.end
        if self.summary:
            result["summary"] = self.summary
        return result

    def merge_key(self) -> str:
        """Generate a deduplication key for this experience."""
        company = (self.company or "").lower().strip()
        title = (self.title or "").lower().strip()
        start = self.start or ""
        key = f"{company}|{title}|{start}"
        return hashlib.md5(key.encode()).hexdigest()


@dataclass
class Education:
    """Represents a single education entry."""
    institution: str = ""
    degree: str = ""
    field: str = ""
    end_year: str = ""   # YYYY format

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.institution:
            result["institution"] = self.institution
        if self.degree:
            result["degree"] = self.degree
        if self.field:
            result["field"] = self.field
        if self.end_year:
            result["end_year"] = self.end_year
        return result

    def merge_key(self) -> str:
        """Generate a deduplication key for this education entry."""
        institution = (self.institution or "").lower().strip()
        degree = (self.degree or "").lower().strip()
        end_year = self.end_year or ""
        key = f"{institution}|{degree}|{end_year}"
        return hashlib.md5(key.encode()).hexdigest()


@dataclass
class Location:
    """Represents a geographic location."""
    city: str = ""
    region: str = ""
    country: str = ""     # ISO 3166 Alpha-2

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.city:
            result["city"] = self.city
        if self.region:
            result["region"] = self.region
        if self.country:
            result["country"] = self.country
        return result


@dataclass
class Links:
    """Represents candidate profile links."""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    other: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.linkedin:
            result["linkedin"] = self.linkedin
        if self.github:
            result["github"] = self.github
        if self.portfolio:
            result["portfolio"] = self.portfolio
        if self.other:
            result["other"] = self.other
        return result


@dataclass
class CandidateRecord:
    """Raw candidate data extracted from a single source.

    This represents the output of a single ingestor before merging.
    Each ingestor produces one or more CandidateRecord instances.
    """
    source_type: SourceType
    source_file: str = ""

    # Identity fields
    full_name: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)

    # Profile fields
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: str = ""
    years_experience: Optional[float] = None
    current_company: str = ""

    # Collections
    skills: list[str] = field(default_factory=list)
    experience: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)

    # Raw data for debugging
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalProfile:
    """The merged, canonical representation of a candidate.

    This is the internal model produced by the merge engine.
    It is completely separate from the projected output.
    """
    candidate_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Identity
    full_name: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)

    # Profile
    location: Optional[Location] = None
    links: Optional[Links] = None
    headline: str = ""
    years_experience: Optional[float] = None

    # Collections
    skills: list[Skill] = field(default_factory=list)
    experience: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)

    # Provenance and confidence
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)
    overall_confidence: float = 0.0

    # Source records that were merged
    source_records: list[CandidateRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the canonical profile to a dictionary."""
        return {
            "candidate_id": self.candidate_id,
            "full_name": self.full_name,
            "emails": sorted(set(self.emails)),
            "phones": sorted(set(self.phones)),
            "location": self.location.to_dict() if self.location else None,
            "links": self.links.to_dict() if self.links else None,
            "headline": self.headline,
            "years_experience": self.years_experience,
            "skills": [s.to_dict() for s in self.skills],
            "experience": [e.to_dict() for e in self.experience],
            "education": [e.to_dict() for e in self.education],
            "provenance": [p.to_dict() for p in self.provenance],
            "overall_confidence": round(self.overall_confidence, 4),
        }


def _safe_serialize(value: Any) -> Any:
    """Safely serialize a value for JSON output."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _safe_serialize(v) for k, v in value.items()}
    return str(value)
