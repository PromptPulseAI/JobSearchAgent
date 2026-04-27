"""Tests for agents/tracker_agent.py — CRUD, status lifecycle, metrics, archival."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tracker_agent import (
    TrackerAgent,
    VALID_TRANSITIONS,
    _build_entry,
    _compute_metrics,
    _find_job,
    _parse_dt,
)
from utils.exceptions import TrackerAgentError


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_JOB = {
    "job_id": "dice_001",
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "location": "Remote",
    "score": 82,
    "url": "https://dice.com/001",
}

SAMPLE_JOB_2 = {
    "job_id": "dice_002",
    "title": "Staff Engineer",
    "company": "Betacorp",
    "location": "NYC",
    "score": 76,
    "url": "https://dice.com/002",
}


def make_tracker(tmp_path):
    config = {
        "gdpr": {"pii_in_logs": False, "consent_acknowledged": True},
        "paths": {"prompts_dir": "prompts", "logs_dir": str(tmp_path / "logs"), "data_dir": str(tmp_path)},
        "llm": {"api_model": "claude-sonnet-4-6"},
    }
    agent = TrackerAgent.__new__(TrackerAgent)
    agent.name = "tracker_agent"
    agent.config = config
    agent.claude = AsyncMock()
    agent.local_llm = None

    def noop_log(level, msg, **kwargs): pass
    def noop_audit(action, target, status, **kwargs): pass

    agent.log = noop_log
    agent.audit = noop_audit
    return agent


def seed_tracker(tmp_path, entries, archived=None):
    """Write a tracker JSON to tmp_path/application_tracker.json."""
    tracker = {
        "jobs": entries,
        "archived_jobs": archived or [],
        "last_run_at": None,
        "metrics": {},
    }
    (tmp_path / "application_tracker.json").write_text(json.dumps(tracker), encoding="utf-8")


# ── VALID_TRANSITIONS ─────────────────────────────────────────────────────────

class TestValidTransitions:
    def test_discovered_can_become_tailored(self):
        assert "Tailored" in VALID_TRANSITIONS["Discovered"]

    def test_discovered_can_become_rejected(self):
        assert "Rejected" in VALID_TRANSITIONS["Discovered"]

    def test_tailored_can_become_applied(self):
        assert "Applied" in VALID_TRANSITIONS["Tailored"]

    def test_applied_can_become_interview(self):
        assert "Interview" in VALID_TRANSITIONS["Applied"]

    def test_applied_can_become_ghosted(self):
        assert "Ghosted" in VALID_TRANSITIONS["Applied"]

    def test_rejected_has_no_transitions(self):
        assert VALID_TRANSITIONS["Rejected"] == set()

    def test_accepted_has_no_transitions(self):
        assert VALID_TRANSITIONS["Accepted"] == set()

    def test_ghosted_can_re_apply(self):
        assert "Applied" in VALID_TRANSITIONS["Ghosted"]


# ── _build_entry ──────────────────────────────────────────────────────────────

class TestBuildEntry:
    def test_includes_required_fields(self):
        now = datetime.now(timezone.utc).isoformat()
        entry = _build_entry(SAMPLE_JOB, "Discovered", now)
        assert entry["job_id"] == "dice_001"
        assert entry["status"] == "Discovered"
        assert entry["follow_up_needed"] is False
        assert entry["archived"] is False

    def test_preserves_score(self):
        now = datetime.now(timezone.utc).isoformat()
        entry = _build_entry(SAMPLE_JOB, "Tailored", now)
        assert entry["score"] == 82


# ── _find_job ─────────────────────────────────────────────────────────────────

class TestFindJob:
    def test_finds_existing_job(self):
        jobs = [{"job_id": "dice_001", "title": "Eng"}]
        assert _find_job(jobs, "dice_001") is not None

    def test_returns_none_when_missing(self):
        assert _find_job([], "dice_999") is None

    def test_returns_correct_entry(self):
        jobs = [{"job_id": "a"}, {"job_id": "b"}]
        assert _find_job(jobs, "b")["job_id"] == "b"


# ── _compute_metrics ──────────────────────────────────────────────────────────

class TestComputeMetrics:
    def test_counts_discovered(self):
        entries = [{"status": "Discovered"}, {"status": "Discovered"}]
        m = _compute_metrics(entries)
        assert m["total_discovered"] == 2

    def test_counts_each_status(self):
        entries = [
            {"status": "Tailored"},
            {"status": "Applied"},
            {"status": "Interview"},
            {"status": "Offered"},
            {"status": "Rejected"},
        ]
        m = _compute_metrics(entries)
        assert m["total_tailored"] == 1
        assert m["total_applied"] == 1
        assert m["total_interview"] == 1
        assert m["total_offered"] == 1
        assert m["total_rejected"] == 1

    def test_accepted_increments_offered_and_accepted(self):
        entries = [{"status": "Accepted"}]
        m = _compute_metrics(entries)
        assert m["total_offered"] == 1
        assert m["total_accepted"] == 1

    def test_ghosted_counts_as_rejected(self):
        entries = [{"status": "Ghosted"}]
        m = _compute_metrics(entries)
        assert m["total_rejected"] == 1


# ── record_job ────────────────────────────────────────────────────────────────

class TestRecordJob:
    @pytest.mark.asyncio
    async def test_creates_new_entry(self, tmp_path):
        agent = make_tracker(tmp_path)
        await agent.run("record_job", job=SAMPLE_JOB, status="Discovered")
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert len(tracker["jobs"]) == 1
        assert tracker["jobs"][0]["job_id"] == "dice_001"
        assert tracker["jobs"][0]["status"] == "Discovered"

    @pytest.mark.asyncio
    async def test_updates_existing_entry_valid_transition(self, tmp_path):
        agent = make_tracker(tmp_path)
        await agent.run("record_job", job=SAMPLE_JOB, status="Discovered")
        await agent.run("record_job", job=SAMPLE_JOB, status="Tailored")
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert len(tracker["jobs"]) == 1
        assert tracker["jobs"][0]["status"] == "Tailored"

    @pytest.mark.asyncio
    async def test_raises_on_invalid_transition(self, tmp_path):
        agent = make_tracker(tmp_path)
        await agent.run("record_job", job=SAMPLE_JOB, status="Discovered")
        with pytest.raises(TrackerAgentError, match="Invalid transition"):
            await agent.run("record_job", job=SAMPLE_JOB, status="Interview")

    @pytest.mark.asyncio
    async def test_raises_on_invalid_status(self, tmp_path):
        agent = make_tracker(tmp_path)
        with pytest.raises(TrackerAgentError, match="Invalid status"):
            await agent.run("record_job", job=SAMPLE_JOB, status="Pending")

    @pytest.mark.asyncio
    async def test_dedup_two_distinct_jobs(self, tmp_path):
        agent = make_tracker(tmp_path)
        await agent.run("record_job", job=SAMPLE_JOB, status="Discovered")
        await agent.run("record_job", job=SAMPLE_JOB_2, status="Discovered")
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert len(tracker["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_same_status_is_idempotent(self, tmp_path):
        """Recording the same status again should not raise."""
        agent = make_tracker(tmp_path)
        await agent.run("record_job", job=SAMPLE_JOB, status="Discovered")
        await agent.run("record_job", job=SAMPLE_JOB, status="Discovered")
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert len(tracker["jobs"]) == 1

    @pytest.mark.asyncio
    async def test_raises_without_job(self, tmp_path):
        agent = make_tracker(tmp_path)
        with pytest.raises(TrackerAgentError, match="requires job"):
            await agent.run("record_job", status="Discovered")

    @pytest.mark.asyncio
    async def test_raises_without_status(self, tmp_path):
        agent = make_tracker(tmp_path)
        with pytest.raises(TrackerAgentError, match="requires job"):
            await agent.run("record_job", job=SAMPLE_JOB)


# ── end_of_run ────────────────────────────────────────────────────────────────

class TestEndOfRun:
    @pytest.mark.asyncio
    async def test_flags_applied_jobs_older_than_7_days(self, tmp_path):
        agent = make_tracker(tmp_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        seed_tracker(tmp_path, [
            {**_build_entry(SAMPLE_JOB, "Applied", old_date), "updated_at": old_date}
        ])
        await agent.run("end_of_run", run_summary={})
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert tracker["jobs"][0]["follow_up_needed"] is True

    @pytest.mark.asyncio
    async def test_does_not_flag_recent_applied_jobs(self, tmp_path):
        agent = make_tracker(tmp_path)
        recent = datetime.now(timezone.utc).isoformat()
        seed_tracker(tmp_path, [
            {**_build_entry(SAMPLE_JOB, "Applied", recent)}
        ])
        await agent.run("end_of_run", run_summary={})
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert tracker["jobs"][0]["follow_up_needed"] is False

    @pytest.mark.asyncio
    async def test_archives_rejected_jobs_older_than_30_days(self, tmp_path):
        agent = make_tracker(tmp_path)
        old_date = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        seed_tracker(tmp_path, [
            {**_build_entry(SAMPLE_JOB, "Rejected", old_date), "updated_at": old_date}
        ])
        await agent.run("end_of_run", run_summary={})
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert len(tracker["jobs"]) == 0
        assert len(tracker["archived_jobs"]) == 1

    @pytest.mark.asyncio
    async def test_does_not_archive_recent_rejected(self, tmp_path):
        agent = make_tracker(tmp_path)
        recent = datetime.now(timezone.utc).isoformat()
        seed_tracker(tmp_path, [
            {**_build_entry(SAMPLE_JOB, "Rejected", recent)}
        ])
        await agent.run("end_of_run", run_summary={})
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert len(tracker["jobs"]) == 1
        assert len(tracker["archived_jobs"]) == 0

    @pytest.mark.asyncio
    async def test_writes_master_summary_md(self, tmp_path):
        agent = make_tracker(tmp_path)
        seed_tracker(tmp_path, [_build_entry(SAMPLE_JOB, "Tailored", datetime.now(timezone.utc).isoformat())])
        await agent.run("end_of_run", run_summary={})
        assert (tmp_path / "master_summary.md").exists()
        content = (tmp_path / "master_summary.md").read_text()
        assert "Conversion Funnel" in content

    @pytest.mark.asyncio
    async def test_appends_to_run_history(self, tmp_path):
        agent = make_tracker(tmp_path)
        seed_tracker(tmp_path, [])
        summary = {"jobs_found": 5, "jobs_approved": 3, "jobs_completed": 2, "jobs_skipped": 1}
        await agent.run("end_of_run", run_summary=summary)
        history = json.loads((tmp_path / "run_history.json").read_text())
        assert len(history) == 1
        assert history[0]["jobs_found"] == 5

    @pytest.mark.asyncio
    async def test_computes_metrics(self, tmp_path):
        agent = make_tracker(tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        seed_tracker(tmp_path, [
            _build_entry(SAMPLE_JOB, "Applied", now),
            _build_entry(SAMPLE_JOB_2, "Tailored", now),
        ])
        await agent.run("end_of_run", run_summary={})
        tracker = json.loads((tmp_path / "application_tracker.json").read_text())
        assert tracker["metrics"]["total_applied"] == 1
        assert tracker["metrics"]["total_tailored"] == 1

    @pytest.mark.asyncio
    async def test_writes_scoring_feedback(self, tmp_path):
        agent = make_tracker(tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        entry = {**_build_entry(SAMPLE_JOB, "Applied", now), "user_override": True}
        seed_tracker(tmp_path, [entry])
        await agent.run("end_of_run", run_summary={})
        assert (tmp_path / "scoring_feedback.json").exists()
        feedback = json.loads((tmp_path / "scoring_feedback.json").read_text())
        assert len(feedback) == 1
        assert feedback[0]["job_id"] == "dice_001"


# ── status_update ─────────────────────────────────────────────────────────────

class TestStatusUpdate:
    @pytest.mark.asyncio
    async def test_valid_transition_updates_status(self, tmp_path):
        agent = make_tracker(tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        seed_tracker(tmp_path, [_build_entry(SAMPLE_JOB, "Tailored", now)])
        result = await agent.run("status_update", job=SAMPLE_JOB, status="Applied")
        assert result["new_status"] == "Applied"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, tmp_path):
        agent = make_tracker(tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        seed_tracker(tmp_path, [_build_entry(SAMPLE_JOB, "Discovered", now)])
        with pytest.raises(TrackerAgentError, match="Invalid transition"):
            await agent.run("status_update", job=SAMPLE_JOB, status="Applied")

    @pytest.mark.asyncio
    async def test_missing_job_raises(self, tmp_path):
        agent = make_tracker(tmp_path)
        seed_tracker(tmp_path, [])
        with pytest.raises(TrackerAgentError, match="not found"):
            await agent.run("status_update", job=SAMPLE_JOB, status="Tailored")

    @pytest.mark.asyncio
    async def test_user_override_writes_feedback(self, tmp_path):
        agent = make_tracker(tmp_path)
        now = datetime.now(timezone.utc).isoformat()
        seed_tracker(tmp_path, [_build_entry(SAMPLE_JOB, "Tailored", now)])
        await agent.run("status_update", job=SAMPLE_JOB, status="Applied")
        assert (tmp_path / "scoring_feedback.json").exists()
        feedback = json.loads((tmp_path / "scoring_feedback.json").read_text())
        assert feedback[0]["new_status"] == "Applied"
        assert feedback[0]["user_override"] is True


# ── Unknown action ────────────────────────────────────────────────────────────

class TestUnknownAction:
    @pytest.mark.asyncio
    async def test_raises_on_unknown_action(self, tmp_path):
        agent = make_tracker(tmp_path)
        with pytest.raises(TrackerAgentError, match="Unknown tracker action"):
            await agent.run("explode")
