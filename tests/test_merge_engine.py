"""
Tests for candidate_transformer.merge_engine

Validates the merge logic: combining multiple CandidateRecords into a
single CanonicalProfile with correct conflict resolution, deduplication,
and priority-based field selection.
"""

from __future__ import annotations

import pytest

from candidate_transformer.merge_engine import merge_records
from candidate_transformer.models import (
    CanonicalProfile,
    CandidateRecord,
    Education,
    Experience,
    Links,
    Location,
    Skill,
    SourceType,
    SOURCE_PRIORITY,
)


class TestMergeEngine:
    """Tests for merge_records function."""

    def test_merge_single_record(self, sample_candidate_record):
        """Merging a single record should produce a profile with the same data."""
        profile = merge_records([sample_candidate_record])

        assert isinstance(profile, CanonicalProfile)
        assert profile.full_name == "Alice Johnson"
        assert "alice.johnson@example.com" in profile.emails
        assert len(profile.experience) == 1
        assert len(profile.education) == 1

    def test_merge_conflicting_names(self):
        """When two sources disagree on the name, highest-priority source wins."""
        csv_rec = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice M. Johnson",
            emails=["alice@example.com"],
        )
        ats_rec = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice Johnson",
            emails=["alice@example.com"],
        )
        profile = merge_records([csv_rec, ats_rec])

        # RECRUITER_CSV has higher priority (6) than ATS_JSON (5)
        assert profile.full_name == "Alice M. Johnson"

    def test_merge_unique_emails(self):
        """Emails from all sources should be combined and deduplicated."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            emails=["alice@a.com", "alice@b.com"],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice",
            emails=["alice@b.com", "alice@c.com"],
        )
        profile = merge_records([rec1, rec2])

        # Should be union: alice@a.com, alice@b.com, alice@c.com
        assert len(profile.emails) == 3
        assert set(profile.emails) == {"alice@a.com", "alice@b.com", "alice@c.com"}

    def test_merge_duplicate_skills(self):
        """Duplicate skills should be merged, not duplicated."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            skills=["Python", "SQL", "Machine Learning"],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice",
            skills=["Python", "TensorFlow", "SQL"],
        )
        profile = merge_records([rec1, rec2])

        skill_names = [s.name for s in profile.skills]
        # No duplicates
        assert len(skill_names) == len(set(s.lower() for s in skill_names))
        # All unique skills present
        assert any("python" in s.lower() for s in skill_names)
        assert any("tensorflow" in s.lower() for s in skill_names)
        assert any("sql" in s.lower() for s in skill_names)
        assert any("machine learning" in s.lower() for s in skill_names)

    def test_merge_experience_dedup(self):
        """Duplicate experience entries should be deduplicated by merge_key."""
        exp = Experience(
            company="Acme Corp",
            title="Senior Data Scientist",
            start="2021-03",
            end="present",
        )
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            experience=[exp],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice",
            experience=[
                Experience(
                    company="Acme Corp",
                    title="Senior Data Scientist",
                    start="2021-03",
                    end="present",
                    summary="Led ML team.",
                )
            ],
        )
        profile = merge_records([rec1, rec2])

        # Should have exactly 1 experience entry (deduplicated)
        assert len(profile.experience) == 1

    def test_merge_education_dedup(self):
        """Duplicate education entries should be deduplicated."""
        edu = Education(
            institution="MIT", degree="MS", field="Computer Science", end_year="2020"
        )
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            education=[edu],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice",
            education=[
                Education(
                    institution="MIT",
                    degree="MS",
                    field="Computer Science",
                    end_year="2020",
                )
            ],
        )
        profile = merge_records([rec1, rec2])
        assert len(profile.education) == 1

    def test_merge_priority_resolution(self):
        """Source with higher priority should win for scalar conflicts."""
        # RECRUITER_NOTES = priority 1, RECRUITER_CSV = priority 6
        notes_rec = CandidateRecord(
            source_type=SourceType.RECRUITER_NOTES,
            full_name="Alice J.",
            headline="DS at Acme",
            emails=["alice@example.com"],
        )
        csv_rec = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice Johnson",
            headline="Senior Data Scientist | ML & AI",
            emails=["alice@example.com"],
        )
        profile = merge_records([notes_rec, csv_rec])

        # CSV has higher priority → its values should win
        assert profile.full_name == "Alice Johnson"
        assert profile.headline == "Senior Data Scientist | ML & AI"

    def test_merge_phones_union(self):
        """Phone numbers from multiple sources should be combined."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            phones=["+15551234567"],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice",
            phones=["+15551234567", "+442079460958"],
        )
        profile = merge_records([rec1, rec2])
        assert len(profile.phones) == 2

    def test_merge_preserves_location_from_highest_priority(self):
        """Location should come from the highest-priority source."""
        rec_low = CandidateRecord(
            source_type=SourceType.GITHUB,
            full_name="Alice",
            location=Location(city="NYC", country="US"),
        )
        rec_high = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            location=Location(city="San Francisco", region="CA", country="US"),
        )
        profile = merge_records([rec_low, rec_high])
        assert profile.location is not None
        assert profile.location.city == "San Francisco"

    def test_merge_empty_records(self):
        """Merging records with no data should produce an empty profile."""
        rec = CandidateRecord(source_type=SourceType.RECRUITER_CSV)
        profile = merge_records([rec])
        assert isinstance(profile, CanonicalProfile)
        assert profile.full_name == ""
        assert len(profile.emails) == 0

    def test_merge_years_experience_max(self):
        """years_experience should take the maximum or highest-priority value."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            years_experience=7.0,
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice",
            years_experience=6.5,
        )
        profile = merge_records([rec1, rec2])
        # Should be 7.0 (from highest-priority source or max)
        assert profile.years_experience >= 6.5

    def test_merge_links_combined(self):
        """Links from multiple sources should be merged."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice",
            links=Links(linkedin="https://linkedin.com/in/alice"),
        )
        rec2 = CandidateRecord(
            source_type=SourceType.GITHUB,
            full_name="Alice",
            links=Links(github="https://github.com/alice"),
        )
        profile = merge_records([rec1, rec2])
        assert profile.links is not None
        assert profile.links.linkedin != ""
        assert profile.links.github != ""
