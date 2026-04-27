"""Tests for utils/ats_scanner.py — ATS keyword extraction and coverage scoring."""
import pytest
from utils.ats_scanner import extract_keywords, compute_coverage

SAMPLE_JD = """
We are looking for a Senior Software Engineer.

Requirements:
- 5+ years of Python experience
- Strong knowledge of AWS and Docker
- Experience with PostgreSQL and Redis
- REST API design and microservices architecture
- CI/CD pipeline experience with Jenkins or GitHub Actions
- Experience with Kubernetes

Preferred:
- Knowledge of GraphQL
- Familiarity with Terraform
- Experience with Kafka

About us: Great company.
"""

GOOD_RESUME = (
    "Senior Software Engineer with 8 years of experience. "
    "Expert in Python and AWS cloud services. "
    "Built REST APIs and microservices. "
    "PostgreSQL and Redis caching. "
    "CI/CD pipelines with Jenkins. "
    "Led Kubernetes migration. Docker containerization."
)


class TestExtractKeywords:
    def test_extracts_required_from_requirements_section(self):
        result = extract_keywords(SAMPLE_JD)
        req = result["required"]
        assert "python" in req
        assert "aws" in req
        assert "docker" in req

    def test_extracts_preferred_from_preferred_section(self):
        result = extract_keywords(SAMPLE_JD)
        all_kw = result["all"]
        # GraphQL and Terraform are in Preferred — should appear somewhere
        assert "graphql" in all_kw or "terraform" in all_kw

    def test_preferred_not_duplicated_in_required(self):
        result = extract_keywords(SAMPLE_JD)
        overlap = result["required"] & result["preferred"]
        assert overlap == set(), f"Overlap found: {overlap}"

    def test_all_is_union_of_required_and_preferred(self):
        result = extract_keywords(SAMPLE_JD)
        assert result["all"] == result["required"] | result["preferred"]

    def test_empty_jd_returns_empty_sets(self):
        result = extract_keywords("")
        assert result == {"required": set(), "preferred": set(), "all": set()}

    def test_jd_without_sections_extracts_from_full_text(self):
        jd = "Looking for Python and AWS experience."
        result = extract_keywords(jd)
        assert "python" in result["required"] or "python" in result["all"]


class TestComputeCoverage:
    def test_high_coverage_good_resume(self):
        kw = extract_keywords(SAMPLE_JD)
        result = compute_coverage(GOOD_RESUME, kw)
        assert result["coverage_percent"] >= 50.0

    def test_zero_coverage_empty_resume(self):
        kw = {"required": {"python", "aws"}, "preferred": set(), "all": {"python", "aws"}}
        result = compute_coverage("", kw)
        assert result["coverage_percent"] == 0.0

    def test_100_coverage_when_no_required_keywords(self):
        kw = {"required": set(), "preferred": set(), "all": set()}
        result = compute_coverage("any text", kw)
        assert result["coverage_percent"] == 100.0

    def test_matched_keywords_present_in_resume(self):
        kw = {"required": {"python", "terraform"}, "preferred": set(), "all": {"python", "terraform"}}
        result = compute_coverage("Python developer", kw)
        assert "python" in result["required"]["matched"]
        assert "terraform" in result["required"]["missing"]

    def test_coverage_percent_calculation(self):
        kw = {"required": {"python", "golang", "rust", "java"}, "preferred": set(), "all": {"python", "golang", "rust", "java"}}
        resume = "Expert Python developer with Golang experience"
        result = compute_coverage(resume, kw)
        assert result["required"]["matched_count"] == 2
        assert result["coverage_percent"] == 50.0

    def test_result_structure(self):
        kw = extract_keywords(SAMPLE_JD)
        result = compute_coverage(GOOD_RESUME, kw)
        assert "coverage_percent" in result
        assert "required" in result
        assert "preferred" in result
        assert "overall" in result
        assert "matched" in result["required"]
        assert "missing" in result["required"]
