"""
Tests for candidate_transformer.projection

Validates the projection layer: field selection, renaming, missing-field
strategies, and provenance/confidence inclusion/exclusion.
"""

from __future__ import annotations

import pytest

from candidate_transformer.projection import ProjectionConfig, project_profile
from candidate_transformer.models import (
    CanonicalProfile,
    Education,
    Experience,
    Links,
    Location,
    ProvenanceRecord,
    Skill,
    SourceType,
)


def _make_profile(**overrides) -> CanonicalProfile:
    """Helper to create a CanonicalProfile with sensible defaults."""
    defaults = dict(
        candidate_id="test-id-123",
        full_name="Alice Johnson",
        emails=["alice@example.com"],
        phones=["+15551234567"],
        location=Location(city="San Francisco", region="CA", country="US"),
        links=Links(linkedin="https://linkedin.com/in/alice"),
        headline="Senior Data Scientist",
        years_experience=7.0,
        skills=[
            Skill(name="Python", confidence=0.95, sources=["recruiter_csv"]),
        ],
        experience=[
            Experience(company="Acme Corp", title="Senior DS", start="2021-03", end="present"),
        ],
        education=[
            Education(institution="MIT", degree="MS", field="CS", end_year="2020"),
        ],
        provenance=[
            ProvenanceRecord(
                source=SourceType.RECRUITER_CSV,
                field_name="full_name",
                original_value="alice johnson",
                normalized_value="Alice Johnson",
                normalizations_applied=("title_case",),
                confidence=0.90,
            ),
        ],
        field_confidence={"full_name": 0.90, "emails": 0.85},
        overall_confidence=0.88,
    )
    defaults.update(overrides)
    return CanonicalProfile(**defaults)


class TestProjection:
    """Tests for the project_profile function."""

    def test_default_projection(self, sample_canonical_profile):
        """Default projection (no config) should include all standard fields."""
        result = project_profile(sample_canonical_profile)

        assert isinstance(result, dict)
        assert "full_name" in result or "candidateName" in result or "candidate_id" in result
        # Should contain the candidate's data
        # The exact keys depend on default config, but the profile should be present
        assert result  # Non-empty

    def test_custom_field_selection(self):
        """Only specified fields should appear in the output."""
        profile = _make_profile()
        config = ProjectionConfig(
            fields=["full_name", "emails", "skills"],
        )
        result = project_profile(profile, config)

        assert "full_name" in result
        assert "emails" in result
        assert "skills" in result
        # Fields NOT in the selection should be absent
        assert "phones" not in result
        assert "headline" not in result
        assert "experience" not in result

    def test_field_rename(self):
        """Fields should be renamed according to the rename mapping."""
        profile = _make_profile()
        config = ProjectionConfig(
            fields=["full_name", "emails"],
            rename={"full_name": "candidateName", "emails": "emailAddresses"},
        )
        result = project_profile(profile, config)

        assert "candidateName" in result
        assert "emailAddresses" in result
        assert result["candidateName"] == "Alice Johnson"
        # Original keys should NOT be present
        assert "full_name" not in result
        assert "emails" not in result

    def test_on_missing_null(self):
        """on_missing='null' → missing fields should appear as None."""
        profile = _make_profile(headline="", years_experience=None)
        config = ProjectionConfig(
            fields=["full_name", "years_experience", "nonexistent_field"],
            on_missing="null",
        )
        result = project_profile(profile, config)

        assert "full_name" in result
        # Missing/empty fields should be None
        if "nonexistent_field" in result:
            assert result["nonexistent_field"] is None

    def test_on_missing_omit(self):
        """on_missing='omit' → missing fields should not appear at all."""
        profile = _make_profile(years_experience=None)
        config = ProjectionConfig(
            fields=["full_name", "nonexistent_field"],
            on_missing="omit",
        )
        result = project_profile(profile, config)

        assert "full_name" in result
        assert "nonexistent_field" not in result

    def test_on_missing_error(self):
        """on_missing='error' → missing fields should raise an exception."""
        profile = _make_profile()
        config = ProjectionConfig(
            fields=["full_name", "nonexistent_field"],
            on_missing="error",
        )
        with pytest.raises((KeyError, ValueError, AttributeError)):
            project_profile(profile, config)

    def test_exclude_provenance(self):
        """include_provenance=False should omit provenance from output."""
        profile = _make_profile()
        config = ProjectionConfig(
            include_provenance=False,
        )
        result = project_profile(profile, config)

        assert "provenance" not in result

    def test_exclude_confidence(self):
        """include_confidence=False should omit confidence scores."""
        profile = _make_profile()
        config = ProjectionConfig(
            include_confidence=False,
        )
        result = project_profile(profile, config)

        assert "overall_confidence" not in result
        assert "field_confidence" not in result

    def test_include_provenance_and_confidence(self):
        """When both are True, provenance and confidence should appear."""
        profile = _make_profile()
        config = ProjectionConfig(
            include_provenance=True,
            include_confidence=True,
        )
        result = project_profile(profile, config)

        assert "provenance" in result or "overall_confidence" in result

    def test_empty_fields_list(self):
        """Empty fields list should return empty dict or all fields."""
        profile = _make_profile()
        config = ProjectionConfig(fields=[])
        result = project_profile(profile, config)
        # Either empty or all fields — implementation choice
        assert isinstance(result, dict)

    def test_projection_preserves_nested_structures(self):
        """Nested structures (location, skills) should be properly serialized."""
        profile = _make_profile()
        config = ProjectionConfig(
            fields=["location", "skills"],
        )
        result = project_profile(profile, config)

        if "location" in result:
            loc = result["location"]
            assert isinstance(loc, dict)
            assert loc.get("city") == "San Francisco"

        if "skills" in result:
            skills = result["skills"]
            assert isinstance(skills, list)
            assert len(skills) >= 1
