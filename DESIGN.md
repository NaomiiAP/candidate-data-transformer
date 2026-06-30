# Technical Design Document — Candidate Data Transformer

## 1. Problem Statement

Recruiting workflows generate candidate data across multiple disconnected systems: recruiter spreadsheets (CSV), applicant tracking systems (JSON), GitHub profiles, LinkedIn exports, parsed resumes (PDF/DOCX), and free-text recruiter notes. Each source uses different schemas, field naming conventions, date formats, and quality levels.

**Goal:** Build a deterministic pipeline that ingests candidate records from any combination of these seven sources, identifies which records refer to the same person, merges them into a single canonical profile with conflict resolution, and outputs a clean JSON document with full provenance and confidence metadata.

**Constraints:**
- Must be deterministic — same inputs always produce same output (modulo UUIDs/timestamps).
- Must handle missing, malformed, and conflicting data gracefully.
- Output shape must be configurable at runtime without code changes.

---

## 2. Pipeline Architecture

```
Source Files → Detect → Extract → Normalize → Match → Merge → Confidence → Provenance → Project → Validate → Output
```

| Stage | Input | Output | Description |
|-------|-------|--------|-------------|
| **Detect** | File path + hint | `SourceType` enum | Determine which ingestor to use based on CLI flags or file extension |
| **Extract** | Raw file | `list[CandidateRecord]` | Parse source-specific format into internal model |
| **Normalize** | `CandidateRecord` fields | Cleaned `CandidateRecord` | Standardize phones, emails, dates, skills, names, countries, URLs |
| **Match** | `list[CandidateRecord]` | `list[list[CandidateRecord]]` | Group records by same person using email/phone/name overlap |
| **Merge** | `list[CandidateRecord]` (one cluster) | `CanonicalProfile` | Combine records using source-priority conflict resolution |
| **Confidence** | `CanonicalProfile` | Scored `CanonicalProfile` | Compute per-field and overall confidence scores |
| **Provenance** | Field values + sources | `list[ProvenanceRecord]` | Track origin, original value, and transformations for each field |
| **Project** | `CanonicalProfile` + config | `dict` | Select, rename, and filter output fields based on runtime config |
| **Validate** | Projected `dict` | Validated `dict` | Ensure output conforms to expected schema |
| **Output** | `dict` | JSON string | Serialize to stdout or file |

---

## 3. Canonical Output Schema

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `candidate_id` | `string` (UUID v4) | Unique identifier for the merged profile | `"a1b2c3d4-..."` |
| `full_name` | `string` | Title-cased canonical name | `"Alice Johnson"` |
| `emails` | `list[string]` | Deduplicated, sorted email addresses | `["alice@a.com", "alice@b.com"]` |
| `phones` | `list[string]` | Deduplicated, E.164 format | `["+15551234567"]` |
| `location.city` | `string` | City name | `"San Francisco"` |
| `location.region` | `string` | State/province | `"CA"` |
| `location.country` | `string` | ISO 3166-1 alpha-2 | `"US"` |
| `links.linkedin` | `string` | LinkedIn profile URL | `"https://linkedin.com/in/alice"` |
| `links.github` | `string` | GitHub profile URL | `"https://github.com/alice"` |
| `links.portfolio` | `string` | Portfolio/blog URL | `"https://alice.dev"` |
| `headline` | `string` | Professional headline | `"Senior DS \| ML & AI"` |
| `years_experience` | `float` | Years of professional experience | `7.0` |
| `skills[].name` | `string` | Canonical skill name | `"Python"` |
| `skills[].confidence` | `float` | Confidence score (0–1) | `0.95` |
| `skills[].sources` | `list[string]` | Which sources mentioned this skill | `["recruiter_csv", "ats_json"]` |
| `experience[].company` | `string` | Employer name | `"Acme Corp"` |
| `experience[].title` | `string` | Job title | `"Senior Data Scientist"` |
| `experience[].start` | `string` | Start date (YYYY-MM) | `"2021-03"` |
| `experience[].end` | `string` | End date (YYYY-MM or "present") | `"present"` |
| `education[].institution` | `string` | School name | `"MIT"` |
| `education[].degree` | `string` | Degree type | `"MS"` |
| `education[].field` | `string` | Field of study | `"Computer Science"` |
| `education[].end_year` | `string` | Graduation year (YYYY) | `"2020"` |
| `provenance[]` | `ProvenanceRecord` | Per-field origin tracking | *(see below)* |
| `overall_confidence` | `float` | Weighted average confidence (0–1) | `0.88` |

