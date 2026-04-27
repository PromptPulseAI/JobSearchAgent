"""Tests for utils/pii_scrubber.py — GDPR PII detection and scrubbing."""
import pytest
from utils.pii_scrubber import scrub, scrub_dict, is_pii_free


class TestScrub:
    def test_scrubs_email(self):
        text = "Contact john.doe@example.com for details"
        result = scrub(text)
        assert "john.doe@example.com" not in result
        assert "EMAIL_REDACTED" in result

    def test_scrubs_us_phone(self):
        text = "Call us at 555-123-4567 anytime"
        result = scrub(text)
        assert "555-123-4567" not in result

    def test_scrubs_ssn(self):
        text = "SSN: 123-45-6789 on file"
        result = scrub(text)
        assert "123-45-6789" not in result
        assert "SSN_REDACTED" in result

    def test_preserves_non_pii_text(self):
        text = "Python developer with 5 years of AWS experience using Kubernetes"
        assert scrub(text) == text

    def test_empty_string_returns_empty(self):
        assert scrub("") == ""

    def test_multiple_pii_in_same_string(self):
        text = "Email: a@b.com, Phone: 555-999-1234"
        result = scrub(text)
        assert "a@b.com" not in result
        assert "555-999-1234" not in result


class TestScrubDict:
    def test_redacts_name_key(self):
        data = {"name": "John Doe", "score": 87}
        result = scrub_dict(data)
        assert result["name"] == "[REDACTED]"
        assert result["score"] == 87

    def test_redacts_email_key(self):
        data = {"email": "user@example.com", "title": "Engineer"}
        result = scrub_dict(data)
        assert result["email"] == "[REDACTED]"
        assert result["title"] == "Engineer"

    def test_scrubs_pii_in_string_values(self):
        data = {"message": "Contact jane@example.com for info"}
        result = scrub_dict(data)
        assert "jane@example.com" not in result["message"]

    def test_handles_nested_dicts(self):
        data = {"contact": {"email": "x@y.com", "phone": "555-111-2222"}}
        result = scrub_dict(data)
        assert result["contact"]["email"] == "[REDACTED]"

    def test_handles_list_of_strings(self):
        data = {"items": ["safe text", "email: test@test.com"]}
        result = scrub_dict(data)
        assert "test@test.com" not in result["items"][1]

    def test_handles_list_of_dicts(self):
        data = {"entries": [{"name": "Alice"}, {"name": "Bob"}]}
        result = scrub_dict(data)
        assert result["entries"][0]["name"] == "[REDACTED]"
        assert result["entries"][1]["name"] == "[REDACTED]"

    def test_non_string_scalars_unchanged(self):
        data = {"score": 87, "active": True, "count": None, "ratio": 0.75}
        result = scrub_dict(data)
        assert result["score"] == 87
        assert result["active"] is True
        assert result["count"] is None
        assert result["ratio"] == 0.75

    def test_api_key_redacted(self):
        data = {"api_key": "sk-ant-very-secret"}
        result = scrub_dict(data)
        assert result["api_key"] == "[REDACTED]"

    def test_custom_sensitive_keys(self):
        data = {"job_id": "dice_123", "secret_field": "top secret"}
        result = scrub_dict(data, sensitive_keys={"secret_field"})
        assert result["job_id"] == "dice_123"  # not in custom set or default set
        assert result["secret_field"] == "[REDACTED]"


class TestIsPiiFreePIIFree:
    def test_clean_text_is_pii_free(self):
        assert is_pii_free("Python developer with AWS experience") is True

    def test_email_is_not_pii_free(self):
        assert is_pii_free("Contact me at user@example.com") is False

    def test_phone_is_not_pii_free(self):
        assert is_pii_free("Call 555-123-4567") is False

    def test_ssn_is_not_pii_free(self):
        assert is_pii_free("SSN 123-45-6789") is False
