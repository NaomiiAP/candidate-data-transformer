"""Resume ingestor for PDF and DOCX files.

Extracts text from resume files and applies regex-based heuristics to
identify structured fields: name, email, phone, URLs, skills,
experience sections, and education sections.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from candidate_transformer.models import (
    CandidateRecord,
    Education,
    Experience,
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

# Section header patterns — match lines that are likely section titles
_SECTION_HEADER_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z\s&/,\-]{2,}$"  # ALL CAPS lines
    r"|.{3,40}:\s*$"            # Lines ending with colon
    r"|(?:#+\s+).+"             # Markdown-style headers
    r")",
    re.MULTILINE,
)

# Specific section name patterns
_EXPERIENCE_HEADERS = re.compile(
    r"(?:work\s+)?experience|employment(?:\s+history)?|"
    r"professional\s+experience|career\s+history|work\s+history",
    re.IGNORECASE,
)
_EDUCATION_HEADERS = re.compile(
    r"education(?:al)?(?:\s+background)?|academic|degrees?|qualifications?",
    re.IGNORECASE,
)
_SKILLS_HEADERS = re.compile(
    r"(?:technical\s+)?skills|technologies|tech(?:nical)?\s+stack|"
    r"competenc(?:ies|y)|tools?\s+(?:&|and)\s+technologies|"
    r"programming\s+languages|proficienc(?:ies|y)",
    re.IGNORECASE,
)

# Date patterns in resumes
_DATE_RANGE_RE = re.compile(
    r"("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
    r"[\s,]*\d{4}"
    r"|"
    r"\d{4}"
    r"|"
    r"\d{1,2}/\d{4}"
    r")"
    r"\s*[-–—to]+\s*"
    r"("
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
    r"[\s,]*\d{4}"
    r"|"
    r"\d{4}"
    r"|"
    r"\d{1,2}/\d{4}"
    r"|"
    r"[Pp]resent|[Cc]urrent|[Nn]ow"
    r")",
    re.IGNORECASE,
)

# Month mapping for normalisation
_MONTH_MAP: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
}


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(file_path: str) -> str:
    """Extract all text from a PDF file using pdfplumber.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Concatenated text from all pages, or empty string on failure.
    """
    try:
        import pdfplumber
    except ImportError:
        logger.error(
            "pdfplumber is not installed. Install it with: pip install pdfplumber"
        )
        return ""

    try:
        pages_text: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text)
                    else:
                        logger.debug(
                            "No text extracted from page %d of %s",
                            page_num, file_path,
                        )
                except Exception as exc:
                    logger.warning(
                        "Error extracting text from page %d of %s: %s",
                        page_num, file_path, exc,
                    )
        full_text = "\n".join(pages_text)
        logger.debug(
            "Extracted %d characters from PDF %s (%d pages)",
            len(full_text), file_path, len(pages_text),
        )
        return full_text
    except Exception as exc:
        logger.error("Failed to open/read PDF %s: %s", file_path, exc)
        return ""


def _extract_text_from_docx(file_path: str) -> str:
    """Extract all text from a DOCX file using python-docx.

    Args:
        file_path: Path to the DOCX file.

    Returns:
        Concatenated paragraph text, or empty string on failure.
    """
    try:
        import docx
    except ImportError:
        logger.error(
            "python-docx is not installed. Install it with: pip install python-docx"
        )
        return ""

    try:
        doc = docx.Document(file_path)
        paragraphs: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        full_text = "\n".join(paragraphs)
        logger.debug(
            "Extracted %d characters from DOCX %s (%d paragraphs)",
            len(full_text), file_path, len(paragraphs),
        )
        return full_text
    except Exception as exc:
        logger.error("Failed to open/read DOCX %s: %s", file_path, exc)
        return ""


def _extract_text_from_txt(file_path: str) -> str:
    """Extract text from a plain text file with encoding fallback.

    Args:
        file_path: Path to the text file.

    Returns:
        File content as a string, or empty string on failure.
    """
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=encoding) as fh:
                content = fh.read()
            logger.debug(
                "Read %d characters from TXT %s (encoding=%s)",
                len(content), file_path, encoding,
            )
            return content
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error("OS error reading text file %s: %s", file_path, exc)
            return ""
    logger.error("Could not decode text file with any known encoding: %s", file_path)
    return ""


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _extract_emails(text: str) -> list[str]:
    """Extract unique email addresses from text.

    Args:
        text: Full resume text.

    Returns:
        List of unique email addresses found.
    """
    matches = _EMAIL_RE.findall(text)
    # Deduplicate while preserving order
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
        text: Full resume text.

    Returns:
        List of cleaned phone number strings.
    """
    matches = _PHONE_RE.findall(text)
    result: list[str] = []
    seen: set[str] = set()
    for phone in matches:
        cleaned = phone.strip()
        # Filter out things that are clearly not phone numbers
        digits_only = re.sub(r"\D", "", cleaned)
        if len(digits_only) < 7 or len(digits_only) > 15:
            continue
        if digits_only not in seen:
            seen.add(digits_only)
            result.append(cleaned)
    return result


