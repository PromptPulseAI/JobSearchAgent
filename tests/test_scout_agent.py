"""Tests for agents/scout_agent.py — scoring, dedup, exclusion, grouping."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.scout_agent import (
    _apply_exclusions,
    _apply_freshness_boost,
    _group_by_tier,
    _load_seen_job_ids,
    _parse_score_response,
    _build_scoring_message,
)
from utils.exceptions import AllSourcesFailedError


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_JOB = {
    "job_id": "dice_001",
    "source": "dice",
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "location": "Remote",
    "date_posted": "2026-04-26",
    "job_description": "Python, AWS, Kubernetes, REST APIs, microservices. 5+ years required.",
    "employment_type": "full-time",
    "url": "https://dice.com/jobs/001",
    "company_context": {},
    "score": 0,
}

SAMPLE_PROFILE = {
    "name": "Test User",
    "target_titles": ["Senior Software Engineer", "Lead Engineer"],
    "years_experience": 8,
    "skills": {
        "technical": [
            {"name": "Python", "years": 8, "proficiency": "expert"},
            {"name": "AWS", "years": 5, "proficiency": "advanced"},
            {"name": "Kubernetes", "years": 3, "proficiency": "intermediate"},
        ],
        "soft": [],
        "certifications": [],
    },
    "industries": ["fintech", "saas"],
    "keywords": ["microservices", "REST API", "CI/CD"],
}

VALID_SCORE_JSON = {
    "core_skills_match": 85,
    "title_seniority_alignment": 90,
    "industry_domain_fit": 70,
    "years_experience_fit": 95,
    "nice_to_have_skills": 60,
    "company_culture_signals": 75,
    "reasoning": "Strong Python/AWS match, right seniority level.",
}

CONFIG = {
    "paths": {"data_dir": "data", "prompts_dir": "prompts"},
    "scoring": {
        "weights": {
            "core_skills_match": 0.35,
            "title_seniority_alignment": 0.20,
            "industry_domain_fit": 0.15,
            "years_experience_fit": 0.15,
            "nice_to_have_skills": 0.10,
            "company_culture_signals": 0.05,
        },
        "thresholds": {"best_match": 75, "possible_match": 50},
    },
    "exclusions": {
        "security_clearance": True,
        "entry_level_junior": True,
        "companies_blacklist": [],
        "technologies_avoid": [],
    },
    "job_sources": {"active_sources": [], "sources": {}},
}


# ── _parse_score_response ─────────────────────────────────────────────────────

class TestParseScoreResponse:
    def test_parses_valid_json(self):
        result = _parse_score_response(json.dumps(VALID_SCORE_JSON))
        assert result["core_skills_match"] == 85
        assert result["title_seniority_alignment"] == 90

    def test_parses_json_in_code_fence(self):
        raw = f"```json\n{json.dumps(VALID_SCORE_JSON)}\n```"
        result = _parse_score_response(raw)
        assert result["core_skills_match"] == 85

    def test_returns_zeros_on_invalid_json(self):
        result = _parse_score_response("not json")
        assert result["core_skills_match"] == 0
        assert result["title_seniority_alignment"] == 0

    def test_clamps_scores_to_100(self):
        data = {**VALID_SCORE_JSON, "core_skills_match": 150}
        result = _parse_score_response(json.dumps(data))
        assert result["core_skills_match"] == 100

    def test_clamps_scores_to_zero(self):
        data = {**VALID_SCORE_JSON, "core_skills_match": -10}
        result = _parse_score_response(json.dumps(data))
        assert result["core_skills_match"] == 0


# ── _apply_exclusions ─────────────────────────────────────────────────────────

class TestApplyExclusions:
    def test_excludes_clearance_jobs(self):
        job = {**SAMPLE_JOB, "job_description": "Requires active security clearance TS/SCI"}
        kept, count = _apply_exclusions([job], {"security_clearance": True, "entry_level_junior": False, "companies_blacklist": [], "technologies_avoid": []})
        assert count == 1
        assert kept == []

    def test_keeps_clearance_jobs_when_filter_disabled(self):
        job = {**SAMPLE_JOB, "job_description": "Requires security clearance"}
        kept, count = _apply_exclusions([job], {"security_clearance": False, "entry_level_junior": False, "companies_blacklist": [], "technologies_avoid": []})
        assert count == 0
        assert len(kept) == 1

    def test_excludes_junior_jobs(self):
        job = {**SAMPLE_JOB, "title": "Junior Software Engineer"}
        kept, count = _apply_exclusions([job], {"security_clearance": False, "entry_level_junior": True, "companies_blacklist": [], "technologies_avoid": []})
        assert count == 1

    def test_excludes_entry_level_jobs(self):
        job = {**SAMPLE_JOB, "job_description": "Entry-level position, 0-2 years experience"}
        kept, count = _apply_exclusions([job], {"security_clearance": False, "entry_level_junior": True, "companies_blacklist": [], "technologies_avoid": []})
        assert count == 1

    def test_excludes_blacklisted_company(self):
        job = {**SAMPLE_JOB, "company": "BadCorp"}
        kept, count = _apply_exclusions([job], {"security_clearance": False, "entry_level_junior": False, "companies_blacklist": ["BadCorp"], "technologies_avoid": []})
        assert count == 1

    def test_excludes_avoided_technology(self):
        job = {**SAMPLE_JOB, "job_description": "Heavy PHP and legacy COBOL codebase"}
        kept, count = _apply_exclusions([job], {"security_clearance": False, "entry_level_junior": False, "companies_blacklist": [], "technologies_avoid": ["cobol"]})
        assert count == 1

    def test_keeps_clean_job(self):
        kept, count = _apply_exclusions([SAMPLE_JOB], {"security_clearance": True, "entry_level_junior": True, "companies_blacklist": [], "technologies_avoid": []})
        assert count == 0
        assert len(kept) == 1


# ── _apply_freshness_boost ────────────────────────────────────────────────────

class TestApplyFreshnessBoost:
    def test_adds_5_for_job_posted_today(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        job = {**SAMPLE_JOB, "score": 70, "date_posted": today}
        result = _apply_freshness_boost(job)
        assert result["score"] == 75
        assert result["freshness_boost"] == 5

    def test_adds_2_for_job_posted_5_days_ago(self):
        from datetime import datetime, timezone, timedelta
        five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
        job = {**SAMPLE_JOB, "score": 70, "date_posted": five_days_ago}
        result = _apply_freshness_boost(job)
        assert result["score"] == 72
        assert result["freshness_boost"] == 2

    def test_no_boost_for_old_job(self):
        job = {**SAMPLE_JOB, "score": 70, "date_posted": "2026-01-01"}
        result = _apply_freshness_boost(job)
        assert result["score"] == 70
        assert "freshness_boost" not in result

    def test_no_boost_when_date_missing(self):
        job = {**SAMPLE_JOB, "score": 70, "date_posted": ""}
        result = _apply_freshness_boost(job)
        assert result["score"] == 70

    def test_score_capped_at_100(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        job = {**SAMPLE_JOB, "score": 98, "date_posted": today}
        result = _apply_freshness_boost(job)
        assert result["score"] == 100


# ── _group_by_tier ────────────────────────────────────────────────────────────

class TestGroupByTier:
    def test_best_match_at_or_above_threshold(self):
        jobs = [{**SAMPLE_JOB, "score": 80}, {**SAMPLE_JOB, "score": 75}]
        result = _group_by_tier(jobs, best_threshold=75, possible_threshold=50)
        assert len(result["best_match"]) == 2

    def test_possible_match_between_thresholds(self):
        jobs = [{**SAMPLE_JOB, "score": 60}]
        result = _group_by_tier(jobs, best_threshold=75, possible_threshold=50)
        assert len(result["possible_match"]) == 1

    def test_not_matching_below_possible_threshold(self):
        jobs = [{**SAMPLE_JOB, "score": 30}]
        result = _group_by_tier(jobs, best_threshold=75, possible_threshold=50)
        assert len(result["not_matching"]) == 1

    def test_empty_input_returns_empty_groups(self):
        result = _group_by_tier([], 75, 50)
        assert result == {"best_match": [], "possible_match": [], "not_matching": []}


# ── _load_seen_job_ids ────────────────────────────────────────────────────────

class TestLoadSeenJobIds:
    def test_returns_empty_set_when_file_missing(self, tmp_path):
        result = _load_seen_job_ids(tmp_path / "nonexistent.json")
        assert result == set()

    def test_returns_job_ids_from_tracker(self, tmp_path):
        tracker = {"jobs": [{"job_id": "dice_001"}, {"job_id": "dice_002"}]}
        p = tmp_path / "application_tracker.json"
        p.write_text(json.dumps(tracker))
        result = _load_seen_job_ids(p)
        assert "dice_001" in result
        assert "dice_002" in result

    def test_skips_entries_without_job_id(self, tmp_path):
        tracker = {"jobs": [{"job_id": "dice_001"}, {"title": "no id"}]}
        p = tmp_path / "application_tracker.json"
        p.write_text(json.dumps(tracker))
        result = _load_seen_job_ids(p)
        assert len(result) == 1


# ── _build_scoring_message ────────────────────────────────────────────────────

class TestBuildScoringMessage:
    def test_includes_job_title(self):
        msg = _build_scoring_message(SAMPLE_JOB, SAMPLE_PROFILE)
        assert "Senior Software Engineer" in msg

    def test_includes_candidate_skills(self):
        msg = _build_scoring_message(SAMPLE_JOB, SAMPLE_PROFILE)
        assert "Python" in msg

    def test_truncates_long_job_description(self):
        long_job = {**SAMPLE_JOB, "job_description": "x" * 5000}
        msg = _build_scoring_message(long_job, SAMPLE_PROFILE)
        # 2000 char limit on description portion
        assert len(msg) < 4000


# ── ScoutAgent.run() integration ──────────────────────────────────────────────

class TestScoutAgentRun:
    @pytest.fixture
    def agent(self, tmp_path):
        from agents.scout_agent import ScoutAgent
        cfg = {**CONFIG, "paths": {**CONFIG["paths"], "data_dir": str(tmp_path)}}
        local_mock = MagicMock()
        local_mock.generate = AsyncMock(return_value=json.dumps(VALID_SCORE_JSON))
        return ScoutAgent(config=cfg, local_llm=local_mock)

    async def test_run_writes_job_matches_file(self, agent, tmp_path):
        mock_jobs = [{**SAMPLE_JOB}]

        with patch("agents.scout_agent.SourceRegistry") as MockReg:
            mock_source = AsyncMock()
            mock_source.source_name = "Dice"
            mock_source.source_id = "dice"
            mock_source.search_jobs = AsyncMock(return_value=mock_jobs)
            MockReg.return_value.active_sources = [mock_source]

            with patch.object(agent, "load_prompt", return_value="scoring prompt"):
                result = await agent.run(SAMPLE_PROFILE)

        assert (tmp_path / "job_matches.json").exists()
        assert "best_match" in result
        assert "possible_match" in result
        assert "not_matching" in result

    async def test_run_deduplicates_against_tracker(self, agent, tmp_path):
        tracker = {"jobs": [{"job_id": "dice_001"}]}
        (tmp_path / "application_tracker.json").write_text(json.dumps(tracker))

        with patch("agents.scout_agent.SourceRegistry") as MockReg:
            mock_source = AsyncMock()
            mock_source.source_name = "Dice"
            mock_source.source_id = "dice"
            mock_source.search_jobs = AsyncMock(return_value=[{**SAMPLE_JOB}])
            MockReg.return_value.active_sources = [mock_source]

            with patch.object(agent, "load_prompt", return_value="prompt"):
                result = await agent.run(SAMPLE_PROFILE)

        total = sum(len(v) for v in result.values())
        assert total == 0  # dice_001 was already in tracker

    async def test_raises_when_all_sources_fail(self, agent):
        with patch("agents.scout_agent.SourceRegistry") as MockReg:
            mock_source = AsyncMock()
            mock_source.source_name = "Dice"
            mock_source.source_id = "dice"
            from utils.exceptions import JobSourceError
            mock_source.search_jobs = AsyncMock(side_effect=JobSourceError("down", source_id="dice"))
            MockReg.return_value.active_sources = [mock_source]

            with patch.object(agent, "load_prompt", return_value="prompt"):
                with pytest.raises(AllSourcesFailedError):
                    await agent.run(SAMPLE_PROFILE)
