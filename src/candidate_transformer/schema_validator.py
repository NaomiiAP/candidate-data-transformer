"""
Schema validation for the projected output of the candidate pipeline.

Validates the final JSON-serializable dictionary against a JSON Schema
using the jsonschema library. Returns validation errors as a list of
human-readable strings — never crashes.
"""

from __future__ import annotations

import logging
from typing import Any

import jsonschema
from jsonschema import Draft7Validator, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default output JSON Schema
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "CandidateProfile",
    "description": "Validated output schema for a merged candidate profile.",
    "type": "object",
    "required": [
        "candidate_id",
        "full_name",
        "emails",
        "phones",
    ],
    "properties": {
        "candidate_id": {
            "type": "string",
            "minLength": 1,
            "description": "Deterministic unique identifier for the candidate.",
        },
        "full_name": {
            "type": "string",
            "description": "Normalized full name of the candidate.",
        },
        "emails": {
            "type": "array",
            "items": {
                "type": "string",
                "format": "email",
            },
            "description": "List of unique normalized email addresses.",
        },
        "phones": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "description": "List of unique E.164 phone numbers.",
        },
        "location": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                        "region": {"type": "string"},
                        "country": {
                            "type": "string",
                            "maxLength": 2,
                            "description": "ISO 3166 Alpha-2 country code.",
                        },
                    },
                    "additionalProperties": False,
                },
            ],
            "description": "Geographic location of the candidate.",
        },
        "links": {
            "oneOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "linkedin": {"type": "string"},
                        "github": {"type": "string"},
                        "portfolio": {"type": "string"},
                        "other": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "additionalProperties": False,
                },
            ],
            "description": "Profile links for the candidate.",
        },
        "headline": {
            "type": "string",
            "description": "Professional headline or title.",
        },
        "years_experience": {
            "oneOf": [
                {"type": "null"},
                {"type": "number", "minimum": 0},
            ],
            "description": "Total years of professional experience.",
        },
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
            "description": "List of skills with confidence scores.",
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "description": "Work experience history.",
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": "string"},
                    "degree": {"type": "string"},
                    "field": {"type": "string"},
                    "end_year": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "description": "Education history.",
        },
        "provenance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "source": {"type": "string"},
                    "method": {"type": "string"},
                },
                "additionalProperties": True,
            },
            "description": "Provenance tracking for field values.",
        },
        "overall_confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Overall confidence score for the merged profile.",
        },
    },
    "additionalProperties": True,
}


def _build_validator() -> Draft7Validator:
    """Build and cache a JSON Schema validator instance.

    Returns:
        A Draft7Validator configured with the default output schema.
    """
    jsonschema.Draft7Validator.check_schema(DEFAULT_OUTPUT_SCHEMA)
    return Draft7Validator(DEFAULT_OUTPUT_SCHEMA)


# Module-level validator instance (built once)
_VALIDATOR: Draft7Validator = _build_validator()


def validate_output(
    data: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> list[str]:
    """Validate a projected output dictionary against a JSON Schema.

    Uses the default output schema unless a custom schema is provided.
    Never raises exceptions — all errors are returned as strings.

    Args:
        data: The JSON-serializable dictionary to validate.
        schema: Optional custom JSON Schema. If None, uses the
            default output schema.

    Returns:
        List of human-readable validation error strings.
        Empty list means the data is valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append(
            f"Expected a dictionary, got {type(data).__name__}."
        )
        return errors

    try:
        if schema is not None:
            validator = Draft7Validator(schema)
        else:
            validator = _VALIDATOR

        for error in sorted(
            validator.iter_errors(data),
            key=lambda e: list(e.absolute_path),
        ):
            error_path = _format_error_path(error)
            error_message = _format_error_message(error, error_path)
            errors.append(error_message)

    except jsonschema.SchemaError as e:
        error_msg = f"Invalid JSON Schema: {e.message}"
        logger.error(error_msg)
        errors.append(error_msg)
    except Exception as e:
        error_msg = f"Unexpected validation error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        errors.append(error_msg)

    if errors:
        logger.warning(
            "Validation found %d error(s) in output.", len(errors)
        )
    else:
        logger.info("Output validation passed.")

    return errors


def _format_error_path(error: ValidationError) -> str:
    """Format the JSON path where a validation error occurred.

    Args:
        error: The jsonschema ValidationError.

    Returns:
        Dot-notation path string (e.g., 'skills[0].name').
    """
    parts: list[str] = []
    for segment in error.absolute_path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            if parts:
                parts.append(f".{segment}")
            else:
                parts.append(str(segment))

    return "".join(parts) if parts else "$"


def _format_error_message(
    error: ValidationError, path: str
) -> str:
    """Format a human-readable error message from a validation error.

    Args:
        error: The jsonschema ValidationError.
        path: The formatted path string.

    Returns:
        A single-line error description.
    """
    if error.validator == "required":
        missing = error.message
        return f"Missing required field at '{path}': {missing}"
    elif error.validator == "type":
        expected = error.schema.get("type", "unknown")
        actual = type(error.instance).__name__
        return (
            f"Type error at '{path}': expected {expected}, "
            f"got {actual}"
        )
    elif error.validator == "minLength":
        min_len = error.schema.get("minLength", 0)
        return (
            f"Value at '{path}' is too short "
            f"(minimum length: {min_len})"
        )
    elif error.validator == "format":
        fmt = error.schema.get("format", "unknown")
        return f"Invalid format at '{path}': expected {fmt}"
    elif error.validator in ("minimum", "maximum"):
        return f"Value at '{path}': {error.message}"
    else:
        return f"Validation error at '{path}': {error.message}"


def get_default_schema() -> dict[str, Any]:
    """Return a copy of the default output JSON Schema.

    Returns:
        A deep copy of the DEFAULT_OUTPUT_SCHEMA dictionary.
    """
    import copy

    return copy.deepcopy(DEFAULT_OUTPUT_SCHEMA)
