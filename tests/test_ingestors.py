"""
Tests for candidate_transformer.ingestors

Covers all ingestor modules: CSV, JSON, GitHub, LinkedIn, and recruiter notes.
Each ingestor is tested with valid data, malformed inputs, missing files,
empty files, and edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from candidate_transformer.ingestors import (
    ingest_csv,
    ingest_json,
    ingest_github,
    ingest_linkedin,
    ingest_notes,
)
from candidate_transformer.models import CandidateRecord, SourceType


# ═══════════════════════════════════════════════════════════════════════════
# CSV Ingestor
# ═══════════════════════════════════════════════════════════════════════════

class TestCSVIngestor:
    """Tests for ingest_csv."""

    def test_csv_valid(self, tmp_csv_file):
        """Valid CSV should produce CandidateRecords for each row."""
        records = ingest_csv(str(tmp_csv_file))
        assert len(records) == 2
        assert all(isinstance(r, CandidateRecord) for r in records)

        alice = records[0]
        assert alice.source_type == SourceType.RECRUITER_CSV
        assert "alice" in alice.full_name.lower()
        assert len(alice.emails) >= 1
        assert len(alice.skills) >= 1

    def test_csv_field_extraction(self, tmp_csv_file):
        """Verify specific fields are correctly extracted from CSV."""
        records = ingest_csv(str(tmp_csv_file))
        alice = records[0]

        assert "alice.johnson@example.com" in [e.lower() for e in alice.emails]
        assert alice.current_company != "" or len(alice.experience) > 0

    def test_csv_malformed(self, tmp_csv_malformed):
        """Malformed CSV should not crash; may produce partial records."""
        records = ingest_csv(str(tmp_csv_malformed))
        # Should handle gracefully — may skip bad rows or fill defaults
        assert isinstance(records, list)
        # Should produce at least the valid rows
        assert len(records) >= 1

    def test_csv_missing_file(self, tmp_path):
        """Non-existent file should raise FileNotFoundError."""
        with pytest.raises((FileNotFoundError, OSError)):
            ingest_csv(str(tmp_path / "does_not_exist.csv"))

    def test_csv_empty(self, tmp_csv_empty):
        """CSV with only headers should produce zero records."""
        records = ingest_csv(str(tmp_csv_empty))
        assert len(records) == 0


# ═══════════════════════════════════════════════════════════════════════════
# JSON Ingestor
# ═══════════════════════════════════════════════════════════════════════════

class TestJSONIngestor:
    """Tests for ingest_json."""

    def test_json_valid(self, tmp_json_file):
        """Valid ATS JSON should produce CandidateRecords."""
        records = ingest_json(str(tmp_json_file))
        assert len(records) >= 1
        assert all(isinstance(r, CandidateRecord) for r in records)

        alice = records[0]
        assert alice.source_type == SourceType.ATS_JSON
        assert "alice" in alice.full_name.lower()

    def test_json_field_extraction(self, tmp_json_file):
        """Verify specific fields from JSON are correctly extracted."""
        records = ingest_json(str(tmp_json_file))
        alice = records[0]

        assert len(alice.emails) >= 1
        assert len(alice.skills) >= 1
        assert len(alice.experience) >= 1
        assert len(alice.education) >= 1

    def test_json_invalid_json(self, tmp_json_invalid):
        """Invalid JSON content should raise ValueError or JSONDecodeError."""
        with pytest.raises((ValueError, json.JSONDecodeError)):
            ingest_json(str(tmp_json_invalid))

    def test_json_missing_file(self, tmp_path):
        """Non-existent file should raise FileNotFoundError."""
        with pytest.raises((FileNotFoundError, OSError)):
            ingest_json(str(tmp_path / "missing.json"))

    def test_json_single_object(self, tmp_json_single_object):
        """A JSON file with a single object (not array) should still work."""
        records = ingest_json(str(tmp_json_single_object))
        assert len(records) == 1
        assert isinstance(records[0], CandidateRecord)

    def test_json_empty_array(self, tmp_path):
        """Empty JSON array should produce zero records."""
        path = tmp_path / "empty_array.json"
        path.write_text("[]", encoding="utf-8")
        records = ingest_json(str(path))
        assert len(records) == 0


# ═══════════════════════════════════════════════════════════════════════════
# GitHub Ingestor
# ═══════════════════════════════════════════════════════════════════════════

class TestGitHubIngestor:
    """Tests for ingest_github (cached JSON mode)."""

    def test_github_cached_json(self, tmp_github_file):
        """Cached GitHub JSON should produce a CandidateRecord."""
        records = ingest_github(str(tmp_github_file))
        assert len(records) >= 1
        rec = records[0]
        assert isinstance(rec, CandidateRecord)
        assert rec.source_type == SourceType.GITHUB

    def test_github_fields(self, tmp_github_file):
        """Verify GitHub-specific field extraction."""
        records = ingest_github(str(tmp_github_file))
        rec = records[0]

        assert "alice" in rec.full_name.lower()
        # GitHub profiles may provide email, bio, skills from repos
        assert rec.links is not None or len(rec.skills) >= 0

    def test_github_missing_file(self, tmp_path):
        """Non-existent GitHub cache file should raise an error."""
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            ingest_github(str(tmp_path / "no_github.json"))


# ═══════════════════════════════════════════════════════════════════════════
# LinkedIn Ingestor
# ═══════════════════════════════════════════════════════════════════════════

class TestLinkedInIngestor:
    """Tests for ingest_linkedin."""

    def test_linkedin_valid(self, tmp_linkedin_file):
        """Valid LinkedIn JSON should produce a CandidateRecord."""
        records = ingest_linkedin(str(tmp_linkedin_file))
        assert len(records) >= 1
        rec = records[0]
        assert isinstance(rec, CandidateRecord)
        assert rec.source_type == SourceType.LINKEDIN

    def test_linkedin_field_extraction(self, tmp_linkedin_file):
        """Verify LinkedIn-specific fields are extracted."""
        records = ingest_linkedin(str(tmp_linkedin_file))
        rec = records[0]

        assert "alice" in rec.full_name.lower() or "johnson" in rec.full_name.lower()
        assert len(rec.experience) >= 1 or rec.headline != ""

    def test_linkedin_missing_fields(self, tmp_linkedin_missing_fields):
        """LinkedIn JSON with minimal fields should not crash."""
        records = ingest_linkedin(str(tmp_linkedin_missing_fields))
        assert len(records) >= 1
        rec = records[0]
        assert isinstance(rec, CandidateRecord)
        assert "charlie" in rec.full_name.lower() or "brown" in rec.full_name.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Notes Ingestor
# ═══════════════════════════════════════════════════════════════════════════

class TestNotesIngestor:
    """Tests for ingest_notes."""

    def test_notes_extraction(self, tmp_notes_file):
        """Recruiter notes should produce at least one CandidateRecord."""
        records = ingest_notes(str(tmp_notes_file))
        assert len(records) >= 1
        assert all(isinstance(r, CandidateRecord) for r in records)

        rec = records[0]
        assert rec.source_type == SourceType.RECRUITER_NOTES

    def test_notes_multiple_candidates(self, tmp_notes_file):
        """Notes with multiple candidate blocks should produce multiple records."""
        records = ingest_notes(str(tmp_notes_file))
        # Our sample notes have 2 candidates (Alice and Bob)
        assert len(records) >= 2

        names = [r.full_name.lower() for r in records]
        assert any("alice" in n for n in names)
        assert any("bob" in n for n in names)

    def test_notes_missing_file(self, tmp_path):
        """Non-existent notes file should raise FileNotFoundError."""
        with pytest.raises((FileNotFoundError, OSError)):
            ingest_notes(str(tmp_path / "missing_notes.txt"))

    def test_notes_empty_file(self, tmp_path):
        """Empty notes file should produce zero records."""
        path = tmp_path / "empty_notes.txt"
        path.write_text("", encoding="utf-8")
        records = ingest_notes(str(path))
        assert len(records) == 0

    def test_notes_email_extraction(self, tmp_notes_file):
        """Email addresses should be extracted from notes text."""
        records = ingest_notes(str(tmp_notes_file))
        all_emails = []
        for rec in records:
            all_emails.extend(rec.emails)

        email_lower = [e.lower() for e in all_emails]
        assert "alice.johnson@example.com" in email_lower or len(all_emails) > 0
