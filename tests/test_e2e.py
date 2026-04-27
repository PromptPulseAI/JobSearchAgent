"""
Commit 11 — End-to-end and error-scenario tests.
These run the full Orchestrator pipeline with all agents mocked, covering:
  - dry-run completes cleanly
  - happy path: profile → scout → gate1 → writer → reviewer → tracker
  - all 11 error scenarios from the spec
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.exceptions import (
    AllSourcesFailedError,
    APIError,
    ConfigError,
    ConsentError,
    ProfileAgentError,
    TrackerAgentError,
    WriterAgentError,
)

# ── Shared helpers ────────────────────────────────────────────────────────────

VALID_CONFIG = {
    "gdpr": {"consent_acknowledged": True, "pii_in_logs": False},
    "paths": {
        "data_dir": "PLACEHOLDER",
        "prompts_dir": "prompts",
        "input_dir": "Input_Files",
        "skills_dir": "Skills",
        "logs_dir": "data/logs",
    },
    "llm": {
        "api_model": "claude-sonnet-4-6",
        "use_local_model": False,
        "api_params": {},
    },
    "rate_limit": {"max_concurrent_api_calls": 3, "delay_between_jobs_ms": 0},
    "quality": {"max_auto_fix_retries": 2},
    "scoring": {"thresholds": {"best_match": 75, "possible_match": 50}},
    "job_sources": {"active_sources": [], "sources": {}},
    "automation": {"headless_mode": False, "pending_approval_file": "data/pending_approval.json"},
    "candidate": {"seniority": ["senior"], "employment_types": ["full-time"]},
    "exclusions": {
        "security_clearance": True,
        "entry_level_junior": True,
        "companies_blacklist": [],
        "technologies_avoid": [],
    },
}

SAMPLE_JOB = {
    "job_id": "dice_e2e_001",
    "title": "Senior Engineer",
    "company": "E2ECorp",
    "location": "Remote",
    "score": 82,
    "url": "https://dice.com/e2e_001",
    "job_description": "Python. 5+ years.",
    "score_breakdown": {"reasoning": "Good match"},
}

SAMPLE_PROFILE = {
    "name": "Test User",
    "target_titles": ["Senior Engineer"],
    "years_experience": 8,
    "skills": {"technical": [{"name": "Python", "years": 8, "proficiency": "expert"}], "soft": [], "certifications": []},
    "industries": ["saas"],
    "keywords": ["Python"],
    "experience_summary": [],
    "education": [],
}

WRITER_OUTPUT = {
    "output_dir": "/tmp/e2e_output",
    "resume": "/tmp/e2e_output/resume.docx",
    "cover_letter": None,
    "interview_prep": None,
    "degraded": True,
}

REVIEW_PASS = {
    "passed": True,
    "score": 88,
    "review_pass": 1,
    "review_notes": "Good.",
    "fix_instructions": None,
    "issues": [],
}


def make_orc(tmp_path):
    from agents.orchestrator import Orchestrator
    cfg = {**VALID_CONFIG, "paths": {**VALID_CONFIG["paths"], "data_dir": str(tmp_path)}}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("utils.api_client.ClaudeClient.__init__", return_value=None):
            orc = Orchestrator(config_path=str(p), no_local_model=True)
    orc.claude = AsyncMock()
    orc.local = None
    return orc


# ── Dry-run ───────────────────────────────────────────────────────────────────

class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_completes_without_exceptions(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.dry_run = True
        with patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

    @pytest.mark.asyncio
    async def test_dry_run_makes_no_api_calls(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.dry_run = True
        with patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()
        orc.claude.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_calls_end_of_run_tracker(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.dry_run = True
        tracker_calls = []
        with patch.object(orc, "_run_tracker", new=AsyncMock(side_effect=lambda a, **kw: tracker_calls.append(a))):
            await orc.run()
        assert "end_of_run" in tracker_calls


# ── Happy path ────────────────────────────────────────────────────────────────

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_pipeline_single_job(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[SAMPLE_JOB])), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=True)), \
             patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

    @pytest.mark.asyncio
    async def test_run_summary_counts_completed_jobs(self, tmp_path):
        orc = make_orc(tmp_path)
        captured_summary = {}

        async def capture_tracker(action, run_summary=None, **kwargs):
            if action == "end_of_run" and run_summary:
                captured_summary.update(run_summary)

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[SAMPLE_JOB])), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=True)), \
             patch.object(orc, "_run_tracker", side_effect=capture_tracker):
            await orc.run()

        assert captured_summary.get("jobs_completed") == 1
        assert captured_summary.get("jobs_approved") == 1

    @pytest.mark.asyncio
    async def test_gate2_no_counts_as_skipped(self, tmp_path):
        orc = make_orc(tmp_path)
        captured = {}

        async def capture_tracker(action, run_summary=None, **kwargs):
            if action == "end_of_run" and run_summary:
                captured.update(run_summary)

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[SAMPLE_JOB])), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=False)), \
             patch.object(orc, "_run_tracker", side_effect=capture_tracker):
            await orc.run()

        assert captured.get("jobs_skipped") == 1
        assert captured.get("jobs_completed") == 0

    @pytest.mark.asyncio
    async def test_target_job_id_filters_to_single_job(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.target_job_id = "dice_e2e_001"
        job2 = {**SAMPLE_JOB, "job_id": "dice_other_999"}

        gate1_received = {}

        async def capture_gate1(all_jobs, job_matches):
            gate1_received["jobs"] = all_jobs
            return []

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB, job2], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", side_effect=capture_gate1), \
             patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

        assert len(gate1_received["jobs"]) == 1
        assert gate1_received["jobs"][0]["job_id"] == "dice_e2e_001"


# ── Error scenarios ───────────────────────────────────────────────────────────

class TestErrorScenarios:
    # E1: Profile agent fails → abort entire run
    @pytest.mark.asyncio
    async def test_profile_failure_aborts_run(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(side_effect=ProfileAgentError("no resume"))):
            with pytest.raises(ProfileAgentError):
                await orc.run()

    # E2: GDPR consent not set → ConsentError at init
    def test_no_consent_raises_consent_error(self, tmp_path):
        from agents.orchestrator import Orchestrator
        cfg = {**VALID_CONFIG, "gdpr": {"consent_acknowledged": False}}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("utils.api_client.ClaudeClient.__init__", return_value=None):
                with pytest.raises(ConsentError):
                    Orchestrator(config_path=str(p), no_local_model=True)

    # E3: Missing config.json → ConfigError at init
    def test_missing_config_raises_config_error(self, tmp_path):
        from agents.orchestrator import Orchestrator
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with pytest.raises(ConfigError, match="not found"):
                Orchestrator(config_path=str(tmp_path / "nonexistent.json"))

    # E4: Missing ANTHROPIC_API_KEY → ConfigError
    def test_missing_api_key_raises_config_error(self, tmp_path):
        from agents.orchestrator import Orchestrator
        p = tmp_path / "config.json"
        p.write_text(json.dumps(VALID_CONFIG))
        with patch.dict("os.environ", {}, clear=True):
            if "ANTHROPIC_API_KEY" in __import__("os").environ:
                return
            with patch("utils.api_client.ClaudeClient.__init__", side_effect=ConfigError("no key")):
                with pytest.raises(ConfigError):
                    Orchestrator(config_path=str(p), no_local_model=True)

    # E5: All job sources fail → handled gracefully, tracker still called
    @pytest.mark.asyncio
    async def test_all_sources_failed_calls_end_of_run(self, tmp_path):
        orc = make_orc(tmp_path)
        tracker_calls = []
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(side_effect=AllSourcesFailedError("all down"))), \
             patch.object(orc, "_run_tracker", new=AsyncMock(side_effect=lambda a, **kw: tracker_calls.append(a))):
            await orc.run()  # must NOT re-raise
        assert "end_of_run" in tracker_calls

    # E6: Single writer failure → job rejected, run continues
    @pytest.mark.asyncio
    async def test_writer_failure_continues_other_jobs(self, tmp_path):
        orc = make_orc(tmp_path)
        job2 = {**SAMPLE_JOB, "job_id": "dice_002", "title": "Staff Eng"}
        fix_loop_calls = []

        async def mock_fix_loop(job, profile):
            fix_loop_calls.append(job["job_id"])
            if job["job_id"] == "dice_e2e_001":
                raise WriterAgentError("Lane A failed")
            return WRITER_OUTPUT

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB, job2], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[SAMPLE_JOB, job2])), \
             patch.object(orc, "_fix_loop", side_effect=mock_fix_loop), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=True)), \
             patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

        assert len(fix_loop_calls) == 2

    # E7: Tracker failure does not crash the run
    @pytest.mark.asyncio
    async def test_tracker_failure_does_not_crash(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[])), \
             patch("agents.tracker_agent.TrackerAgent.run", new=AsyncMock(side_effect=TrackerAgentError("disk full"))):
            await orc.run()  # must not re-raise

    # E8: Gate 1 approves zero jobs → pipeline ends gracefully
    @pytest.mark.asyncio
    async def test_gate1_zero_approved_ends_gracefully(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[])), \
             patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

    # E9: skip-search loads existing job_matches.json
    @pytest.mark.asyncio
    async def test_skip_search_loads_existing_matches(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.skip_search = True
        matches = {"best_match": [SAMPLE_JOB], "possible_match": [], "not_matching": []}
        (tmp_path / "job_matches.json").write_text(json.dumps(matches))

        gate1_received = {}

        async def capture_gate1(all_jobs, job_matches):
            gate1_received["count"] = len(all_jobs)
            return []

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_gate1", side_effect=capture_gate1), \
             patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

        assert gate1_received.get("count") == 1

    # E10: skip-search with no existing file → empty matches
    @pytest.mark.asyncio
    async def test_skip_search_no_file_means_zero_jobs(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.skip_search = True

        gate1_received = {}

        async def capture_gate1(all_jobs, job_matches):
            gate1_received["count"] = len(all_jobs)
            return []

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_gate1", side_effect=capture_gate1), \
             patch.object(orc, "_run_tracker", new=AsyncMock()):
            await orc.run()

        assert gate1_received.get("count", 0) == 0

    # E11: Rate limit on API → RateLimitError propagates from writer (not silenced)
    @pytest.mark.asyncio
    async def test_rate_limit_error_from_writer_recorded_as_failure(self, tmp_path):
        from utils.exceptions import RateLimitError
        orc = make_orc(tmp_path)
        tracker_statuses = []

        async def capture_tracker(action, job=None, status=None, **kwargs):
            if status:
                tracker_statuses.append(status)

        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value=SAMPLE_PROFILE)), \
             patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [SAMPLE_JOB], "possible_match": [], "not_matching": []})), \
             patch.object(orc, "_gate1", new=AsyncMock(return_value=[SAMPLE_JOB])), \
             patch.object(orc, "_fix_loop", new=AsyncMock(side_effect=RateLimitError("429 too many requests"))), \
             patch.object(orc, "_run_tracker", side_effect=capture_tracker):
            await orc.run()

        assert "Rejected" in tracker_statuses