def _extract_links(text: str) -> Links:
    """Extract LinkedIn, GitHub, and other URLs from text.

    Args:
        text: Full resume text.

    Returns:
        A ``Links`` object populated with found URLs.
    """
    linkedin = ""
    github = ""
    portfolio = ""
    other: list[str] = []

    linkedin_matches = _LINKEDIN_RE.findall(text)
    if linkedin_matches:
        url = linkedin_matches[0].strip()
        if not url.startswith("http"):
            url = "https://" + url
        linkedin = url

    github_matches = _GITHUB_RE.findall(text)
    if github_matches:
        url = github_matches[0].strip()
        if not url.startswith("http"):
            url = "https://" + url
        github = url

    # Find other URLs that aren't LinkedIn or GitHub
    all_urls = _URL_RE.findall(text)
    for url in all_urls:
        url_clean = url.rstrip(".,;:)")
        lower = url_clean.lower()
        if "linkedin.com" in lower or "github.com" in lower:
            continue
        if not portfolio:
            portfolio = url_clean
        else:
            if url_clean not in other:
                other.append(url_clean)

    return Links(linkedin=linkedin, github=github, portfolio=portfolio, other=other)


def _extract_name(text: str, emails: list[str]) -> str:
    """Extract the candidate's name from resume text.

    Heuristic: the name is typically the first non-empty line, or the
    line immediately before the first section header or contact info.

    Args:
        text: Full resume text.
        emails: Already-extracted emails (used to skip contact lines).

    Returns:
        Best-guess name string.
    """
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip lines that are clearly not names
        if _EMAIL_RE.search(stripped):
            continue
        if _PHONE_RE.search(stripped):
            continue
        if _URL_RE.search(stripped):
            continue
        # Skip lines that look like section headers
        if _EXPERIENCE_HEADERS.search(stripped):
            continue
        if _EDUCATION_HEADERS.search(stripped):
            continue
        if _SKILLS_HEADERS.search(stripped):
            continue
        # Skip very long lines (unlikely to be just a name)
        if len(stripped) > 60:
            continue
        # Skip lines with too many special characters
        alpha_ratio = sum(1 for c in stripped if c.isalpha()) / max(len(stripped), 1)
        if alpha_ratio < 0.6:
            continue

        return stripped

    return ""


