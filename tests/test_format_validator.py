"""Tests for utils/format_validator.py — resume and cover letter format checks."""
import pytest
from utils.format_validator import validate_resume, validate_cover_letter, SPELL_CHECK_AVAILABLE

VALID_RESUME = """
SUMMARY
Experienced software engineer with 8 years building scalable systems.

EXPERIENCE
Senior Software Engineer, TechCorp 2020-2026
- Led migration to Kubernetes reducing deployment time 60%
- Built microservices on AWS with Python and PostgreSQL

SOFTWARE ENGINEER, StartupCo 2018-2020
- Developed REST APIs using Django and Docker

EDUCATION
BS Computer Science, Test University 2018

SKILLS
Python, AWS, Kubernetes, PostgreSQL, Docker, REST, CI/CD
"""


class TestValidateResume:
    def test_valid_resume_passes(self):
        result = validate_resume(VALID_RESUME)
        assert result["passed"] is True
        assert result["error_count"] == 0

    def test_result_contains_required_keys(self):
        result = validate_resume(VALID_RESUME)
        assert "passed" in result
        assert "error_count" in result
        assert "warning_count" in result
        assert "issues" in result
        assert "word_count" in result
        assert "page_count" in result

    def test_missing_experience_section_is_error(self):
        resume = "SUMMARY\nSome professional.\n\nEDUCATION\nBS CS.\n\nSKILLS\nPython."
        result = validate_resume(resume)
        issue_types = [i["type"] for i in result["issues"]]
        assert "missing_section" in issue_types
        assert result["passed"] is False

    def test_missing_skills_section_is_error(self):
        resume = "SUMMARY\nText.\n\nEXPERIENCE\nSome job.\n\nEDUCATION\nBS."
        result = validate_resume(resume)
        issue_types = [i["type"] for i in result["issues"]]
        assert "missing_section" in issue_types

    def test_page_count_warning_at_3_pages(self):
        result = validate_resume(VALID_RESUME, page_count=3)
        types = [i["type"] for i in result["issues"]]
        assert "too_long" in types

    def test_word_count_is_positive(self):
        result = validate_resume(VALID_RESUME)
        assert result["word_count"] > 0

    def test_very_short_resume_gets_warning(self):
        short = "SUMMARY\nTen words. EXPERIENCE\nA job. EDUCATION\nBS. SKILLS\nPython."
        result = validate_resume(short)
        types = [i["type"] for i in result["issues"]]
        assert "too_short" in types

    def test_spell_check_field_present(self):
        result = validate_resume(VALID_RESUME)
        assert "spell_check_available" in result
        assert result["spell_check_available"] == SPELL_CHECK_AVAILABLE


class TestValidateCoverLetter:
    def test_valid_cover_letter_passes(self):
        text = " ".join(["word"] * 300)
        result = validate_cover_letter(text)
        assert result["passed"] is True
        assert result["error_count"] == 0

    def test_too_short_is_error(self):
        result = validate_cover_letter("Too short.")
        assert result["passed"] is False
        types = [i["type"] for i in result["issues"]]
        assert "too_short" in types

    def test_too_long_is_warning_not_error(self):
        text = " ".join(["word"] * 700)
        result = validate_cover_letter(text)
        # Too long is a warning, not an error — should still pass
        assert result["passed"] is True
        types = [i["type"] for i in result["issues"]]
        assert "too_long" in types
        assert result["warning_count"] > 0

    def test_generic_opener_detected(self):
        opener = "I am writing to express my interest in this role. "
        text = opener + " ".join(["word"] * 250)
        result = validate_cover_letter(text)
        types = [i["type"] for i in result["issues"]]
        assert "generic_opener" in types

    def test_second_bad_opener_detected(self):
        text = "I am writing to apply for this position. " + " ".join(["word"] * 250)
        result = validate_cover_letter(text)
        types = [i["type"] for i in result["issues"]]
        assert "generic_opener" in types

    def test_word_count_reported(self):
        words = ["word"] * 200
        result = validate_cover_letter(" ".join(words))
        assert result["word_count"] == 200

    def test_result_structure(self):
        result = validate_cover_letter(" ".join(["word"] * 250))
        assert "passed" in result
        assert "error_count" in result
        assert "warning_count" in result
        assert "issues" in result
        assert "word_count" in result
