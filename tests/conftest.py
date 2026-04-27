"""Shared pytest fixtures for JobSearchAgent tests."""
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_jd_dict() -> dict:
    return json.loads((FIXTURES_DIR / "sample_job_description.json").read_text())


@pytest.fixture
def sample_jd_text(sample_jd_dict) -> str:
    return sample_jd_dict["description"]


@pytest.fixture
def expected_profile() -> dict:
    return json.loads((FIXTURES_DIR / "expected_profile.json").read_text())


@pytest.fixture
def expected_ats() -> dict:
    return json.loads((FIXTURES_DIR / "expected_ats_result.json").read_text())


@pytest.fixture
def good_resume_text() -> str:
    return (
        "Senior Software Engineer with 8 years of experience.\n"
        "Expert in Python and AWS cloud services.\n"
        "Built REST APIs and microservices at scale.\n"
        "PostgreSQL database optimization and Redis caching.\n"
        "CI/CD pipelines using Jenkins and GitHub Actions.\n"
        "Led Kubernetes migration, reducing deployment time 60%.\n"
        "Docker containerization and Docker Compose.\n"
    )


@pytest.fixture
def minimal_config() -> dict:
    return {
        "gdpr": {"pii_in_logs": False, "consent_acknowledged": True},
        "paths": {"prompts_dir": "prompts", "logs_dir": "data/logs"},
        "llm": {"api_model": "claude-sonnet-4-6", "use_local_model": True},
        "quality": {"ats_target_coverage": 85, "max_auto_fix_retries": 2},
    }