def _normalise_date(raw: str) -> str:
    """Normalise a date string to YYYY-MM or YYYY format.

    Args:
        raw: Raw date string like ``"Jan 2020"``, ``"2020"``,
            ``"01/2020"``, or ``"Present"``.

    Returns:
        Normalised date string.
    """
    cleaned = raw.strip()
    if not cleaned:
        return ""

    if cleaned.lower() in ("present", "current", "now"):
        return "present"

    # Already normalised
    if re.match(r"^\d{4}-\d{2}$", cleaned):
        return cleaned

    # "01/2020"
    match = re.match(r"^(\d{1,2})/(\d{4})$", cleaned)
    if match:
        month = match.group(1).zfill(2)
        year = match.group(2)
        return f"{year}-{month}"

    # "Month YYYY" or "Mon YYYY"
    match = re.match(r"^([A-Za-z]+)[\s,]*(\d{4})$", cleaned)
    if match:
        month_str = match.group(1).lower()
        year = match.group(2)
        month_num = _MONTH_MAP.get(month_str)
        if month_num:
            return f"{year}-{month_num}"
        return year

    # Just a year
    if re.match(r"^\d{4}$", cleaned):
        return cleaned

    return cleaned


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def _find_sections(text: str) -> dict[str, str]:
    """Split resume text into named sections.

    Identifies section headers and captures the text between them.

    Args:
        text: Full resume text.

    Returns:
        Dictionary mapping lowercase section names to their content text.
    """
    lines = text.split("\n")
    sections: dict[str, str] = {}
    current_section: str = "_header"
    current_lines: list[str] = []

    # Common section header patterns
    header_pattern = re.compile(
        r"^(?:#{1,3}\s+)?"  # Optional markdown
        r"("
        r"(?:work\s+)?experience|employment(?:\s+history)?|"
        r"professional\s+experience|career\s+history|work\s+history|"
        r"education(?:al)?(?:\s+background)?|academic|"
        r"(?:technical\s+)?skills|technologies|tech(?:nical)?\s+stack|"
        r"competenc(?:ies|y)|tools?\s+(?:&|and)\s+technologies|"
        r"programming\s+languages|proficienc(?:ies|y)|"
        r"summary|objective|profile|about(?:\s+me)?|"
        r"certifications?|awards?|projects?|publications?|"
        r"languages?|interests?|references?|"
        r"volunteer(?:ing)?|activities"
        r")"
        r"\s*:?\s*$",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        match = header_pattern.match(stripped)

        # Also detect ALL CAPS headers of at least 3 chars
        is_all_caps_header = (
            len(stripped) >= 3
            and stripped.isupper()
            and stripped.replace(" ", "").isalpha()
        )

        if match or is_all_caps_header:
            # Save previous section
            if current_lines:
                sections[current_section.lower()] = "\n".join(current_lines)
            current_section = stripped.rstrip(":").strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    if current_lines:
        sections[current_section.lower()] = "\n".join(current_lines)

    return sections


def _extract_skills_from_section(section_text: str) -> list[str]:
    """Extract individual skills from a skills section.

    Handles comma-separated, pipe-separated, bullet-separated,
    and newline-separated lists.

    Args:
        section_text: Text content of the skills section.

    Returns:
        List of skill strings.
    """
    skills: list[str] = []

    for line in section_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Remove bullet markers
        stripped = re.sub(r"^[\-•●○▪▸►◦*]\s*", "", stripped)
        stripped = stripped.strip()

        if not stripped:
            continue

        # Split on common delimiters
        for sep in ["|", ";", ","]:
            if sep in stripped:
                parts = [s.strip() for s in stripped.split(sep) if s.strip()]
                skills.extend(parts)
                break
        else:
            # If no delimiter found, treat the whole line as one skill
            # (unless it's too long, which suggests a sentence)
            if len(stripped) < 50:
                skills.append(stripped)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        lower = skill.lower()
        if lower not in seen and len(skill) < 100:
            seen.add(lower)
            unique.append(skill)

    return unique


def _extract_experience_from_section(section_text: str) -> list[Experience]:
    """Parse work experience entries from a section.

    Looks for patterns of company name, title, date ranges, and
    descriptions.

    Args:
        section_text: Text content of the experience section.

    Returns:
        List of ``Experience`` objects.
    """
    experiences: list[Experience] = []
    lines = section_text.split("\n")

    current_company = ""
    current_title = ""
    current_start = ""
    current_end = ""
    current_desc_lines: list[str] = []

    def _flush() -> None:
        """Save the current experience block if it has content."""
        nonlocal current_company, current_title, current_start, current_end
        nonlocal current_desc_lines
        if current_company or current_title:
            experiences.append(Experience(
                company=current_company,
                title=current_title,
                start=_normalise_date(current_start),
                end=_normalise_date(current_end),
                summary=" ".join(current_desc_lines).strip(),
            ))
        current_company = ""
        current_title = ""
        current_start = ""
        current_end = ""
        current_desc_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Remove bullet markers
        cleaned = re.sub(r"^[\-•●○▪▸►◦*]\s*", "", stripped).strip()

        # Check for date ranges — indicates a new entry
        date_match = _DATE_RANGE_RE.search(cleaned)
        if date_match:
            # If we already have data, flush the previous entry
            if current_company or current_title:
                _flush()

            current_start = date_match.group(1)
            current_end = date_match.group(2)

            # The text before the date range might be title or company
            before_date = cleaned[:date_match.start()].strip().rstrip("–—-|,")
            if before_date:
                # Check for "Title at Company" or "Company | Title" patterns
                at_match = re.match(
                    r"^(.+?)(?:\s+at\s+|\s*[|@]\s*)(.+)$",
                    before_date, re.IGNORECASE,
                )
                if at_match:
                    current_title = at_match.group(1).strip()
                    current_company = at_match.group(2).strip()
                else:
                    # Could be either title or company; assume title
                    current_title = before_date

            # Text after the date range
            after_date = cleaned[date_match.end():].strip().lstrip("–—-|,").strip()
            if after_date:
                # Check if this looks like a company or title
                if not current_company:
                    current_company = after_date
                elif not current_title:
                    current_title = after_date
            continue

        # If we don't have a company yet and this looks like one
        if not current_company and not current_title:
            # Check for "Title at Company" patterns
            at_match = re.match(
                r"^(.+?)(?:\s+at\s+|\s*[|@]\s*)(.+)$",
                cleaned, re.IGNORECASE,
            )
            if at_match:
                current_title = at_match.group(1).strip()
                current_company = at_match.group(2).strip()
                continue
            # First non-date line in a block — treat as title/company
            if current_start or current_end:
                # We have dates, so this is probably a company or title
                current_company = cleaned
            else:
                current_title = cleaned
            continue

        if current_title and not current_company:
            current_company = cleaned
            continue

        if current_company and not current_title:
            current_title = cleaned
            continue

        # Otherwise it's a description line
        current_desc_lines.append(cleaned)

    # Flush any remaining entry
    _flush()

    return experiences


def _extract_education_from_section(section_text: str) -> list[Education]:
    """Parse education entries from a section.

    Args:
        section_text: Text content of the education section.

    Returns:
        List of ``Education`` objects.
    """
    educations: list[Education] = []
    lines = section_text.split("\n")

    current_institution = ""
    current_degree = ""
    current_field = ""
    current_year = ""

    def _flush() -> None:
        nonlocal current_institution, current_degree, current_field, current_year
        if current_institution or current_degree:
            educations.append(Education(
                institution=current_institution,
                degree=current_degree,
                field=current_field,
                end_year=current_year,
            ))
        current_institution = ""
        current_degree = ""
        current_field = ""
        current_year = ""

    # Common degree abbreviations
    degree_pattern = re.compile(
        r"\b(?:B\.?S\.?|B\.?A\.?|M\.?S\.?|M\.?A\.?|M\.?B\.?A\.?|Ph\.?D\.?|"
        r"Bachelor|Master|Doctor|Associate|Diploma|Certificate)\b",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        cleaned = re.sub(r"^[\-•●○▪▸►◦*]\s*", "", stripped).strip()
        if not cleaned:
            continue

        # Look for year patterns
        year_match = re.search(r"\b((?:19|20)\d{2})\b", cleaned)

        # Check if this line has a degree
        has_degree = bool(degree_pattern.search(cleaned))

        if has_degree:
            if current_institution or current_degree:
                _flush()

            # Try to split degree and field: "BS in Computer Science"
            degree_match = degree_pattern.search(cleaned)
            if degree_match:
                current_degree = degree_match.group(0)
                remainder = cleaned[degree_match.end():].strip()
                # Remove connectors like "in", "of"
                remainder = re.sub(r"^(?:in|of|,)\s+", "", remainder, flags=re.IGNORECASE)
                if remainder:
                    current_field = remainder

                # Check for institution before the degree
                prefix = cleaned[:degree_match.start()].strip().rstrip(",- ")
                if prefix:
                    current_institution = prefix

            if year_match:
                current_year = year_match.group(1)
            continue

        if year_match and not current_year:
            current_year = year_match.group(1)

        # If we don't have an institution yet, this line might be one
        if not current_institution:
            current_institution = cleaned
            continue

        # If we have institution but no degree, might be degree/field
        if not current_degree:
            if degree_pattern.search(cleaned):
                current_degree = cleaned
            elif not current_field:
                current_field = cleaned
            continue

    _flush()

    return educations


def _extract_location(text: str) -> Location | None:
    """Try to extract location from resume text.

    Looks for common patterns like addresses or location mentions.

    Args:
        text: Full resume text.

    Returns:
        Location object, or ``None`` if not found.
    """
    # Look for city, state patterns (US-centric but common)
    patterns = [
        # "City, ST" or "City, State"
        re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z]{2})\b"),
        # "City, State, Country"
        re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*(\w+)\b"),
    ]

    # Check only the header area (first ~10 lines)
    header_text = "\n".join(text.split("\n")[:10])

    for pattern in patterns:
        match = pattern.search(header_text)
        if match:
            groups = match.groups()
            city = groups[0] if len(groups) >= 1 else ""
            region = groups[1] if len(groups) >= 2 else ""
            country = groups[2] if len(groups) >= 3 else ""
            return Location(city=city, region=region, country=country)

    return None


