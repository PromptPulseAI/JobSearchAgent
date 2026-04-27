"""Tests for agents/reviewer_agent.py — Phase 1 mechanical, Phase 2 quality, scoring."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.reviewer_agent import ReviewerAgent, _parse_review_response
from utils.exceptions import ReviewerAgentError


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_JOB = {
    "job_id": "dice_001",
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "location": "Remote",
    "job_description": "Python, AWS, Kubernetes, REST APIs. 5+ years required. CI/CD preferred.",
}

SAMPLE_PROFILE = {
    "name": "Jane Dev",
    "target_titles": ["Senior Software Engineer"],
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
    "industries": ["fintech"],
    "keywords": ["microservices"],
}

PHASE2_PASS = {
    "passed": True,
    "score": 88,
    "review_notes": "Strong match. Well-tailored resume.",
    "issues": [],
    "fix_instructions": None,
}

PHASE2_FAIL = {
    "passed": False,
    "score": 60,
    "review_notes": "Fabrication risk in experience bullet.",
    "issues": [
        {
            "severity": "error",
            "location": "resume.experience[0].bullets[0]",
            "issue": "Unsubstantiated claim",
            "fix": "Remove percentage",
        }
    ],
    "fix_instructions": {
        "resume_fixes": [{"location": "experience", "issue": "Fabrication", "fix": "Remove %"}]
    },
}


def make_reviewer(tmp_path):
    config = {
        "gdpr": {"pii_in_logs": False, "consent_acknowledged": True},
        "paths": {"prompts_dir": "prompts", "logs_dir": str(tmp_path / "logs")},
        "llm": {"api_model": "claude-sonnet-4-6", "api_params": {"quality_review": {}}},
        "quality": {"ats_target_coverage": 85, "max_auto_fix_retries": 2},
    }

    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.name = "reviewer_agent"
    agent.config = config
    agent.claude = AsyncMock()

    def mock_log(level, msg, **kwargs):
        pass

    def mock_audit(action, target, status, **kwargs):
        pass

    def mock_load_prompt(name):
        return f"System prompt for {name}"

    agent.log = mock_log
    agent.audit = mock_audit
    agent.load_prompt = mock_load_prompt
    return agent


# ── _parse_review_response ────────────────────────────────────────────────────

class TestParseReviewResponse:
    def test_valid_json_returns_dict(self):
        raw = json.dumps({"passed": True, "score": 85, "issues": []})
        result = _parse_review_response(raw)
        assert result["passed"] is True
        assert result["score"] == 85

    def test_applies_defaults(self):
        raw = json.dumps({"passed": False})
        result = _parse_review_response(raw)
        assert "score" in result
        assert "issues" in result
        assert "fix_instructions" in result
        assert "review_notes" in result

    def test_strips_json_fences(self):
        raw = '```json\n{"passed": true, "score": 80, "issues": []}\n```'
        result = _parse_review_response(raw)
        assert result["score"] == 80

    def test_plain_fences_also_stripped(self):
        raw = '```\n{"passed": true}\n```'
        result = _parse_review_response(raw)
        assert result["passed"] is True

    def test_invalid_json_raises_reviewer_error(self):
        with pytest.raises(ReviewerAgentError, match="invalid JSON"):
            _parse_review_response("not valid JSON {{{")


# ── _check_ats_coverage ───────────────────────────────────────────────────────

class TestCheckAtsCoverage:
    def test_low_coverage_adds_error_issue(self, tmp_path):
        agent = make_reviewer(tmp_path)
        issues = []
        with patch("agents.reviewer_agent.extract_keywords") as mock_kw, \
             patch("agents.reviewer_agent.compute_coverage") as mock_cov:
            mock_kw.return_value = {"required": {"python", "kubernetes"}, "preferred": set()}
            mock_cov.return_value = {
                "coverage_percent": 30,
                "required": {"found": [], "missing": ["python", "kubernetes"]},
                "preferred": {"found": [], "missing": []},
            }
            agent._check_ats_coverage(SAMPLE_JOB, None, issues)

        assert len(issues) == 1
        assert issues[0]["severity"] == "error"
        assert "30" in issues[0]["issue"]

    def test_moderate_coverage_adds_warning(self, tmp_path):
        agent = make_reviewer(tmp_path)
        issues = []
        with patch("agents.reviewer_agent.extract_keywords") as mock_kw, \
             patch("agents.reviewer_agent.compute_coverage") as mock_cov:
            mock_kw.return_value = {"required": {"python"}, "preferred": set()}
            mock_cov.return_value = {
                "coverage_percent": 65,
                "required": {"found": [], "missing": ["python"]},
                "preferred": {"found": [], "missing": []},
            }
            agent._check_ats_coverage(SAMPLE_JOB, None, issues)

        assert len(issues) == 1
        assert issues[0]["severity"] == "warning"

    def test_good_coverage_no_issue(self, tmp_path):
        agent = make_reviewer(tmp_path)
        issues = []
        with patch("agents.reviewer_agent.extract_keywords") as mock_kw, \
             patch("agents.reviewer_agent.compute_coverage") as mock_cov:
            mock_kw.return_value = {"required": set(), "preferred": set()}
            mock_cov.return_value = {
                "coverage_percent": 92,
                "required": {"found": [], "missing": []},
                "preferred": {"found": [], "missing": []},
            }
            agent._check_ats_coverage(SAMPLE_JOB, None, issues)

        assert issues == []


# ── _cross_reference_skills ───────────────────────────────────────────────────

class TestCrossReferenceSkills:
    def test_many_missing_skills_adds_warning(self, tmp_path):
        agent = make_reviewer(tmp_path)
        issues = []
        sparse_profile = {"skills": {"technical": [{"name": "Python"}]}}
        with patch("agents.reviewer_agent.extract_keywords") as mock_kw:
            mock_kw.return_value = {
                "required": {"go", "rust", "erlang", "haskell", "cobol"},
                "preferred": set(),
            }
            agent._cross_reference_skills(SAMPLE_JOB, sparse_profile, issues)

        assert len(issues) == 1
        assert issues[0]["severity"] == "warning"
        assert "skills_cross_reference" in issues[0]["location"]

    def test_few_missing_skills_no_warning(self, tmp_path):
        agent = make_reviewer(tmp_path)
        issues = []
        with patch("agents.reviewer_agent.extract_keywords") as mock_kw:
            mock_kw.return_value = {"required": {"go"}, "preferred": set()}
            agent._cross_reference_skills(SAMPLE_JOB, SAMPLE_PROFILE, issues)

        assert issues == []

    def test_all_skills_present_no_warning(self, tmp_path):
        agent = make_reviewer(tmp_path)
        issues = []
        with patch("agents.reviewer_agent.extract_keywords") as mock_kw:
            mock_kw.return_value = {"required": {"python", "aws"}, "preferred": set()}
            agent._cross_reference_skills(SAMPLE_JOB, SAMPLE_PROFILE, issues)

        assert issues == []


# ── _write_review_notes ───────────────────────────────────────────────────────

class TestWriteReviewNotes:
    def test_creates_review_notes_file(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result = {
            "review_pass": 1,
            "score": 85,
            "passed": True,
            "review_notes": "Good resume.",
            "issues": [],
        }
        agent._write_review_notes(result, SAMPLE_JOB, tmp_path)
        notes = (tmp_path / "review_notes.md").read_text()
        assert "Senior Software Engineer" in notes
        assert "Acme Corp" in notes
        assert "85/100" in notes
        assert "PASSED" in notes

    def test_failed_review_shows_failed_status(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result = {
            "review_pass": 2,
            "score": 55,
            "passed": False,
            "review_notes": "Multiple issues.",
            "issues": [
                {"severity": "error", "location": "resume.skills", "issue": "Missing keyword", "fix": "Add it"}
            ],
        }
        agent._write_review_notes(result, SAMPLE_JOB, tmp_path)
        notes = (tmp_path / "review_notes.md").read_text()
        assert "NEEDS FIX" in notes
        assert "Missing keyword" in notes

    def test_error_issue_gets_red_indicator(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result = {
            "review_pass": 1,
            "score": 60,
            "passed": False,
            "review_notes": "",
            "issues": [
                {"severity": "error", "location": "resume.skills", "issue": "Error issue", "fix": "Fix it"}
            ],
        }
        agent._write_review_notes(result, SAMPLE_JOB, tmp_path)
        notes = (tmp_path / "review_notes.md").read_text()
        assert "🔴" in notes

    def test_warning_issue_gets_yellow_indicator(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result = {
            "review_pass": 1,
            "score": 75,
            "passed": True,
            "review_notes": "",
            "issues": [
                {"severity": "warning", "location": "resume.skills", "issue": "Warning issue", "fix": "Fix it"}
            ],
        }
        agent._write_review_notes(result, SAMPLE_JOB, tmp_path)
        notes = (tmp_path / "review_notes.md").read_text()
        assert "🟡" in notes


# ── _append_fix_history ───────────────────────────────────────────────────────

class TestAppendFixHistory:
    def test_creates_history_file_on_first_call(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result = {"review_pass": 1, "score": 85, "passed": True, "issues": []}
        agent._append_fix_history(result, SAMPLE_JOB, tmp_path)
        assert (tmp_path / "fix_history.md").exists()

    def test_appends_on_subsequent_calls(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result1 = {"review_pass": 1, "score": 65, "passed": False, "issues": []}
        result2 = {"review_pass": 2, "score": 85, "passed": True, "issues": []}
        agent._append_fix_history(result1, SAMPLE_JOB, tmp_path)
        agent._append_fix_history(result2, SAMPLE_JOB, tmp_path)
        content = (tmp_path / "fix_history.md").read_text()
        assert "Pass 1" in content
        assert "Pass 2" in content

    def test_history_includes_pass_number_and_score(self, tmp_path):
        agent = make_reviewer(tmp_path)
        result = {"review_pass": 3, "score": 72, "passed": True, "issues": []}
        agent._append_fix_history(result, SAMPLE_JOB, tmp_path)
        content = (tmp_path / "fix_history.md").read_text()
        assert "Pass 3" in content
        assert "72/100" in content


# ── ReviewerAgent.run() ───────────────────────────────────────────────────────

class TestReviewerAgentRun:
    @pytest.mark.asyncio
    async def test_run_passes_when_score_high_no_errors(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": None}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 95, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_PASS}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert result["passed"] is True
        assert result["score"] >= 70

    @pytest.mark.asyncio
    async def test_run_fails_when_phase1_has_errors(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": None}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {
                "passed": False,
                "score": 50,
                "issues": [{"severity": "error", "location": "ats", "issue": "Bad coverage", "fix": "Add keywords"}],
                "ats_coverage": {},
            }
            mock_p2.return_value = {**PHASE2_PASS}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_run_fails_when_phase2_has_errors(self, tmp_path):
        agent = make_reviewer(tmp_path)
        resume_path = str(tmp_path / "tailored_resume.docx")
        writer_output = {"output_dir": str(tmp_path), "resume": resume_path}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 95, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_FAIL}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert result["passed"] is False
        assert result["fix_instructions"] is not None

    @pytest.mark.asyncio
    async def test_run_fails_when_combined_score_below_70(self, tmp_path):
        agent = make_reviewer(tmp_path)
        resume_path = str(tmp_path / "tailored_resume.docx")
        writer_output = {"output_dir": str(tmp_path), "resume": resume_path}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 55, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {"passed": True, "score": 60, "issues": [], "fix_instructions": None, "review_notes": ""}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert result["score"] < 70
        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_phase2_failure_is_degraded_not_crash(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": "some_path.docx"}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 90, "issues": [], "ats_coverage": {}}
            mock_p2.side_effect = Exception("Claude API timeout")

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert result is not None
        assert "score" in result

    @pytest.mark.asyncio
    async def test_fix_instructions_none_when_passed(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": None}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 95, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_PASS}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert result["fix_instructions"] is None

    @pytest.mark.asyncio
    async def test_writes_review_notes_file(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": None}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 95, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_PASS}

            await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert (tmp_path / "review_notes.md").exists()
        assert (tmp_path / "fix_history.md").exists()

    @pytest.mark.asyncio
    async def test_writes_fix_instructions_json_when_failed(self, tmp_path):
        agent = make_reviewer(tmp_path)
        resume_path = str(tmp_path / "tailored_resume.docx")
        writer_output = {"output_dir": str(tmp_path), "resume": resume_path}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 90, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_FAIL}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        assert (tmp_path / "fix_instructions.json").exists()

    @pytest.mark.asyncio
    async def test_review_pass_number_included_in_result(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": None}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 95, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_PASS}

            result = await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE, review_pass=2)

        assert result["review_pass"] == 2

    @pytest.mark.asyncio
    async def test_no_resume_path_skips_phase2(self, tmp_path):
        agent = make_reviewer(tmp_path)
        writer_output = {"output_dir": str(tmp_path), "resume": None}

        with patch.object(agent, "_phase1_mechanical") as mock_p1, \
             patch.object(agent, "_phase2_quality", new_callable=AsyncMock) as mock_p2:
            mock_p1.return_value = {"passed": True, "score": 95, "issues": [], "ats_coverage": {}}
            mock_p2.return_value = {**PHASE2_PASS}

            await agent.run(SAMPLE_JOB, writer_output, SAMPLE_PROFILE)

        mock_p2.assert_not_called()
