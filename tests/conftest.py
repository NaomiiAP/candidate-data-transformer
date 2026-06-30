"""
Shared pytest fixtures for the candidate_transformer test suite.

Provides temporary files (CSV, JSON, LinkedIn, GitHub, Notes) and
pre-built model instances (CandidateRecord, CanonicalProfile) that
are shared across all test modules.
"""

from __future__ import annotations

import csv
import json
import textwrap
from pathlib import Path

import pytest

from candidate_transformer.models import (
    CandidateRecord,
    CanonicalProfile,
    Education,
    Experience,
    Links,
    Location,
    ProvenanceRecord,
    Skill,
    SourceType,
)


# ---------------------------------------------------------------------------
# CSV fixtures
# ---------------------------------------------------------------------------

SAMPLE_CSV_ROWS = [
    {
        "name": "Alice Johnson",
        "email": "alice.johnson@example.com",
        "phone": "+1 (555) 123-4567",
        "skills": "Python;Machine Learning;SQL",
        "company": "Acme Corp",
        "title": "Senior Data Scientist",
        "start_date": "2021-03",
        "end_date": "present",
        "education": "MIT|MS|Computer Science|2020",
        "city": "San Francisco",
        "state": "CA",
        "country": "US",
        "linkedin": "https://linkedin.com/in/alicejohnson",
        "github": "alicejohnson",
        "years_experience": "7",
    },
    {
        "name": "Bob Smith",
        "email": "bob.smith@company.org",
        "phone": "44 20 7946 0958",
        "skills": "Java;Spring Boot;Kubernetes",
        "company": "BigTech Ltd",
        "title": "Staff Engineer",
        "start_date": "2019-06",
        "end_date": "2023-12",
        "education": "Stanford|BS|Electrical Engineering|2018",
        "city": "London",
        "state": "",
        "country": "United Kingdom",
        "linkedin": "linkedin.com/in/bobsmith",
        "github": "",
        "years_experience": "9",
    },
]


