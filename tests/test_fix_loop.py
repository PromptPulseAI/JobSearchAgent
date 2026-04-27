"""
Commit 9 integration tests — fix loop (_fix_loop, _process_job, _gate2).
Tests the Writer → Reviewer → fix cycle end-to-end using mocked agents.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.exceptions import WriterAgentError


# ── Shared fixtures ───────────────────────────────────────────────────────────

VALID_CONFIG = {
    "gdpr": {"consent_acknowledged": True, "pii_in_logs": False},
    "paths": {
        "data_dir": "data",
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
    "exclusions": {"security_clearance": True, "entry_level_junior": True, "companies_blacklist": [], "technologies_avoid": []},
}

SAMPLE_JOB = {
    "job_id": "dice_001",
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "location": "Remote",
    "score": 82,
    "url": "https://dice.com/001",
    "job_description": "Python, AWS, Kubernetes.",
    "score_breakdown": {"reasoning": "Strong match."},
}

WRITER_OUTPUT = {
    "output_dir": "/tmp/output",
    "resume": "/tmp/output/tailored_resume.docx",
    "cover_letter": "/tmp/output/cover_letter.docx",
    "interview_prep": "/tmp/output/interview_prep.md",
    "degraded": False,
}

REVIEW_PASS = {
    "passed": True,
    "score": 88,
    "review_pass": 1,
    "review_notes": "Strong resume.",
    "fix_instructions": None,
    "issues": [],
}

REVIEW_FAIL = {
    "passed": False,
    "score": 62,
    "review_pass": 1,
    "review_notes": "ATS keywords missing.",
    "fix_instructions": {"resume_fixes": [{"location": "skills", "issue": "Missing Python", "fix": "Add it"}]},
    "issues": [{"severity": "error", "location": "skills", "issue": "Missing keyword", "fix": "Add Python"}],
}


def make_orc(tmp_path, extra_config=None):
    from agents.orchestrator import Orchestrator
    cfg = {**VALID_CONFIG, "paths": {**VALID_CONFIG["paths"], "data_dir": str(tmp_path)}}
    if extra_config:
        cfg.update(extra_config)
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("utils.api_client.ClaudeClient.__init__", return_value=None):
            orc = Orchestrator(config_path=str(p), no_local_model=True)
    orc.local = None
    orc.claude = AsyncMock()
    return orc


# ── _fix_loop tests ───────────────────────────────────────────────────────────

class TestFixLoop:
    @pytest.mark.asyncio
    async def test_passes_on_first_try(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch("agents.writer_agent.WriterAgent.run", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=AsyncMock(return_value=REVIEW_PASS)):
            result = await orc._fix_loop(SAMPLE_JOB, {})
        assert result == WRITER_OUTPUT

    @pytest.mark.asyncio
    async def test_calls_writer_once_when_review_passes(self, tmp_path):
        orc = make_orc(tmp_path)
        mock_writer = AsyncMock(return_value=WRITER_OUTPUT)
        mock_reviewer = AsyncMock(return_value=REVIEW_PASS)
        with patch("agents.writer_agent.WriterAgent.run", new=mock_writer), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=mock_reviewer):
            await orc._fix_loop(SAMPLE_JOB, {})
        mock_writer.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_once_on_first_fail(self, tmp_path):
        orc = make_orc(tmp_path)
        review_responses = [REVIEW_FAIL, REVIEW_PASS]
        mock_writer = AsyncMock(return_value=WRITER_OUTPUT)
        mock_reviewer = AsyncMock(side_effect=review_responses)
        with patch("agents.writer_agent.WriterAgent.run", new=mock_writer), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=mock_reviewer):
            result = await orc._fix_loop(SAMPLE_JOB, {})
        assert mock_writer.call_count == 2
        assert result == WRITER_OUTPUT

    @pytest.mark.asyncio
    async def test_passes_fix_instructions_to_writer_on_retry(self, tmp_path):
        orc = make_orc(tmp_path)
        review_responses = [REVIEW_FAIL, REVIEW_PASS]
        captured_calls = []

        async def capture_writer(*args, **kwargs):
            captured_calls.append(kwargs.get("fix_instructions"))
            return WRITER_OUTPUT

        with patch("agents.writer_agent.WriterAgent.run", new=capture_writer), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=AsyncMock(side_effect=review_responses)):
            await orc._fix_loop(SAMPLE_JOB, {})

        assert captured_calls[0] is None  # first call: no fixes
        assert captured_calls[1] == REVIEW_FAIL["fix_instructions"]  # second call: fixes applied

    @pytest.mark.asyncio
    async def test_accepts_output_at_max_retries(self, tmp_path):
        """After max_retries (2), accept result even if still failing."""
        orc = make_orc(tmp_path)
        mock_writer = AsyncMock(return_value=WRITER_OUTPUT)
        mock_reviewer = AsyncMock(return_value=REVIEW_FAIL)
        with patch("agents.writer_agent.WriterAgent.run", new=mock_writer), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=mock_reviewer):
            result = await orc._fix_loop(SAMPLE_JOB, {})
        assert result == WRITER_OUTPUT
        assert mock_writer.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_dry_run_skips_writer_and_reviewer(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.dry_run = True
        mock_writer = AsyncMock(return_value=WRITER_OUTPUT)
        mock_reviewer = AsyncMock(return_value=REVIEW_PASS)
        with patch("agents.writer_agent.WriterAgent.run", new=mock_writer), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=mock_reviewer):
            result = await orc._fix_loop(SAMPLE_JOB, {})
        mock_writer.assert_not_called()
        mock_reviewer.assert_not_called()
        assert result["output_dir"] == "dry_run"

    @pytest.mark.asyncio
    async def test_not_implemented_writer_returns_gracefully(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch("agents.writer_agent.WriterAgent.run", new=AsyncMock(side_effect=NotImplementedError)):
            result = await orc._fix_loop(SAMPLE_JOB, {})
        assert result["output_dir"] == "not_implemented"

    @pytest.mark.asyncio
    async def test_not_implemented_reviewer_returns_writer_output(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch("agents.writer_agent.WriterAgent.run", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=AsyncMock(side_effect=NotImplementedError)):
            result = await orc._fix_loop(SAMPLE_JOB, {})
        assert result == WRITER_OUTPUT

    @pytest.mark.asyncio
    async def test_max_retries_from_config(self, tmp_path):
        """max_auto_fix_retries=1 means 1 initial + 1 retry = 2 total writer calls."""
        cfg_override = {"quality": {"max_auto_fix_retries": 1}}
        orc = make_orc(tmp_path, extra_config=cfg_override)
        mock_writer = AsyncMock(return_value=WRITER_OUTPUT)
        with patch("agents.writer_agent.WriterAgent.run", new=mock_writer), \
             patch("agents.reviewer_agent.ReviewerAgent.run", new=AsyncMock(return_value=REVIEW_FAIL)):
            await orc._fix_loop(SAMPLE_JOB, {})
        assert mock_writer.call_count == 2


# ── _gate2 tests ──────────────────────────────────────────────────────────────

class TestGate2:
    @pytest.mark.asyncio
    async def test_yes_input_returns_true(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch("builtins.input", return_value="y"):
            result = await orc._gate2(SAMPLE_JOB, WRITER_OUTPUT)
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_input_defaults_to_yes(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch("builtins.input", return_value=""):
            result = await orc._gate2(SAMPLE_JOB, WRITER_OUTPUT)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_input_returns_false(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch("builtins.input", return_value="n"):
            result = await orc._gate2(SAMPLE_JOB, WRITER_OUTPUT)
        assert result is False

    @pytest.mark.asyncio
    async def test_dry_run_always_true(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.dry_run = True
        result = await orc._gate2(SAMPLE_JOB, WRITER_OUTPUT)
        assert result is True

    @pytest.mark.asyncio
    async def test_skip_gate1_flag_always_true(self, tmp_path):
        orc = make_orc(tmp_path)
        orc.skip_gate1_if_no_new = True
        result = await orc._gate2(SAMPLE_JOB, WRITER_OUTPUT)
        assert result is True

    @pytest.mark.asyncio
    async def test_prints_job_info(self, tmp_path, capsys):
        orc = make_orc(tmp_path)
        with patch("builtins.input", return_value="y"):
            await orc._gate2(SAMPLE_JOB, WRITER_OUTPUT)
        out = capsys.readouterr().out
        assert "Senior Software Engineer" in out
        assert "Acme Corp" in out


# ── _process_job tests ────────────────────────────────────────────────────────

class TestProcessJob:
    @pytest.mark.asyncio
    async def test_success_records_tailored(self, tmp_path):
        orc = make_orc(tmp_path)
        tracker_calls = []

        async def capture_tracker(action, job=None, status=None, **kwargs):
            tracker_calls.append((action, status))

        with patch.object(orc, "_run_tracker", side_effect=capture_tracker), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=True)):
            result = await orc._process_job(SAMPLE_JOB, {})

        assert result is True
        statuses = [s for _, s in tracker_calls]
        assert "Discovered" in statuses
        assert "Tailored" in statuses

    @pytest.mark.asyncio
    async def test_gate2_no_records_skipped(self, tmp_path):
        orc = make_orc(tmp_path)
        tracker_calls = []

        async def capture_tracker(action, job=None, status=None, **kwargs):
            tracker_calls.append((action, status))

        with patch.object(orc, "_run_tracker", side_effect=capture_tracker), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=False)):
            result = await orc._process_job(SAMPLE_JOB, {})

        assert result is False
        statuses = [s for _, s in tracker_calls]
        assert "Discovered" in statuses
        assert "Tailored" not in statuses

    @pytest.mark.asyncio
    async def test_writer_failure_records_rejected(self, tmp_path):
        orc = make_orc(tmp_path)
        tracker_calls = []

        async def capture_tracker(action, job=None, status=None, **kwargs):
            tracker_calls.append((action, status))

        with patch.object(orc, "_run_tracker", side_effect=capture_tracker), \
             patch.object(orc, "_fix_loop", new=AsyncMock(side_effect=WriterAgentError("Lane A failed"))):
            result = await orc._process_job(SAMPLE_JOB, {})

        assert result is False
        statuses = [s for _, s in tracker_calls]
        assert "Rejected" in statuses

    @pytest.mark.asyncio
    async def test_process_job_initial_status_is_discovered(self, tmp_path):
        orc = make_orc(tmp_path)
        first_call = {}

        async def capture_tracker(action, job=None, status=None, **kwargs):
            if not first_call:
                first_call["action"] = action
                first_call["status"] = status

        with patch.object(orc, "_run_tracker", side_effect=capture_tracker), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=True)):
            await orc._process_job(SAMPLE_JOB, {})

        assert first_call["action"] == "record_job"
        assert first_call["status"] == "Discovered"

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch.object(orc, "_run_tracker", new=AsyncMock()), \
             patch.object(orc, "_fix_loop", new=AsyncMock(return_value=WRITER_OUTPUT)), \
             patch.object(orc, "_gate2", new=AsyncMock(return_value=True)):
            result = await orc._process_job(SAMPLE_JOB, {})
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, tmp_path):
        orc = make_orc(tmp_path)
        with patch.object(orc, "_run_tracker", new=AsyncMock()), \
             patch.object(orc, "_fix_loop", new=AsyncMock(side_effect=Exception("unexpected"))):
            result = await orc._process_job(SAMPLE_JOB, {})
        assert result is False