---

## 4. Normalization Choices

| Field | Standard | Library | Example |
|-------|----------|---------|---------|
| Phone numbers | E.164 | `phonenumbers` | `"(555) 123-4567"` → `"+15551234567"` |
| Countries | ISO 3166-1 alpha-2 | `pycountry` | `"United States"` → `"US"`, `"USA"` → `"US"` |
| Dates | YYYY-MM | `python-dateutil` | `"March 2021"` → `"2021-03"`, `"Present"` → `"present"` |
| Skills | Canonical name | Alias map | `"JS"` → `"JavaScript"`, `"k8s"` → `"Kubernetes"` |
| Names | Title case | Built-in | `"ALICE JOHNSON"` → `"Alice Johnson"` |
| Emails | Lowercase | Built-in | `"Alice@Example.COM"` → `"alice@example.com"` |
| URLs | Add scheme | Built-in | `"linkedin.com/in/alice"` → `"https://linkedin.com/in/alice"` |

---

## 5. Merge / Conflict Resolution Policy

### Source Priority Table

| Source | Priority | Rationale |
|--------|----------|-----------|
| `recruiter_csv` | 6 | Recruiter-verified, highest trust |
| `ats_json` | 5 | Structured system export |
| `resume_pdf` | 4 | Candidate-authored |
| `resume_docx` | 4 | Candidate-authored |
| `linkedin` | 3 | Semi-structured, self-reported |
| `github` | 2 | Public profile, limited fields |
| `recruiter_notes` | 1 | Free text, highest error rate |

### How the Winner Is Picked

1. **Scalar fields** (`full_name`, `headline`, `years_experience`): Value from the **highest-priority source** wins. Ties are broken by alphabetical source name for determinism.
2. **Collection fields** (`emails`, `phones`): Set **union** across all sources, then deduplicated.
3. **Structured collections** (`experience`, `education`): Deduplicated by `merge_key()` — an MD5 hash of key identifying fields. When duplicates are found, the entry from the higher-priority source is kept (it may have a richer `summary`).
4. **Skills**: Union after normalization, with per-skill confidence boosted by an agreement factor when multiple sources list the same skill.

---

## 6. Match Keys for Entity Resolution

Records are grouped into "same person" clusters using a **Union-Find** structure with the following match keys:

| Key Type | How It's Used |
|----------|---------------|
| **Email** | Exact match after lowercasing. If record A and B share any email, they match. |
| **Phone** | Exact match after E.164 normalization. If record A and B share any phone, they match. |
| **Name** | Normalized name match (case-insensitive, whitespace-collapsed). **Strict Conflict-Avoidance:** To prevent false positives (e.g. the 'Michael Chen' problem), name-based merging is explicitly disallowed if the records have conflicting unique identifiers (different emails, phones, or social URLs). |

**Transitivity:** If A↔B (email) and B↔C (phone), then A, B, C are all in the same cluster. The Union-Find structure handles this automatically.

---

## 7. Runtime Configuration / Projection

The `ProjectionConfig` dataclass controls the output shape:

```python
@dataclass
class ProjectionConfig:
    fields: list[str] | None = None        # None = all fields
    rename: dict[str, str] = field(default_factory=dict)
    on_missing: str = "null"               # "null" | "omit" | "error"
    include_provenance: bool = True
    include_confidence: bool = True
```

**Projection process:**
1. Serialize `CanonicalProfile` to a full dictionary via `to_dict()`.
2. If `fields` is specified, select only those keys.
3. Apply `rename` mapping to output keys.
4. Handle missing fields according to `on_missing` strategy.
5. Strip `provenance` and/or confidence fields if disabled.

---

## 8. Validation Approach

The pipeline validates its output before serialization:

1. **Type checking** — All fields must match expected types (strings, lists, nested objects).
2. **Required fields** — `candidate_id` and `full_name` must be non-empty.
3. **Format validation** — Phones must be E.164, countries must be alpha-2, dates must be YYYY-MM.
4. **Confidence bounds** — All confidence values must be in \[0.0, 1.0\].
5. **No duplicate emails/phones** — Collection fields are deduplicated before output.

