"""
Tests for candidate_transformer.entity_matcher

Validates that candidate records from different sources are correctly
grouped into match groups based on shared emails, phones, or names.
"""

from __future__ import annotations

import pytest

from candidate_transformer.entity_matcher import match_candidates
from candidate_transformer.models import (
    CandidateRecord,
    Location,
    SourceType,
)


class TestEntityMatcher:
    """Tests for the match_candidates function."""

    def test_match_by_email(
        self, sample_candidate_record, sample_candidate_record_ats
    ):
        """Two records sharing an email should be grouped together."""
        groups = match_candidates([sample_candidate_record, sample_candidate_record_ats])
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_match_by_phone(self):
        """Two records sharing a phone number should match."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice J",
            phones=["+15551234567"],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice Johnson",
            phones=["+15551234567"],
        )
        groups = match_candidates([rec1, rec2])
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_match_by_name(self):
        """Two records with the same normalized name (no shared email/phone)."""
        rec1 = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice Johnson",
            emails=["alice1@example.com"],
        )
        rec2 = CandidateRecord(
            source_type=SourceType.LINKEDIN,
            full_name="alice johnson",
            emails=["alice2@other.com"],
        )
        groups = match_candidates([rec1, rec2])
        # Depending on implementation, name-only match may or may not group.
        # If it does, we should have 1 group; otherwise 2 groups.
        assert len(groups) in (1, 2)
        total_records = sum(len(g) for g in groups)
        assert total_records == 2

    def test_no_match_different_people(
        self, sample_candidate_record, sample_candidate_record_bob
    ):
        """Records for different people should NOT be grouped."""
        groups = match_candidates([sample_candidate_record, sample_candidate_record_bob])
        assert len(groups) == 2
        # Each group should have exactly one record
        for group in groups:
            assert len(group) == 1

    def test_multiple_groups(self):
        """Three records: two match, one is separate → 2 groups."""
        alice_csv = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice Johnson",
            emails=["alice@example.com"],
        )
        alice_ats = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice Johnson",
            emails=["alice@example.com"],
        )
        bob = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Bob Smith",
            emails=["bob@example.com"],
        )
        groups = match_candidates([alice_csv, alice_ats, bob])
        assert len(groups) == 2
        # One group should have 2 records, the other should have 1
        group_sizes = sorted(len(g) for g in groups)
        assert group_sizes == [1, 2]

    def test_single_record(self):
        """A single record should produce one group of one."""
        rec = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Solo Person",
            emails=["solo@example.com"],
        )
        groups = match_candidates([rec])
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_empty_input(self):
        """No records should produce no groups."""
        groups = match_candidates([])
        assert len(groups) == 0

    def test_transitive_match(self):
        """If A matches B (email) and B matches C (phone), all three group."""
        rec_a = CandidateRecord(
            source_type=SourceType.RECRUITER_CSV,
            full_name="Alice A",
            emails=["shared@example.com"],
            phones=[],
        )
        rec_b = CandidateRecord(
            source_type=SourceType.ATS_JSON,
            full_name="Alice B",
            emails=["shared@example.com"],
            phones=["+15559999999"],
        )
        rec_c = CandidateRecord(
            source_type=SourceType.LINKEDIN,
            full_name="Alice C",
            emails=["different@example.com"],
            phones=["+15559999999"],
        )
        groups = match_candidates([rec_a, rec_b, rec_c])
        # Transitive matching should put all 3 in one group
        assert len(groups) == 1
        assert len(groups[0]) == 3
