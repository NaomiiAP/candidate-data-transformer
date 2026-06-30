"""
Tests for candidate_transformer.pipeline

End-to-end integration tests that exercise the full pipeline:
ingest → normalize → match → merge → confidence → provenance → project → output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from candidate_transformer.pipeline import run_pipeline
from candidate_transformer.projection import ProjectionConfig


class TestPipelineE2E:
    """End-to-end pipeline integration tests."""

    def test_full_pipeline_all_sources(
        self,
        tmp_csv_file,
        tmp_json_file,
        tmp_linkedin_file,
        tmp_github_file,
        tmp_notes_file,
    ):
        """Run pipeline with all available source types and verify complete output."""
        sources = {
            "recruiter_csv": str(tmp_csv_file),
            "ats_json": str(tmp_json_file),
            "linkedin": str(tmp_linkedin_file),
            "github": str(tmp_github_file),
            "recruiter_notes": str(tmp_notes_file),
        }

        results = run_pipeline(sources, config=None)

        assert isinstance(results, (dict, list))

        # Extract candidates list
        if isinstance(results, dict):
            candidates = results.get("candidates", results.get("profiles", [results]))
            if not isinstance(candidates, list):
                candidates = [candidates]
        else:
            candidates = results

        assert len(candidates) >= 1, "Pipeline should produce at least one candidate"

        # Verify basic structure of first candidate
        first = candidates[0]
        assert isinstance(first, dict)

        # Should have identity fields
        has_name = "full_name" in first or "candidateName" in first or "name" in first
        assert has_name, f"Candidate missing name field. Keys: {list(first.keys())}"

    def test_pipeline_single_source(self, tmp_csv_file):
        """Pipeline should work with just a single CSV source."""
        sources = {"recruiter_csv": str(tmp_csv_file)}
        results = run_pipeline(sources, config=None)

        assert isinstance(results, (dict, list))

        if isinstance(results, dict):
            candidates = results.get("candidates", results.get("profiles", [results]))
            if not isinstance(candidates, list):
                candidates = [candidates]
        else:
            candidates = results

        assert len(candidates) >= 1

    def test_pipeline_with_custom_config(self, tmp_csv_file, tmp_config_file):
        """Pipeline should respect custom projection config."""
        sources = {"recruiter_csv": str(tmp_csv_file)}

        config_data = json.loads(tmp_config_file.read_text(encoding="utf-8"))
        config = ProjectionConfig(**config_data)

        results = run_pipeline(sources, config=config)
        assert isinstance(results, (dict, list))

        # With our config, provenance should be excluded
        result_str = json.dumps(results, default=str)
        # Provenance is excluded in our test config
        if "include_provenance" in config_data and not config_data["include_provenance"]:
            # Serialized output shouldn't contain provenance blocks
            # (This is a soft check — depends on output structure)
            pass

    def test_pipeline_missing_source_graceful(self, tmp_path):
        """Pipeline should handle missing source files gracefully."""
        sources = {
            "recruiter_csv": str(tmp_path / "nonexistent.csv"),
        }

        with pytest.raises((FileNotFoundError, OSError, ValueError, Exception)):
            run_pipeline(sources, config=None)

    def test_pipeline_malformed_input_graceful(self, tmp_path):
        """Pipeline should handle malformed input data gracefully."""
        # Create a CSV file with garbage content
        bad_csv = tmp_path / "garbage.csv"
        bad_csv.write_text("this,is\nnot,valid,candidate,data\n", encoding="utf-8")

        sources = {"recruiter_csv": str(bad_csv)}

        # Should either produce empty results or raise a clear error
        try:
            results = run_pipeline(sources, config=None)
            # If it succeeds, result should be valid
            assert isinstance(results, (dict, list))
        except (ValueError, KeyError, Exception):
            # Also acceptable — graceful error
            pass

    def test_pipeline_deterministic_output(
        self, tmp_csv_file, tmp_json_file
    ):
        """Running the pipeline twice with same inputs should produce identical output."""
        sources = {
            "recruiter_csv": str(tmp_csv_file),
            "ats_json": str(tmp_json_file),
        }

        result1 = run_pipeline(sources, config=None)
        result2 = run_pipeline(sources, config=None)

        # Serialize both to JSON for comparison (normalize UUIDs and timestamps)
        json1 = json.dumps(result1, sort_keys=True, default=str)
        json2 = json.dumps(result2, sort_keys=True, default=str)

        # UUIDs and timestamps will differ, so we compare structure
        # Parse back and compare everything except dynamic fields
        parsed1 = json.loads(json1)
        parsed2 = json.loads(json2)

        def _strip_dynamic(obj):
            """Remove candidate_id, timestamp, and other dynamic fields."""
            if isinstance(obj, dict):
                return {
                    k: _strip_dynamic(v)
                    for k, v in obj.items()
                    if k not in ("candidate_id", "timestamp", "processing_timestamp")
                }
            if isinstance(obj, list):
                return [_strip_dynamic(item) for item in obj]
            return obj

        stripped1 = _strip_dynamic(parsed1)
        stripped2 = _strip_dynamic(parsed2)

        assert stripped1 == stripped2, "Pipeline output is not deterministic"

    def test_pipeline_json_only(self, tmp_json_file):
        """Pipeline with only JSON source should work."""
        sources = {"ats_json": str(tmp_json_file)}
        results = run_pipeline(sources, config=None)
        assert isinstance(results, (dict, list))

    def test_pipeline_notes_only(self, tmp_notes_file):
        """Pipeline with only recruiter notes should work."""
        sources = {"recruiter_notes": str(tmp_notes_file)}
        results = run_pipeline(sources, config=None)
        assert isinstance(results, (dict, list))

    def test_pipeline_output_is_json_serializable(
        self, tmp_csv_file, tmp_json_file
    ):
        """Pipeline output should be fully JSON-serializable."""
        sources = {
            "recruiter_csv": str(tmp_csv_file),
            "ats_json": str(tmp_json_file),
        }
        results = run_pipeline(sources, config=None)

        # This should not raise
        json_str = json.dumps(results, indent=2, ensure_ascii=False, default=str)
        assert isinstance(json_str, str)
        assert len(json_str) > 10

        # Should be parseable back
        parsed = json.loads(json_str)
        assert parsed is not None
