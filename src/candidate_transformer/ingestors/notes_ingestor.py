"""Recruiter notes ingestor.

Reads plain-text recruiter notes files and uses regex-based heuristics
to extract structured candidate information.  Handles multiple
candidates within a single file by splitting on clear separators.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from candidate_transformer.models import (
    CandidateRecord,
    Links,
    Location,
    SourceType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_PHONE_RE = re.compile(r"[\+]?[\d][\d\s\-\(\)\.]{7,15}")
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+/?", re.IGNORECASE
)
_GITHUB_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/[\w\-]+/?", re.IGNORECASE
)
_URL_RE = re.compile(r"https?://[^\s,;\"'<>\)]+")

# Name extraction patterns
_NAME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:Candidate|Name|Applicant)\s*:\s*(.+)", re.IGNORECASE),
    re.compile(r"(?:Spoke|Talked|Met|Chatted)\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.IGNORECASE),
    re.compile(r"(?:Interviewed|Screening|Screen(?:ed)?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.IGNORECASE),
    re.compile(r"(?:Resume|CV|Profile)\s+(?:of|for|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", re.IGNORECASE),
]

# Company extraction patterns
_COMPANY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:works?|working)\s+at\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"currently\s+at\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"(?:employed\s+)?at\s+(.+?)\s+(?:as|since|for)\s+", re.IGNORECASE),
    re.compile(r"(?:currently|presently)\s+(?:with|employed\s+by)\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"(?:from|left|leaving|joined)\s+(.+?)(?:\.|,|\s+(?:to|in|as|where))", re.IGNORECASE),
    re.compile(
        r"(?:He(?:'s)?|She(?:'s)?|They(?:'re)?)\s+(?:currently\s+)?at\s+(.+?)"
        r"(?:\s+as\s+|\.|,|$)",
        re.IGNORECASE,
    ),
]

# Skills extraction patterns
_SKILL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:knows?|knowledge\s+of)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:experienced?|expertise)\s+(?:in|with)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:proficient|proficiency)\s+(?:in|with)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:skilled?|skills?)\s+(?:in|with)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:strong|solid|good)\s+(.+?)\s+background", re.IGNORECASE),
    re.compile(r"(.+?)\s+(?:expertise|expert)", re.IGNORECASE),
    re.compile(r"(?:familiar(?:ity)?)\s+with\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:has\s+)?(?:experience|background)\s+(?:in|with)\s+(.+?)(?:\.|$)", re.IGNORECASE),
]

# Years of experience patterns
_YOE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(\d+)\+?\s*years?\s+(?:of\s+)?experience", re.IGNORECASE),
    re.compile(r"about\s+(\d+)\s+years?\s+(?:of\s+)?experience", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*years?\s+(?:in\s+(?:the\s+)?)?(?:industry|field|tech)", re.IGNORECASE),
    re.compile(r"(\d+)\+?\s*(?:yrs?|years?)\s+exp", re.IGNORECASE),
    re.compile(r"experience:\s*(\d+)\+?\s*(?:yrs?|years?)", re.IGNORECASE),
]

# Location extraction patterns
_LOCATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:based|located|location)\s+(?:in|:)\s+(.+?)(?:\.|,\s*(?:has|with|and)|$)", re.IGNORECASE),
    re.compile(r"(?:lives?|living|resides?|residing)\s+(?:in|at)\s+(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)", re.IGNORECASE),
]

# Title extraction patterns
_TITLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:Title|Role|Position)\s*:\s*(.+)", re.IGNORECASE),
    re.compile(
        r"(?:as\s+(?:a\s+)?|is\s+(?:a\s+)?)("
        r"(?:Senior|Junior|Lead|Staff|Principal|Chief|Head|VP|Director|Manager|"
        r"Sr\.?|Jr\.?)\s+.*?"
        r"(?:Engineer|Developer|Manager|Designer|Analyst|Consultant|"
        r"Architect|Administrator|Coordinator|Specialist|Officer|Director)"
        r")",
        re.IGNORECASE,
    ),
]

# Separator pattern for splitting notes into candidate blocks
_BLOCK_SEPARATOR = re.compile(
    r"(?:"
    r"\n\s*---+\s*\n"         # --- separators
    r"|\n\s*===+\s*\n"        # === separators
    r"|\n\s*\*\*\*+\s*\n"     # *** separators
    r"|\n\s*#{3,}\s*\n"       # ### separators
    r")"
)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_emails(text: str) -> list[str]:
    """Extract unique email addresses from text.

    Args:
        text: Note text.

    Returns:
        List of unique email addresses.
    """
    matches = _EMAIL_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for email in matches:
        lower = email.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(email)
    return result


def _extract_phones(text: str) -> list[str]:
    """Extract phone numbers from text.

    Args:
        text: Note text.

    Returns:
        List of cleaned phone number strings.
    """
    matches = _PHONE_RE.findall(text)
    result: list[str] = []
    seen: set[str] = set()
    for phone in matches:
        cleaned = phone.strip()
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) < 7 or len(digits) > 15:
            continue
        if digits not in seen:
            seen.add(digits)
            result.append(cleaned)
    return result


def _extract_name(text: str) -> str:
    """Extract candidate name using heuristic patterns.

    Args:
        text: Note text block.

    Returns:
        Extracted name string, or empty string.
    """
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip().rstrip(".,;:")
            # Validate: should look like a name (2–5 words, mostly alpha)
            words = name.split()
            if 1 <= len(words) <= 5:
                alpha_ratio = sum(
                    1 for c in name if c.isalpha() or c.isspace()
                ) / max(len(name), 1)
                if alpha_ratio > 0.8:
                    return name
    return ""


def _extract_companies(text: str) -> list[str]:
    """Extract company names from text.

    Args:
        text: Note text block.

    Returns:
        List of company name strings.
    """
    companies: list[str] = []
    seen: set[str] = set()

    for pattern in _COMPANY_PATTERNS:
        for match in pattern.finditer(text):
            company = match.group(1).strip().rstrip(".,;:")
            # Basic validation
            if not company or len(company) > 80:
                continue
            lower = company.lower()
            if lower not in seen:
                seen.add(lower)
                companies.append(company)

    return companies


def _extract_skills(text: str) -> list[str]:
    """Extract skills from text using heuristic patterns.

    Args:
        text: Note text block.

    Returns:
        List of skill strings.
    """
    skills: list[str] = []
    seen: set[str] = set()

    for pattern in _SKILL_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).strip().rstrip(".,;:")
            # Split on "and", commas, etc.
            parts: list[str] = []
            for sep in [" and ", ",", ";", "|"]:
                if sep in raw:
                    parts = [p.strip() for p in raw.split(sep) if p.strip()]
                    break
            if not parts:
                parts = [raw]

            for skill in parts:
                # Clean up
                skill = skill.strip().rstrip(".,;:")
                if not skill or len(skill) > 60:
                    continue
                lower = skill.lower()
                if lower not in seen:
                    seen.add(lower)
                    skills.append(skill)

    return skills


def _extract_years_experience(text: str) -> float | None:
    """Extract years of experience from text.

    Args:
        text: Note text block.

    Returns:
        Years as float, or ``None`` if not found.
    """
    for pattern in _YOE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, TypeError):
                continue
    return None


def _extract_location(text: str) -> Location | None:
    """Extract location from text.

    Args:
        text: Note text block.

    Returns:
        Location object, or ``None`` if not found.
    """
    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = match.group(1).strip().rstrip(".,;:")
            if not raw:
                continue
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            city = parts[0] if len(parts) >= 1 else ""
            region = parts[1] if len(parts) >= 2 else ""
            country = parts[2] if len(parts) >= 3 else ""
            if city:
                return Location(city=city, region=region, country=country)
    return None


def _extract_links(text: str) -> Links:
    """Extract profile links from text.

    Args:
        text: Note text block.

    Returns:
        A ``Links`` object.
    """
    linkedin = ""
    github = ""
    portfolio = ""
    other: list[str] = []

    # Named link patterns (e.g., "LinkedIn: url")
    linkedin_named = re.search(
        r"LinkedIn\s*:\s*(https?://[^\s]+|(?:www\.)?linkedin\.com/in/[\w\-]+/?)",
        text, re.IGNORECASE,
    )
    if linkedin_named:
        url = linkedin_named.group(1).strip()
        if not url.startswith("http"):
            url = "https://" + url
        linkedin = url
    else:
        li_matches = _LINKEDIN_RE.findall(text)
        if li_matches:
            url = li_matches[0].strip()
            if not url.startswith("http"):
                url = "https://" + url
            linkedin = url

    github_named = re.search(
        r"GitHub\s*:\s*(https?://[^\s]+|(?:www\.)?github\.com/[\w\-]+/?)",
        text, re.IGNORECASE,
    )
    if github_named:
        url = github_named.group(1).strip()
        if not url.startswith("http"):
            url = "https://" + url
        github = url
    else:
        gh_matches = _GITHUB_RE.findall(text)
        if gh_matches:
            url = gh_matches[0].strip()
            if not url.startswith("http"):
                url = "https://" + url
            github = url

    all_urls = _URL_RE.findall(text)
    for url in all_urls:
        url_clean = url.rstrip(".,;:)")
        lower = url_clean.lower()
        if "linkedin.com" in lower or "github.com" in lower:
            continue
        if not portfolio:
            portfolio = url_clean
        elif url_clean not in other:
            other.append(url_clean)

    return Links(linkedin=linkedin, github=github, portfolio=portfolio, other=other)


def _extract_title(text: str) -> str:
    """Extract job title from text.

    Args:
        text: Note text block.

    Returns:
        Title string, or empty string.
    """
    for pattern in _TITLE_PATTERNS:
        match = pattern.search(text)
        if match:
            title = match.group(1).strip().rstrip(".,;:")
            if title and len(title) < 80:
                return title
    return ""


# ---------------------------------------------------------------------------
# Block processing
# ---------------------------------------------------------------------------

def _split_into_blocks(text: str) -> list[str]:
    """Split notes text into per-candidate blocks.

    Uses separator patterns (``---``, ``===``, etc.) and also detects
    repeated ``Candidate:`` headers within the same file.

    Args:
        text: Full notes text.

    Returns:
        List of text blocks, one per candidate (or one block if no
        separators are found).
    """
    # First try explicit separators
    blocks = _BLOCK_SEPARATOR.split(text)
    blocks = [b.strip() for b in blocks if b.strip()]

    if len(blocks) > 1:
        logger.debug("Split notes into %d blocks using separators", len(blocks))
        return blocks

    # Try splitting on "Candidate:" headers
    candidate_splits = re.split(
        r"(?=\n\s*(?:Candidate|Applicant|Name)\s*:)",
        text, flags=re.IGNORECASE,
    )
    candidate_splits = [b.strip() for b in candidate_splits if b.strip()]
    if len(candidate_splits) > 1:
        logger.debug(
            "Split notes into %d blocks using Candidate: headers",
            len(candidate_splits),
        )
        return candidate_splits

    # Return as single block
    return [text.strip()] if text.strip() else []


def _process_block(
    block: str,
    source_file: str,
    block_index: int,
) -> CandidateRecord | None:
    """Process a single text block into a CandidateRecord.

    Args:
        block: Text block for one candidate.
        source_file: Absolute path to the source file.
        block_index: 0-based index of this block in the file.

    Returns:
        A ``CandidateRecord``, or ``None`` if the block has no
        useful information.
    """
    full_name = _extract_name(block)
    emails = _extract_emails(block)
    phones = _extract_phones(block)
    companies = _extract_companies(block)
    skills = _extract_skills(block)
    yoe = _extract_years_experience(block)
    location = _extract_location(block)
    links = _extract_links(block)
    title = _extract_title(block)

    # Skip blocks with no identifying information
    if not full_name and not emails and not phones:
        logger.debug(
            "Skipping block %d with no identity info in %s",
            block_index, source_file,
        )
        return None

    current_company = companies[0] if companies else ""
    headline = title

    raw_data: dict[str, Any] = {
        "block_index": block_index,
        "block_text": block[:500],
        "companies_found": companies,
    }

    return CandidateRecord(
        source_type=SourceType.RECRUITER_NOTES,
        source_file=source_file,
        full_name=full_name,
        emails=emails,
        phones=phones,
        headline=headline,
        current_company=current_company,
        years_experience=yoe,
        skills=skills,
        location=location,
        links=links,
        raw_data=raw_data,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_notes(file_path: str) -> list[CandidateRecord]:
    """Ingest recruiter notes from a plain text file.

    Uses regex and NLP heuristics to extract structured candidate
    information from free-form text.  Handles multiple candidates
    per file by splitting on separators.

    Args:
        file_path: Path to the recruiter notes text file.

    Returns:
        List of ``CandidateRecord`` objects. Returns an empty list if
        the file is missing, empty, or unparseable.
    """
    logger.info("Starting recruiter notes ingestion from: %s", file_path)

    if not file_path or not file_path.strip():
        logger.warning("Empty file path provided to notes ingestor")
        return []

    if not os.path.isfile(file_path):
        logger.warning("Notes file not found: %s", file_path)
        raise FileNotFoundError(f"Notes file not found: {file_path}")

    # Read file with encoding fallback
    raw_content: str = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=encoding) as fh:
                raw_content = fh.read()
            logger.debug("Read notes file with encoding: %s", encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error("OS error reading notes file %s: %s", file_path, exc)
            return []

    if not raw_content.strip():
        logger.warning("Notes file is empty: %s", file_path)
        return []

    abs_path = os.path.abspath(file_path)
    blocks = _split_into_blocks(raw_content)

    if not blocks:
        logger.warning("No content blocks found in notes file: %s", file_path)
        return []

    records: list[CandidateRecord] = []
    for idx, block in enumerate(blocks):
        try:
            record = _process_block(block, abs_path, idx)
            if record is not None:
                records.append(record)
                logger.debug(
                    "Extracted candidate from block %d: name=%r",
                    idx, record.full_name,
                )
        except Exception as exc:
            logger.warning(
                "Failed to process block %d in %s: %s", idx, file_path, exc
            )
            continue

    logger.info(
        "Notes ingestion complete: %d records from %s", len(records), file_path
    )
    return records
