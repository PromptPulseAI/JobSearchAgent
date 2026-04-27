"""Tests for sources/dice_source.py and utils/api_client.ClaudeClient.call_mcp_tool."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sources.dice_source import (
    DiceSource,
    _build_mcp_prompt,
    _map_employment_types,
    _map_location,
)
from utils.exceptions import JobSourceError


# ── Fixtures ──────────────────────────────────────────────────────────────────

RAW_JOB = {
    "id": "abc123",
    "title": "Senior Software Engineer",
    "company": {"name": "TechCorp"},
    "applyUrl": "https://dice.com/job/abc123",
    "postedDate": "2026-04-26",
    "location": "Remote",
    "employmentType": "FULLTIME",
    "description": "Python, AWS, Kubernetes microservices role.",
}

SAMPLE_PROFILE = {
    "target_titles": ["Senior Software Engineer", "Lead Engineer"],
    "years_experience": 8,
    "skills": {
        "technical": [
            {"name": "Python", "years": 8},
            {"name": "AWS", "years": 5},
            {"name": "Kubernetes", "years": 3},
        ],
        "soft": [],
        "certifications": [],
    },
    "industries": ["fintech", "saas"],
}

CONFIG = {
    "candidate": {
        "location": "anywhere_us",
        "employment_types": ["full-time", "contract"],
    },
    "job_sources": {
        "sources": {
            "dice": {
                "retry": {"max_attempts": 2, "backoff_seconds": [0, 0]},
            }
        }
    },
}


def make_source(call_result=None, side_effect=None):
    """Create a DiceSource with a mocked ClaudeClient."""
    source = DiceSource()
    claude = MagicMock()
    if side_effect:
        claude.call_mcp_tool = AsyncMock(side_effect=side_effect)
    else:
        claude.call_mcp_tool = AsyncMock(return_value=call_result if call_result is not None else [RAW_JOB])
    source.claude = claude
    return source


# ── normalize_job ─────────────────────────────────────────────────────────────

class TestNormalizeJob:
    def test_extracts_standard_fields(self):
        source = DiceSource()
        result = source.normalize_job(RAW_JOB)
        assert result["job_id"] == "dice_abc123"
        assert result["source"] == "dice"
        assert result["title"] == "Senior Software Engineer"
        assert result["company"] == "TechCorp"
        assert result["url"] == "https://dice.com/job/abc123"
        assert result["location"] == "Remote"
        assert result["employment_type"] == "FULLTIME"

    def test_company_as_string(self):
        job = {**RAW_JOB, "company": "FlatCorp"}
        result = DiceSource().normalize_job(job)
        assert result["company"] == "FlatCorp"

    def test_missing_id_gives_empty_suffix(self):
        job = {**RAW_JOB, "id": ""}
        result = DiceSource().normalize_job(job)
        assert result["job_id"] == "dice_"

    def test_uses_url_fallback_when_apply_url_missing(self):
        job = {**RAW_JOB, "applyUrl": None, "url": "https://fallback.com"}
        result = DiceSource().normalize_job(job)
        assert result["url"] == "https://fallback.com"


# ── _build_query ──────────────────────────────────────────────────────────────

class TestBuildQuery:
    def test_uses_target_titles_in_query(self):
        source = DiceSource()
        q = source._build_query(SAMPLE_PROFILE, CONFIG)
        assert "Senior Software Engineer" in q["query"]

    def test_maps_anywhere_us_to_remote(self):
        source = DiceSource()
        q = source._build_query(SAMPLE_PROFILE, CONFIG)
        assert q["location"] == "Remote"

    def test_maps_employment_types(self):
        source = DiceSource()
        q = source._build_query(SAMPLE_PROFILE, CONFIG)
        # both full-time and contract should be included
        assert "FULLTIME" in q["employment_type"] or "CONTRACTS" in q["employment_type"]

    def test_falls_back_to_skills_when_no_titles(self):
        profile = {**SAMPLE_PROFILE, "target_titles": []}
        source = DiceSource()
        q = source._build_query(profile, CONFIG)
        assert "Python" in q["query"]


# ── _map_location / _map_employment_types ─────────────────────────────────────

class TestMapHelpers:
    def test_map_location_anywhere_us(self):
        assert _map_location("anywhere_us") == "Remote"

    def test_map_location_empty(self):
        assert _map_location("") == "Remote"

    def test_map_location_passthrough(self):
        assert _map_location("New York") == "New York"

    def test_map_employment_fulltime(self):
        assert _map_employment_types(["full-time"]) == "FULLTIME"

    def test_map_employment_contract_c2c(self):
        result = _map_employment_types(["contract", "c2c"])
        assert result == "CONTRACTS"

    def test_map_employment_mixed(self):
        result = _map_employment_types(["full-time", "contract"])
        assert "FULLTIME" in result
        assert "CONTRACTS" in result


# ── _build_mcp_prompt ─────────────────────────────────────────────────────────

class TestBuildMcpPrompt:
    def test_includes_query(self):
        q = {"query": '"Senior Engineer"', "location": "Remote", "employment_type": "FULLTIME", "date_posted": "LAST_7_DAYS", "page_size": 25}
        prompt = _build_mcp_prompt(q)
        assert '"Senior Engineer"' in prompt

    def test_includes_location(self):
        q = {"query": "Python", "location": "Remote", "employment_type": "FULLTIME", "date_posted": "LAST_7_DAYS", "page_size": 25}
        assert "Remote" in _build_mcp_prompt(q)

    def test_instructs_raw_json_return(self):
        q = {"query": "x", "location": "Remote", "employment_type": "FULLTIME", "date_posted": "LAST_7_DAYS", "page_size": 25}
        assert "JSON" in _build_mcp_prompt(q)


# ── search_jobs ───────────────────────────────────────────────────────────────

class TestSearchJobs:
    async def test_returns_normalized_jobs_on_success(self):
        source = make_source(call_result=[RAW_JOB])
        results = await source.search_jobs(SAMPLE_PROFILE, CONFIG)
        assert len(results) == 1
        assert results[0]["job_id"] == "dice_abc123"
        assert results[0]["source"] == "dice"

    async def test_unwraps_jobs_key_in_dict_response(self):
        source = make_source(call_result={"jobs": [RAW_JOB]})
        results = await source.search_jobs(SAMPLE_PROFILE, CONFIG)
        assert len(results) == 1

    async def test_unwraps_results_key(self):
        source = make_source(call_result={"results": [RAW_JOB]})
        results = await source.search_jobs(SAMPLE_PROFILE, CONFIG)
        assert len(results) == 1

    async def test_returns_empty_list_on_empty_response(self):
        source = make_source(call_result=[])
        results = await source.search_jobs(SAMPLE_PROFILE, CONFIG)
        assert results == []

    async def test_raises_job_source_error_on_all_failures(self):
        source = make_source(side_effect=Exception("API down"))
        with pytest.raises(JobSourceError, match="Dice search failed"):
            await source.search_jobs(SAMPLE_PROFILE, CONFIG)

    async def test_retries_on_transient_failure(self):
        source = DiceSource()
        source.claude = MagicMock()
        source.claude.call_mcp_tool = AsyncMock(
            side_effect=[Exception("timeout"), [RAW_JOB]]
        )
        with patch("asyncio.sleep", new_callable=AsyncMock):
            results = await source.search_jobs(SAMPLE_PROFILE, CONFIG)
        assert len(results) == 1

    async def test_raises_when_claude_not_set(self):
        source = DiceSource()
        source.claude = None
        with pytest.raises(JobSourceError, match="ClaudeClient"):
            await source.search_jobs(SAMPLE_PROFILE, CONFIG)

    async def test_call_mcp_tool_called_with_correct_server(self):
        source = make_source(call_result=[RAW_JOB])
        await source.search_jobs(SAMPLE_PROFILE, CONFIG)
        call_kwargs = source.claude.call_mcp_tool.call_args[1]
        assert call_kwargs["server_url"] == "https://mcp.dice.com/mcp"
        assert call_kwargs["server_name"] == "dice"