# ---------------------------------------------------------------------------
# Core parsing function
# ---------------------------------------------------------------------------

def _parse_resume_text(
    text: str,
    source_type: SourceType,
    source_file: str,
) -> CandidateRecord:
    """Parse extracted resume text into a CandidateRecord.

    Args:
        text: Extracted plain text from the resume.
        source_type: The source type (PDF or DOCX).
        source_file: Absolute path to the source file.

    Returns:
        A populated ``CandidateRecord``.
    """
    emails = _extract_emails(text)
    phones = _extract_phones(text)
    links = _extract_links(text)
    full_name = _extract_name(text, emails)
    location = _extract_location(text)

    # Find sections
    sections = _find_sections(text)
    logger.debug("Detected sections: %s", list(sections.keys()))

    # Skills
    skills: list[str] = []
    for section_name, section_text in sections.items():
        if _SKILLS_HEADERS.search(section_name):
            skills = _extract_skills_from_section(section_text)
            break

    # Experience
    experience: list[Experience] = []
    for section_name, section_text in sections.items():
        if _EXPERIENCE_HEADERS.search(section_name):
            experience = _extract_experience_from_section(section_text)
            break

    # Education
    education: list[Education] = []
    for section_name, section_text in sections.items():
        if _EDUCATION_HEADERS.search(section_name):
            education = _extract_education_from_section(section_text)
            break

    # Headline — use the summary/profile section if available
    headline = ""
    for section_name, section_text in sections.items():
        if re.search(r"summary|objective|profile|about", section_name, re.IGNORECASE):
            headline = " ".join(section_text.split()).strip()
            if len(headline) > 200:
                headline = headline[:200].rstrip() + "..."
            break

    # Current company from most recent experience
    current_company = ""
    if experience:
        latest = experience[0]
        if latest.end.lower() in ("present", "current", "now", ""):
            current_company = latest.company

    raw_data: dict[str, Any] = {
        "extracted_text_length": len(text),
        "sections_found": list(sections.keys()),
        "emails_found": len(emails),
        "phones_found": len(phones),
    }

    return CandidateRecord(
        source_type=source_type,
        source_file=source_file,
        full_name=full_name,
        emails=emails,
        phones=phones,
        headline=headline,
        current_company=current_company,
        skills=skills,
        experience=experience,
        education=education,
        location=location,
        links=links,
        raw_data=raw_data,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_resume_pdf(file_path: str) -> list[CandidateRecord]:
    """Ingest a PDF resume and return a candidate record.

    Uses pdfplumber to extract text, then applies regex-based
    heuristics to identify structured fields.

    Args:
        file_path: Path to the PDF resume file.

    Returns:
        List containing one ``CandidateRecord``, or empty list on failure.
    """
    logger.info("Starting PDF resume ingestion from: %s", file_path)

    if not file_path or not file_path.strip():
        logger.warning("Empty file path provided to PDF resume ingestor")
        return []

    if not os.path.isfile(file_path):
        logger.warning("PDF file not found: %s", file_path)
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    text = _extract_text_from_pdf(file_path)
    if not text.strip():
        logger.warning("No text extracted from PDF: %s", file_path)
        return []

    abs_path = os.path.abspath(file_path)
    try:
        record = _parse_resume_text(text, SourceType.RESUME_PDF, abs_path)
        logger.info(
            "PDF resume ingestion complete: name=%r from %s",
            record.full_name, file_path,
        )
        return [record]
    except Exception as exc:
        logger.error(
            "Unexpected error parsing PDF resume %s: %s", file_path, exc
        )
        return []


def ingest_resume_docx(file_path: str) -> list[CandidateRecord]:
    """Ingest a DOCX resume and return a candidate record.

    Uses python-docx to extract text, then applies regex-based
    heuristics to identify structured fields.

    Args:
        file_path: Path to the DOCX resume file.

    Returns:
        List containing one ``CandidateRecord``, or empty list on failure.
    """
    logger.info("Starting DOCX resume ingestion from: %s", file_path)

    if not file_path or not file_path.strip():
        logger.warning("Empty file path provided to DOCX resume ingestor")
        return []

    if not os.path.isfile(file_path):
        logger.warning("DOCX file not found: %s", file_path)
        raise FileNotFoundError(f"DOCX file not found: {file_path}")

    text = _extract_text_from_docx(file_path)
    if not text.strip():
        logger.warning("No text extracted from DOCX: %s", file_path)
        return []

    abs_path = os.path.abspath(file_path)
    try:
        record = _parse_resume_text(text, SourceType.RESUME_DOCX, abs_path)
        logger.info(
            "DOCX resume ingestion complete: name=%r from %s",
            record.full_name, file_path,
        )
        return [record]
    except Exception as exc:
        logger.error(
            "Unexpected error parsing DOCX resume %s: %s", file_path, exc
        )
        return []


def ingest_resume_txt(file_path: str) -> list[CandidateRecord]:
    """Ingest a plain-text resume and return a candidate record.

    This is a convenience function for testing with ``.txt`` resume files.
    Uses the PDF source type since the parsing logic is identical.

    Args:
        file_path: Path to the text resume file.

    Returns:
        List containing one ``CandidateRecord``, or empty list on failure.
    """
    logger.info("Starting TXT resume ingestion from: %s", file_path)

    if not file_path or not file_path.strip():
        logger.warning("Empty file path provided to TXT resume ingestor")
        return []

    if not os.path.isfile(file_path):
        logger.warning("TXT resume file not found: %s", file_path)
        raise FileNotFoundError(f"TXT resume file not found: {file_path}")

    text = _extract_text_from_txt(file_path)
    if not text.strip():
        logger.warning("No text extracted from TXT resume: %s", file_path)
        return []

    abs_path = os.path.abspath(file_path)
    try:
        record = _parse_resume_text(text, SourceType.RESUME_PDF, abs_path)
        logger.info(
            "TXT resume ingestion complete: name=%r from %s",
            record.full_name, file_path,
        )
        return [record]
    except Exception as exc:
        logger.error(
            "Unexpected error parsing TXT resume %s: %s", file_path, exc
        )
        return []