@pytest.fixture
def tmp_csv_file(tmp_path: Path) -> Path:
    """Create a temporary recruiter CSV file with two candidates."""
    csv_path = tmp_path / "recruiter.csv"
    fieldnames = list(SAMPLE_CSV_ROWS[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in SAMPLE_CSV_ROWS:
            writer.writerow(row)
    return csv_path


@pytest.fixture
def tmp_csv_empty(tmp_path: Path) -> Path:
    """Create a CSV file with only headers and no data rows."""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("name,email,phone,skills\n", encoding="utf-8")
    return csv_path


@pytest.fixture
def tmp_csv_malformed(tmp_path: Path) -> Path:
    """Create a CSV file with inconsistent column counts."""
    csv_path = tmp_path / "malformed.csv"
    csv_path.write_text(
        "name,email,phone\n"
        'Alice,alice@example.com,"+1 555-1234"\n'
        "Bob,bob@company.org\n"                        # Missing phone column
        'Charlie,"charlie@co.com","+44 7911 123456","extra"\n',  # Extra column
        encoding="utf-8",
    )
    return csv_path


# ---------------------------------------------------------------------------
# ATS JSON fixtures
# ---------------------------------------------------------------------------

SAMPLE_ATS_JSON = [
    {
        "candidate_name": "Alice Johnson",
        "email_addresses": ["alice.johnson@example.com", "alice.j@gmail.com"],
        "phone_numbers": ["+15551234567"],
        "skills": ["Python", "Machine Learning", "TensorFlow", "SQL"],
        "work_history": [
            {
                "employer": "Acme Corp",
                "job_title": "Senior Data Scientist",
                "start_date": "March 2021",
                "end_date": "Present",
                "description": "Led ML team building recommendation engines.",
            }
        ],
        "education": [
            {
                "school": "MIT",
                "degree": "MS",
                "major": "Computer Science",
                "graduation_year": "2020",
            }
        ],
        "location": {"city": "San Francisco", "state": "CA", "country": "USA"},
        "linkedin_url": "https://www.linkedin.com/in/alicejohnson",
        "headline": "Senior Data Scientist | ML & AI",
        "years_of_experience": 7.0,
    }
]


@pytest.fixture
def tmp_json_file(tmp_path: Path) -> Path:
    """Create a temporary ATS JSON file."""
    json_path = tmp_path / "ats.json"
    json_path.write_text(json.dumps(SAMPLE_ATS_JSON, indent=2), encoding="utf-8")
    return json_path


@pytest.fixture
def tmp_json_single_object(tmp_path: Path) -> Path:
    """Create a JSON file containing a single object (not an array)."""
    json_path = tmp_path / "single.json"
    json_path.write_text(json.dumps(SAMPLE_ATS_JSON[0], indent=2), encoding="utf-8")
    return json_path


@pytest.fixture
def tmp_json_invalid(tmp_path: Path) -> Path:
    """Create a file containing invalid JSON."""
    json_path = tmp_path / "invalid.json"
    json_path.write_text("{not valid json: [}", encoding="utf-8")
    return json_path


# ---------------------------------------------------------------------------
# LinkedIn JSON fixture
# ---------------------------------------------------------------------------

SAMPLE_LINKEDIN_JSON = {
    "firstName": "Alice",
    "lastName": "Johnson",
    "headline": "Senior Data Scientist | ML & AI",
    "emailAddress": "alice.johnson@example.com",
    "location": {"name": "San Francisco, California", "country": {"code": "us"}},
    "positions": {
        "values": [
            {
                "company": {"name": "Acme Corp"},
                "title": "Senior Data Scientist",
                "startDate": {"month": 3, "year": 2021},
                "isCurrent": True,
                "summary": "Building ML models at scale.",
            }
        ]
    },
    "educations": {
        "values": [
            {
                "schoolName": "MIT",
                "degree": "MS",
                "fieldOfStudy": "Computer Science",
                "endDate": {"year": 2020},
            }
        ]
    },
    "skills": {"values": [{"skill": {"name": "Python"}}, {"skill": {"name": "Machine Learning"}}]},
    "publicProfileUrl": "https://www.linkedin.com/in/alicejohnson",
}


@pytest.fixture
def tmp_linkedin_file(tmp_path: Path) -> Path:
    """Create a temporary LinkedIn profile JSON file."""
    linkedin_path = tmp_path / "linkedin.json"
    linkedin_path.write_text(json.dumps(SAMPLE_LINKEDIN_JSON, indent=2), encoding="utf-8")
    return linkedin_path


@pytest.fixture
def tmp_linkedin_missing_fields(tmp_path: Path) -> Path:
    """Create a LinkedIn JSON with minimal fields."""
    data = {"firstName": "Charlie", "lastName": "Brown"}
    path = tmp_path / "linkedin_minimal.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# GitHub cached JSON fixture
# ---------------------------------------------------------------------------

SAMPLE_GITHUB_JSON = {
    "login": "alicejohnson",
    "name": "Alice Johnson",
    "email": "alice.j@gmail.com",
    "bio": "Data scientist, ML enthusiast, open-source contributor",
    "blog": "https://alicejohnson.dev",
    "html_url": "https://github.com/alicejohnson",
    "location": "San Francisco, CA",
    "public_repos": 42,
    "repos": [
        {"name": "ml-pipeline", "language": "Python", "stargazers_count": 128},
        {"name": "data-viz", "language": "Python", "stargazers_count": 45},
        {"name": "k8s-config", "language": "YAML", "stargazers_count": 12},
    ],
}


@pytest.fixture
def tmp_github_file(tmp_path: Path) -> Path:
    """Create a temporary cached GitHub profile JSON file."""
    gh_path = tmp_path / "github_cache.json"
    gh_path.write_text(json.dumps(SAMPLE_GITHUB_JSON, indent=2), encoding="utf-8")
    return gh_path


# ---------------------------------------------------------------------------
# Recruiter notes fixture
# ---------------------------------------------------------------------------

SAMPLE_NOTES = textwrap.dedent("""\
    Candidate: Alice Johnson
    Email: alice.johnson@example.com
    Phone: (555) 123-4567

    Strong candidate for senior DS role. 7+ years of experience.
    Currently at Acme Corp. Proficient in Python, ML, and SQL.
    MIT grad. Looking for remote opportunities.
    Salary expectation: $180k-$210k.

    ---
    Candidate: Bob Smith
    Email: bob.smith@company.org

    Experienced backend engineer. Strong Java and Kubernetes skills.
    Based in London.
""")


@pytest.fixture
def tmp_notes_file(tmp_path: Path) -> Path:
    """Create a temporary recruiter notes TXT file."""
    notes_path = tmp_path / "notes.txt"
    notes_path.write_text(SAMPLE_NOTES, encoding="utf-8")
    return notes_path


# ---------------------------------------------------------------------------
# Projection config fixture
# ---------------------------------------------------------------------------

SAMPLE_PROJECTION_CONFIG = {
    "fields": [
        "full_name",
        "emails",
        "phones",
        "skills",
        "experience",
        "location",
    ],
    "rename": {"full_name": "candidateName", "emails": "emailAddresses"},
    "on_missing": "null",
    "include_provenance": False,
    "include_confidence": False,
}


@pytest.fixture
def tmp_config_file(tmp_path: Path) -> Path:
    """Create a temporary projection config JSON file."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(SAMPLE_PROJECTION_CONFIG, indent=2), encoding="utf-8")
    return cfg_path


# ---------------------------------------------------------------------------
# Model instance fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_candidate_record() -> CandidateRecord:
    """Create a fully-populated CandidateRecord for testing."""
    return CandidateRecord(
        source_type=SourceType.RECRUITER_CSV,
        source_file="recruiter.csv",
        full_name="Alice Johnson",
        emails=["alice.johnson@example.com"],
        phones=["+15551234567"],
        location=Location(city="San Francisco", region="CA", country="US"),
        links=Links(
            linkedin="https://linkedin.com/in/alicejohnson",
            github="https://github.com/alicejohnson",
        ),
        headline="Senior Data Scientist | ML & AI",
        years_experience=7.0,
        current_company="Acme Corp",
        skills=["Python", "Machine Learning", "SQL"],
        experience=[
            Experience(
                company="Acme Corp",
                title="Senior Data Scientist",
                start="2021-03",
                end="present",
                summary="Led ML team building recommendation engines.",
            ),
        ],
        education=[
            Education(
                institution="MIT",
                degree="MS",
                field="Computer Science",
                end_year="2020",
            ),
        ],
    )


@pytest.fixture
def sample_candidate_record_ats() -> CandidateRecord:
    """Create a CandidateRecord from ATS source with overlapping data."""
    return CandidateRecord(
        source_type=SourceType.ATS_JSON,
        source_file="ats.json",
        full_name="Alice Johnson",
        emails=["alice.johnson@example.com", "alice.j@gmail.com"],
        phones=["+15551234567"],
        location=Location(city="San Francisco", region="CA", country="US"),
        links=Links(linkedin="https://www.linkedin.com/in/alicejohnson"),
        headline="Senior Data Scientist | ML & AI",
        years_experience=7.0,
        current_company="Acme Corp",
        skills=["Python", "Machine Learning", "TensorFlow", "SQL"],
        experience=[
            Experience(
                company="Acme Corp",
                title="Senior Data Scientist",
                start="2021-03",
                end="present",
                summary="Led ML team building recommendation engines.",
            ),
        ],
        education=[
            Education(
                institution="MIT",
                degree="MS",
                field="Computer Science",
                end_year="2020",
            ),
        ],
    )


@pytest.fixture
def sample_candidate_record_bob() -> CandidateRecord:
    """Create a CandidateRecord for a different person (Bob Smith)."""
    return CandidateRecord(
        source_type=SourceType.RECRUITER_CSV,
        source_file="recruiter.csv",
        full_name="Bob Smith",
        emails=["bob.smith@company.org"],
        phones=["+442079460958"],
        location=Location(city="London", country="GB"),
        skills=["Java", "Spring Boot", "Kubernetes"],
        experience=[
            Experience(
                company="BigTech Ltd",
                title="Staff Engineer",
                start="2019-06",
                end="2023-12",
            ),
        ],
        education=[
            Education(
                institution="Stanford",
                degree="BS",
                field="Electrical Engineering",
                end_year="2018",
            ),
        ],
    )


@pytest.fixture
def sample_canonical_profile() -> CanonicalProfile:
    """Create a fully-populated CanonicalProfile for testing."""
    return CanonicalProfile(
        candidate_id="test-uuid-001",
        full_name="Alice Johnson",
        emails=["alice.johnson@example.com", "alice.j@gmail.com"],
        phones=["+15551234567"],
        location=Location(city="San Francisco", region="CA", country="US"),
        links=Links(
            linkedin="https://linkedin.com/in/alicejohnson",
            github="https://github.com/alicejohnson",
        ),
        headline="Senior Data Scientist | ML & AI",
        years_experience=7.0,
        skills=[
            Skill(name="Python", confidence=0.95, sources=["recruiter_csv", "ats_json"]),
            Skill(name="Machine Learning", confidence=0.90, sources=["recruiter_csv", "ats_json"]),
            Skill(name="SQL", confidence=0.85, sources=["recruiter_csv", "ats_json"]),
            Skill(name="TensorFlow", confidence=0.80, sources=["ats_json"]),
        ],
        experience=[
            Experience(
                company="Acme Corp",
                title="Senior Data Scientist",
                start="2021-03",
                end="present",
                summary="Led ML team building recommendation engines.",
            ),
        ],
        education=[
            Education(
                institution="MIT",
                degree="MS",
                field="Computer Science",
                end_year="2020",
            ),
        ],
        provenance=[
            ProvenanceRecord(
                source=SourceType.RECRUITER_CSV,
                field_name="full_name",
                original_value="Alice Johnson",
                normalized_value="Alice Johnson",
                normalizations_applied=("title_case",),
                confidence=0.90,
            ),
        ],
        field_confidence={"full_name": 0.90, "emails": 0.90, "phones": 0.90},
        overall_confidence=0.88,
    )