Validation errors are logged with the specific field and value that failed, enabling quick debugging.

---

## 9. Edge Cases and Handling

### Edge Case 1: Same person across 5+ sources with conflicting data

**Scenario:** Alice appears in CSV (as "Alice M. Johnson"), ATS JSON (as "Alice Johnson"), LinkedIn (as "Alice J."), GitHub (as "alicejohnson"), and notes (as "Alice").

**Handling:** Entity matcher links all records via shared email. Merge engine selects "Alice M. Johnson" from the highest-priority source (CSV, priority 6). All emails and skills from all sources are unioned. Provenance records show each name variant and its source.

### Edge Case 2: Duplicate experience entries with different summaries

**Scenario:** CSV has `company=Acme, title=Senior DS, start=2021-03` with no summary. ATS JSON has the same entry with `summary="Led ML team"`.

**Handling:** `merge_key()` produces the same hash for both. The merge engine keeps the entry from the higher-priority source. If the lower-priority entry has a richer summary, the merge engine may prefer the more complete version (implementation-specific).

### Edge Case 3: Phone number in recruiter notes is US format without country code

**Scenario:** Notes contain `(555) 123-4567` with no `+1`.

**Handling:** `normalize_phone` is called with `default_region="US"`, which successfully parses and returns `+15551234567`. If the region is ambiguous, the number is logged as a warning and may be dropped.

### Edge Case 4: Completely empty source file

**Scenario:** The CSV file has headers but zero data rows.

**Handling:** The ingestor returns an empty list. The pipeline continues with records from other sources. If ALL sources are empty, the output is an empty `{"candidates": []}`.

### Edge Case 5: Two genuinely different candidates with the same name

**Scenario:** "John Smith" appears in two separate CSV rows with different emails and different companies.

**Handling:** The entity matcher treats them as separate clusters because they share no emails or phones. Each produces its own `CanonicalProfile`. Name-only matching requires additional corroborating signals.

---

## 10. Assumptions and Deliberate Scope Limits

1. **English-language data only.** Name normalization, date parsing, and notes extraction assume English text.
2. **Limited Live API calls.** GitHub ingestion works from cached JSON files by default (avoids rate limits and API key requirements in production). Online API mode handles HTTP 403 Rate Limit Exceeded status codes gracefully by logging warnings and falling back to cached profiles.
3. **No PII encryption.** Data is processed in cleartext. A production deployment would need at-rest and in-transit encryption.
4. **Single-machine processing.** The pipeline is designed for single-process execution, not distributed computing. A production system handling millions of candidates would need a different architecture.
5. **Static source priorities.** The priority table is hard-coded. A production system might allow per-organization or per-field priority configuration.
6. **No ML models.** Entity matching and skill extraction use rules and heuristics, not trained models.
7. **LinkedIn Profile Ingestion Justification.** LinkedIn profiles are ingested via exported JSON dumps rather than direct live scraping or profile API calls. LinkedIn lacks a public profile REST API, and automatic page scraping violates their Terms of Service, introducing severe legal and rate-limit risks for production systems.
8. **Dynamic UTC Provenance Timestamps.** The execution timestamp in `ProvenanceRecord` records represent the system execution wall-clock time. This is a deliberate exception to strict string-to-string output determinism. In regression testing, these dynamic timestamps are stripped out to verify functional data determinism.

---

## 11. What Would Be Improved With More Time

1. **Probabilistic entity resolution** — Replace hard match rules with a probabilistic model (e.g., Fellegi-Sunter) that produces match probabilities, allowing users to set their own threshold.

2. **Structured resume parsing** — Use layout-aware PDF/DOCX parsing (e.g., with ML-based section detection) instead of regex heuristics.

3. **Incremental pipeline** — Support adding new source data without reprocessing all existing records. Use a persistent store with change detection.

4. **Configurable priority overrides** — Allow users to set per-field trust levels (e.g., "trust LinkedIn for `headline` but trust CSV for `phone`").

5. **Comprehensive observability** — Add structured logging with correlation IDs, metrics (records processed, merge conflicts, normalization failures), and distributed tracing for production deployments.
