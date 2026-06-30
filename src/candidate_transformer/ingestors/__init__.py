"""Source ingestors package."""

from candidate_transformer.ingestors.csv_ingestor import ingest_csv
from candidate_transformer.ingestors.json_ingestor import ingest_json
from candidate_transformer.ingestors.github_ingestor import ingest_github
from candidate_transformer.ingestors.linkedin_ingestor import ingest_linkedin
from candidate_transformer.ingestors.resume_ingestor import ingest_resume_pdf, ingest_resume_docx
from candidate_transformer.ingestors.notes_ingestor import ingest_notes

__all__ = [
    "ingest_csv",
    "ingest_json",
    "ingest_github",
    "ingest_linkedin",
    "ingest_resume_pdf",
    "ingest_resume_docx",
    "ingest_notes",
]
