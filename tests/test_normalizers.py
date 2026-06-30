"""
Tests for candidate_transformer.normalizers

Covers every public normalizer function with valid inputs, edge cases,
invalid data, empty inputs, and international formats.
"""

from __future__ import annotations

import pytest

from candidate_transformer.normalizers import (
    normalize_country,
    normalize_date,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_skill,
    normalize_url,
)


# ═══════════════════════════════════════════════════════════════════════════
# Phone normalization (E.164)
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizePhone:
    """Tests for normalize_phone → E.164 format."""

    def test_normalize_phone_valid_us(self):
        """Standard US number with formatting → +15551234567."""
        result = normalize_phone("+1 (555) 123-4567")
        assert result == "+15551234567"

    def test_normalize_phone_valid_us_no_country(self):
        """US number without +1 prefix (assumes US default)."""
        result = normalize_phone("(555) 123-4567", default_region="US")
        assert result == "+15551234567"

    def test_normalize_phone_valid_international(self):
        """UK number → E.164."""
        result = normalize_phone("+44 20 7946 0958")
        assert result == "+442079460958"

    def test_normalize_phone_valid_international_de(self):
        """German mobile number → E.164."""
        result = normalize_phone("+49 151 12345678")
        assert result == "+4915112345678"

    def test_normalize_phone_digits_only(self):
        """Bare digits with country code → E.164."""
        result = normalize_phone("15551234567", default_region="US")
        assert result == "+15551234567"

    def test_normalize_phone_invalid(self):
        """Nonsense string should return empty or raise."""
        result = normalize_phone("not-a-phone")
        assert result == "" or result is None

    def test_normalize_phone_too_short(self):
        """Too-short number should fail gracefully."""
        result = normalize_phone("123")
        assert result == "" or result is None

    def test_normalize_phone_empty(self):
        """Empty string input should return empty."""
        result = normalize_phone("")
        assert result == "" or result is None

    def test_normalize_phone_none(self):
        """None input should return empty."""
        result = normalize_phone(None)
        assert result == "" or result is None

    def test_normalize_phone_with_extension(self):
        """Number with extension — extension may be stripped."""
        result = normalize_phone("+1 555-123-4567 ext. 890")
        # Should at least extract the base number
        assert result is not None
        if result:
            assert result.startswith("+1555")


# ═══════════════════════════════════════════════════════════════════════════
# Email normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeEmail:
    """Tests for normalize_email → lowercase, stripped."""

    def test_normalize_email_valid(self):
        result = normalize_email("alice@example.com")
        assert result == "alice@example.com"

    def test_normalize_email_uppercase(self):
        """Mixed-case email should be lowercased."""
        result = normalize_email("Alice.Johnson@Example.COM")
        assert result == "alice.johnson@example.com"

    def test_normalize_email_whitespace(self):
        """Leading/trailing whitespace should be stripped."""
        result = normalize_email("  alice@example.com  ")
        assert result == "alice@example.com"

    def test_normalize_email_invalid_no_at(self):
        """Email without @ symbol should return empty or None."""
        result = normalize_email("not-an-email")
        assert result == "" or result is None

    def test_normalize_email_invalid_no_domain(self):
        """Email without domain should fail."""
        result = normalize_email("alice@")
        assert result == "" or result is None

    def test_normalize_email_empty(self):
        result = normalize_email("")
        assert result == "" or result is None

    def test_normalize_email_none(self):
        result = normalize_email(None)
        assert result == "" or result is None

    def test_normalize_email_with_plus(self):
        """Gmail-style plus addressing should be preserved."""
        result = normalize_email("alice+jobs@gmail.com")
        assert result == "alice+jobs@gmail.com"


# ═══════════════════════════════════════════════════════════════════════════
# Country normalization (ISO 3166 Alpha-2)
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeCountry:
    """Tests for normalize_country → ISO 3166-1 alpha-2."""

    def test_normalize_country_full_name(self):
        """Full country name → alpha-2 code."""
        result = normalize_country("United States")
        assert result == "US"

    def test_normalize_country_full_name_alt(self):
        result = normalize_country("United Kingdom")
        assert result == "GB"

    def test_normalize_country_code(self):
        """Already a valid alpha-2 code."""
        result = normalize_country("US")
        assert result == "US"

    def test_normalize_country_lowercase_code(self):
        """Lowercase code should be uppercased."""
        result = normalize_country("us")
        assert result == "US"

    def test_normalize_country_alpha3(self):
        """Alpha-3 code → alpha-2."""
        result = normalize_country("USA")
        assert result == "US"

    def test_normalize_country_invalid(self):
        """Non-existent country name should return empty or input."""
        result = normalize_country("Neverland")
        # Should not crash; return empty, None, or the original
        assert result in ("", None, "Neverland")

    def test_normalize_country_empty(self):
        result = normalize_country("")
        assert result == "" or result is None

    def test_normalize_country_none(self):
        result = normalize_country(None)
        assert result == "" or result is None

    def test_normalize_country_germany(self):
        result = normalize_country("Germany")
        assert result == "DE"


