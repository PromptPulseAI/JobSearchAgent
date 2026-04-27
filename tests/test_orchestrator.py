"""Tests for agents/orchestrator.py — config validation, Gate 1, error fallbacks."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.orchestrator import _build_pending_approval, _gate1_cli, _load_and_validate_config
from utils.exceptions import AllSourcesFailedError, ConfigError, ConsentError


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
        "api_params": {
            "profile_extraction": {"max_tokens": 2000, "temperature": 0.1},
        },
    },
    "rate_limit": {"max_concurrent_api_calls": 3, "delay_between_jobs_ms": 0},
    "quality": {"max_auto_fix_retries": 2},
    "scoring": {"thresholds": {"best_match": 75, "possible_match": 50}},
    "job_sources": {"active_sources": [], "sources": {}},
    "automation": {"headless_mode": False, "pending_approval_file": "data/pending_approval.json"},
    "candidate": {"seniority": ["senior"], "employment_types": ["full-time"], "location": "anywhere_us"},
    "exclusions": {"security_clearance": True, "entry_level_junior": True, "companies_blacklist": [], "technologies_avoid": []},
}

SAMPLE_JOB = {
    "job_id": "dice_001",
    "title": "Senior Software Engineer",
    "company": "Acme",
    "location": "Remote",
    "score": 82,
    "url": "https://dice.com/001",
    "score_breakdown": {"reasoning": "Strong match."},
}


# ── _load_and_validate_config ─────────────────────────────────────────────────

class TestLoadAndValidateConfig:
    def test_raises_config_error_when_file_missing(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            _load_and_validate_config(str(tmp_path / "nonexistent.json"))

    def test_raises_consent_error_when_not_acknowledged(self, tmp_path):
        cfg = {**VALID_CONFIG, "gdpr": {"consent_acknowledged": False}}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))
        with pytest.raises(ConsentError, match="consent"):
            _load_and_validate_config(str(p))

    def test_raises_config_error_on_malformed_json(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text("{not valid json")
        with pytest.raises(ConfigError):
            _load_and_validate_config(str(p))

    def test_returns_config_when_valid(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps(VALID_CONFIG))
        cfg = _load_and_validate_config(str(p))
        assert cfg["gdpr"]["consent_acknowledged"] is True


# ── _build_pending_approval ───────────────────────────────────────────────────

class TestBuildPendingApproval:
    def test_structure(self):
        jobs = [SAMPLE_JOB]
        matches = {"best_match": [SAMPLE_JOB], "possible_match": []}
        result = _build_pending_approval(jobs, matches)
        assert result["total_jobs"] == 1
        assert result["best_match_count"] == 1
        assert result["status"] == "awaiting_approval"
        assert result["jobs"][0]["job_id"] == "dice_001"

    def test_includes_score_and_url(self):
        result = _build_pending_approval([SAMPLE_JOB], {"best_match": [], "possible_match": []})
        assert result["jobs"][0]["score"] == 82
        assert result["jobs"][0]["url"] == "https://dice.com/001"

    def test_empty_jobs_list(self):
        result = _build_pending_approval([], {"best_match": [], "possible_match": []})
        assert result["total_jobs"] == 0
        assert result["jobs"] == []


# ── Orchestrator init ─────────────────────────────────────────────────────────

class TestOrchestratorInit:
    def test_raises_config_error_when_no_api_key(self, tmp_path):
        from agents.orchestrator import Orchestrator
        p = tmp_path / "config.json"
        p.write_text(json.dumps(VALID_CONFIG))

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
                Orchestrator(config_path=str(p))

    def test_raises_consent_error_when_consent_false(self, tmp_path):
        from agents.orchestrator import Orchestrator
        cfg = {**VALID_CONFIG, "gdpr": {"consent_acknowledged": False}}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg))

        with pytest.raises(ConsentError):
            Orchestrator(config_path=str(p))

    def test_initializes_successfully_with_valid_config(self, tmp_path):
        from agents.orchestrator import Orchestrator
        p = tmp_path / "config.json"
        p.write_text(json.dumps(VALID_CONFIG))

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("utils.api_client.ClaudeClient.__init__", return_value=None):
                orc = Orchestrator(config_path=str(p), no_local_model=True)
        assert orc.dry_run is False
        assert orc.no_local_model is True


# ── Orchestrator.run() dry-run ────────────────────────────────────────────────

class TestOrchestratorRunDryRun:
    @pytest.fixture
    def orc(self, tmp_path):
        from agents.orchestrator import Orchestrator
        p = tmp_path / "config.json"
        cfg = {**VALID_CONFIG, "paths": {**VALID_CONFIG["paths"], "data_dir": str(tmp_path)}}
        p.write_text(json.dumps(cfg))

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("utils.api_client.ClaudeClient.__init__", return_value=None):
                return Orchestrator(config_path=str(p), dry_run=True, no_local_model=True)

    async def test_dry_run_completes_without_api_calls(self, orc):
        with patch.object(orc, "_run_tracker", new=AsyncMock()):
            with patch.object(orc, "_gate1", new=AsyncMock(return_value=[])):
                await orc.run()

    async def test_dry_run_skips_profile_agent(self, orc):
        with patch.object(orc, "_run_tracker", new=AsyncMock()):
            with patch.object(orc, "_gate1", new=AsyncMock(return_value=[])):
                with patch("agents.profile_agent.ProfileAgent.run", new=AsyncMock()) as mock_run:
                    await orc.run()
        mock_run.assert_not_called()


# ── Gate 1 CLI ────────────────────────────────────────────────────────────────

class TestGate1CLI:
    async def test_approves_on_yes_input(self, tmp_path):
        jobs = [SAMPLE_JOB]
        with patch("builtins.input", return_value="y"):
            approved = await _gate1_cli(jobs, tmp_path / "pending.json")
        assert len(approved) == 1

    async def test_skips_on_no_input(self, tmp_path):
        jobs = [SAMPLE_JOB]
        with patch("builtins.input", return_value="n"):
            approved = await _gate1_cli(jobs, tmp_path / "pending.json")
        assert len(approved) == 0

    async def test_empty_input_defaults_to_yes(self, tmp_path):
        jobs = [SAMPLE_JOB]
        with patch("builtins.input", return_value=""):
            approved = await _gate1_cli(jobs, tmp_path / "pending.json")
        assert len(approved) == 1

    async def test_quit_stops_iteration(self, tmp_path):
        jobs = [SAMPLE_JOB, {**SAMPLE_JOB, "job_id": "dice_002"}]
        inputs = iter(["y", "q"])
        with patch("builtins.input", side_effect=inputs):
            approved = await _gate1_cli(jobs, tmp_path / "pending.json")
        assert len(approved) == 1

    async def test_empty_jobs_returns_empty(self, tmp_path):
        approved = await _gate1_cli([], tmp_path / "pending.json")
        assert approved == []


# ── Error fallbacks ───────────────────────────────────────────────────────────

class TestOrchestratorErrorFallbacks:
    @pytest.fixture
    def orc(self, tmp_path):
        from agents.orchestrator import Orchestrator
        p = tmp_path / "config.json"
        cfg = {**VALID_CONFIG, "paths": {**VALID_CONFIG["paths"], "data_dir": str(tmp_path)}}
        p.write_text(json.dumps(cfg))

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("utils.api_client.ClaudeClient.__init__", return_value=None):
                return Orchestrator(config_path=str(p), no_local_model=True)

    async def test_profile_agent_failure_aborts_run(self, orc):
        from utils.exceptions import ProfileAgentError
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(side_effect=ProfileAgentError("no resume"))):
            with pytest.raises(ProfileAgentError):
                await orc.run()

    async def test_all_sources_failed_handled_gracefully(self, orc):
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value={})):
            with patch.object(orc, "_run_scout_agent", new=AsyncMock(side_effect=AllSourcesFailedError("all down"))):
                with patch.object(orc, "_run_tracker", new=AsyncMock()):
                    # Should NOT re-raise — logs and calls end-of-run tracker
                    await orc.run()

    async def test_tracker_failure_does_not_crash_run(self, orc):
        from utils.exceptions import TrackerAgentError
        with patch.object(orc, "_run_profile_agent", new=AsyncMock(return_value={})):
            with patch.object(orc, "_run_scout_agent", new=AsyncMock(return_value={"best_match": [], "possible_match": [], "not_matching": []})):
                with patch.object(orc, "_gate1", new=AsyncMock(return_value=[])):
                    # Patch the inner TrackerAgent.run so _run_tracker catches it internally
                    with patch("agents.tracker_agent.TrackerAgent.run", new=AsyncMock(side_effect=TrackerAgentError("disk full"))):
                        await orc.run()  # TrackerAgentError caught inside _run_tracker, must not propagate