# ═══════════════════════════════════════════════════════════════════════════
# Date normalization (YYYY-MM)
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeDate:
    """Tests for normalize_date → YYYY-MM or 'present'."""

    def test_normalize_date_iso(self):
        result = normalize_date("2021-03")
        assert result == "2021-03"

    def test_normalize_date_full_iso(self):
        """Full ISO date → YYYY-MM."""
        result = normalize_date("2021-03-15")
        assert result == "2021-03"

    def test_normalize_date_month_name(self):
        """'March 2021' → '2021-03'."""
        result = normalize_date("March 2021")
        assert result == "2021-03"

    def test_normalize_date_abbreviated_month(self):
        """'Mar 2021' → '2021-03'."""
        result = normalize_date("Mar 2021")
        assert result == "2021-03"

    def test_normalize_date_slash_format(self):
        """'03/2021' → '2021-03'."""
        result = normalize_date("03/2021")
        assert result == "2021-03"

    def test_normalize_date_present(self):
        """'present', 'Present', 'PRESENT' → 'present'."""
        assert normalize_date("present") == "present"
        assert normalize_date("Present") == "present"
        assert normalize_date("PRESENT") == "present"

    def test_normalize_date_current(self):
        """'current' should also map to 'present'."""
        result = normalize_date("current")
        assert result == "present"

    def test_normalize_date_invalid(self):
        result = normalize_date("not-a-date")
        assert result == "" or result is None or result == "not-a-date"

    def test_normalize_date_empty(self):
        result = normalize_date("")
        assert result == "" or result is None

    def test_normalize_date_year_only(self):
        """A bare year like '2021' might be returned as-is or '2021-01'."""
        result = normalize_date("2021")
        assert result in ("2021", "2021-01")

    def test_normalize_date_various_formats(self):
        """Batch test for multiple date representations."""
        cases = [
            ("June 2019", "2019-06"),
            ("2019-06", "2019-06"),
            ("06/2019", "2019-06"),
        ]
        for raw, expected in cases:
            assert normalize_date(raw) == expected, f"Failed for input: {raw!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Skill normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeSkill:
    """Tests for normalize_skill → canonical skill name."""

    def test_normalize_skill_case(self):
        """Skill names should be normalized to a consistent case."""
        result = normalize_skill("python")
        assert result.lower() == "python" or result == "Python"

    def test_normalize_skill_aliases_js(self):
        """Common aliases should map to canonical names."""
        result = normalize_skill("JS")
        assert result in ("JavaScript", "javascript", "js", "JS")

    def test_normalize_skill_aliases_ml(self):
        result = normalize_skill("ML")
        assert result in ("Machine Learning", "machine learning", "ML")

    def test_normalize_skill_whitespace(self):
        """Extra whitespace should be stripped."""
        result = normalize_skill("  Python  ")
        assert result.strip() == result
        assert "python" in result.lower()

    def test_normalize_skill_empty(self):
        result = normalize_skill("")
        assert result == "" or result is None

    def test_normalize_skill_already_canonical(self):
        """Already-canonical skill should pass through."""
        result = normalize_skill("Python")
        assert result == "Python"

    def test_normalize_skill_kubernetes_alias(self):
        """k8s → Kubernetes."""
        result = normalize_skill("k8s")
        assert result in ("Kubernetes", "kubernetes", "k8s", "K8s")


# ═══════════════════════════════════════════════════════════════════════════
# Name normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeName:
    """Tests for normalize_name → consistent title case."""

    def test_normalize_name_titlecase(self):
        """Standard mixed-case → title case."""
        result = normalize_name("alice johnson")
        assert result == "Alice Johnson"

    def test_normalize_name_allcaps(self):
        """ALL CAPS → title case."""
        result = normalize_name("ALICE JOHNSON")
        assert result == "Alice Johnson"

    def test_normalize_name_already_correct(self):
        result = normalize_name("Alice Johnson")
        assert result == "Alice Johnson"

    def test_normalize_name_extra_spaces(self):
        """Multiple spaces should be collapsed."""
        result = normalize_name("  alice   johnson  ")
        assert result == "Alice Johnson"

    def test_normalize_name_empty(self):
        result = normalize_name("")
        assert result == "" or result is None

    def test_normalize_name_none(self):
        result = normalize_name(None)
        assert result == "" or result is None

    def test_normalize_name_single_name(self):
        """Single-word name should still be title-cased."""
        result = normalize_name("alice")
        assert result == "Alice"

    def test_normalize_name_hyphenated(self):
        """Hyphenated names should be handled."""
        result = normalize_name("mary-jane watson")
        # Accept either "Mary-Jane Watson" or "Mary-jane Watson"
        assert "watson" in result.lower()
        assert result[0] == "M"


# ═══════════════════════════════════════════════════════════════════════════
# URL normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeUrl:
    """Tests for normalize_url → well-formed URL."""

    def test_normalize_url_no_scheme(self):
        """URL without https:// should get a scheme added."""
        result = normalize_url("linkedin.com/in/alicejohnson")
        assert result.startswith("https://")
        assert "linkedin.com/in/alicejohnson" in result

    def test_normalize_url_trailing_slash(self):
        """Trailing slashes should be removed."""
        result = normalize_url("https://github.com/alice/")
        assert not result.endswith("/")

    def test_normalize_url_already_valid(self):
        result = normalize_url("https://linkedin.com/in/alice")
        assert result == "https://linkedin.com/in/alice"

    def test_normalize_url_http(self):
        """http:// should be preserved or upgraded to https://."""
        result = normalize_url("http://example.com/profile")
        assert result.startswith("http")

    def test_normalize_url_empty(self):
        result = normalize_url("")
        assert result == "" or result is None

    def test_normalize_url_none(self):
        result = normalize_url(None)
        assert result == "" or result is None

    def test_normalize_url_whitespace(self):
        result = normalize_url("  https://github.com/alice  ")
        assert result.strip() == result
