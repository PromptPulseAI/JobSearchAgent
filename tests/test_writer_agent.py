"""Tests for agents/writer_agent.py — 3 parallel lanes, fix mode, helpers."""
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.writer_agent import (
    WriterAgent,
    _backup_resume,
    _build_cover_letter_prompt,
    _build_fix_prompt,
    _build_prep_prompt,
    _build_resume_prompt,
    _generate_docx,
    _parse_json_response,
    _prep_to_markdown,
    _slugify,
)
from utils.exceptions import DocxGenerationError, WriterAgentError


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_JOB = {
    "job_id": "dice_001",
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "location": "Remote",
    "date_posted": "2026-04-25",
    "job_description": "Python, AWS, Kubernetes. 5+ years required.",
    "employment_type": "full-time",
    "url": "https://dice.com/jobs/001",
    "score": 82,
    "score_breakdown": {
        "core_skills_match": 85,
        "title_seniority_alignment": 80,
        "industry_domain_fit": 70,
        "years_experience_fit": 90,
        "nice_to_have_skills": 60,
        "company_culture_signals": 75,
        "reasoning": "Strong Python/AWS match.",
    },
    "company_context": {"founded": "2010"},
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
    "industries": ["fintech", "saas"],
    "keywords": ["microservices", "REST API"],
    "experience_summary": [
        {
            "title": "Staff Engineer",
            "company": "BigCo",
            "years": "2020-present",
            "highlights": ["Led migration", "reduced costs 30%"],
        }
    ],
    "education": [
        {"degree": "B.S. Computer Science", "school": "State University", "year": "2016"}
    ],
}

RESUME_JSON = {
    "name": "Jane Dev",
    "contact": "jane@example.com",
    "summary": "Senior engineer with 8 years experience.",
    "experience": [
        {"title": "Staff Engineer", "company": "BigCo", "dates": "2020-present", "bullets": ["Led migration"]}
    ],
    "education": [{"degree": "B.S. CS", "school": "State U", "year": "2016"}],
    "skills": ["Python", "AWS", "Kubernetes"],
}

COVER_LETTER_JSON = {
    "paragraphs": ["Dear Hiring Manager,", "I am excited to apply."],
    "closing": "Sincerely,",
    "name": "Jane Dev",
}

PREP_JSON = {
    "company_research": {
        "what_they_do": "Makes software.",
        "tech_stack_signals": ["Python", "AWS"],
        "culture_signals": ["fast-paced"],
        "key_talking_points": ["I love their product"],
    },
    "likely_technical_questions": [
        {"question": "Tell me about Python", "why_asked": "JD requires Python", "answer_framework": "STAR: ..."}
    ],
    "likely_behavioral_questions": [
        {"question": "Lead a team?", "why_asked": "JD mentions leadership", "answer_framework": "STAR: ..."}
    ],
    "skills_to_emphasize": ["Python", "AWS"],
    "skills_gap_awareness": [],
    "questions_to_ask": ["What is the on-call rotation?"],
}


def make_writer(tmp_path, config_override=None):
    config = {
        "gdpr": {"pii_in_logs": False, "consent_acknowledged": True},
        "paths": {"prompts_dir": "prompts", "logs_dir": str(tmp_path / "logs"), "output_dir": str(tmp_path / "Output")},
        "llm": {"api_model": "claude-sonnet-4-6", "api_params": {}},
        "quality": {"ats_target_coverage": 85, "max_auto_fix_retries": 2},
        "scoring": {"thresholds": {"best_match": 75}},
    }
    if config_override:
        config.update(config_override)

    agent = WriterAgent.__new__(WriterAgent)
    agent.name = "writer_agent"
    agent.config = config
    agent.claude = AsyncMock()
    agent.local_llm = None

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


# ── _slugify ──────────────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic_conversion(self):
        assert _slugify("Acme Corp_Senior Engineer_001") == "acme_corp_senior_engineer_001"

    def test_removes_special_chars(self):
        result = _slugify("Company (Inc.) — Role #2!")
        assert "(" not in result
        assert "#" not in result
        assert "!" not in result

    def test_max_80_chars(self):
        long_text = "a" * 100
        assert len(_slugify(long_text)) <= 80

    def test_spaces_become_underscores(self):
        assert _slugify("hello world") == "hello_world"


# ── _parse_json_response ──────────────────────────────────────────────────────

class TestParseJsonResponse:
    def test_valid_plain_json(self):
        raw = json.dumps({"key": "value"})
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_strips_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result["key"] == "value"

    def test_strips_plain_fence(self):
        raw = '```\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result["key"] == "value"

    def test_invalid_json_raises_writer_error(self):
        with pytest.raises(WriterAgentError, match="Invalid JSON"):
            _parse_json_response("not json at all", context="resume")

    def test_context_included_in_error(self):
        with pytest.raises(WriterAgentError, match="cover_letter"):
            _parse_json_response("{bad}", context="cover_letter")


# ── _backup_resume ────────────────────────────────────────────────────────────

class TestBackupResume:
    def test_creates_v1_backup(self, tmp_path):
        resume = tmp_path / "tailored_resume.docx"
        resume.write_bytes(b"content")
        _backup_resume(resume, tmp_path)
        assert (tmp_path / "v1_resume.docx").exists()
        assert not resume.exists()

    def test_creates_v2_if_v1_exists(self, tmp_path):
        (tmp_path / "v1_resume.docx").write_bytes(b"old")
        resume = tmp_path / "tailored_resume.docx"
        resume.write_bytes(b"new")
        _backup_resume(resume, tmp_path)
        assert (tmp_path / "v2_resume.docx").exists()

    def test_increments_version_number(self, tmp_path):
        for i in range(1, 4):
            (tmp_path / f"v{i}_resume.docx").write_bytes(b"v")
        resume = tmp_path / "tailored_resume.docx"
        resume.write_bytes(b"latest")
        _backup_resume(resume, tmp_path)
        assert (tmp_path / "v4_resume.docx").exists()


# ── _generate_docx ────────────────────────────────────────────────────────────

class TestGenerateDocx:
    def test_node_not_installed_writes_stub(self, tmp_path):
        output = tmp_path / "resume.docx"
        data = {"type": "resume", "content": {"name": "Jane"}}
        with patch("subprocess.run", side_effect=FileNotFoundError("node not found")):
            _generate_docx(data, output)
        assert output.exists()
        assert output.read_bytes() == b"STUB"
        stub_json = output.with_suffix(".json")
        assert stub_json.exists()
        assert json.loads(stub_json.read_text())["type"] == "resume"

    def test_node_failure_raises_docx_error(self, tmp_path):
        output = tmp_path / "resume.docx"
        data = {"type": "resume", "content": {}}
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Syntax error in docx_writer.js"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(DocxGenerationError, match="docx_writer.js failed"):
                _generate_docx(data, output)

    def test_success_path_calls_node(self, tmp_path):
        output = tmp_path / "resume.docx"
        data = {"type": "resume", "content": {}}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            _generate_docx(data, output)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "node"
        assert "docx_writer.js" in call_args[1]


# ── _prep_to_markdown ─────────────────────────────────────────────────────────

class TestPrepToMarkdown:
    def test_generates_all_sections(self):
        md = _prep_to_markdown(PREP_JSON)
        assert "# Interview Preparation Guide" in md
        assert "## Company Research" in md
        assert "## Likely Technical Questions" in md
        assert "## Likely Behavioral Questions" in md
        assert "## Skills to Emphasize" in md
        assert "## Questions to Ask" in md

    def test_includes_question_text(self):
        md = _prep_to_markdown(PREP_JSON)
        assert "Tell me about Python" in md
        assert "What is the on-call rotation?" in md

    def test_handles_empty_data(self):
        md = _prep_to_markdown({})
        assert "# Interview Preparation Guide" in md

    def test_tech_stack_signals_in_output(self):
        md = _prep_to_markdown(PREP_JSON)
        assert "Python" in md
        assert "AWS" in md


# ── Prompt builders ───────────────────────────────────────────────────────────

class TestPromptBuilders:
    def test_resume_prompt_includes_job_title(self):
        msg = _build_resume_prompt(SAMPLE_JOB, SAMPLE_PROFILE)
        assert "Senior Software Engineer" in msg

    def test_resume_prompt_includes_skills(self):
        msg = _build_resume_prompt(SAMPLE_JOB, SAMPLE_PROFILE)
        assert "Python" in msg
        assert "AWS" in msg

    def test_cover_letter_prompt_includes_company(self):
        msg = _build_cover_letter_prompt(SAMPLE_JOB, SAMPLE_PROFILE)
        assert "Acme Corp" in msg

    def test_prep_prompt_includes_experience(self):
        msg = _build_prep_prompt(SAMPLE_JOB, SAMPLE_PROFILE)
        assert "Staff Engineer" in msg

    def test_fix_prompt_includes_fixes(self):
        fix_instructions = {
            "resume_fixes": [{"location": "skills", "issue": "Missing Python", "fix": "Add Python"}]
        }
        msg = _build_fix_prompt(SAMPLE_JOB, SAMPLE_PROFILE, fix_instructions)
        assert "Fix Instructions" in msg
        assert "Missing Python" in msg


# ── WriterAgent.run() ─────────────────────────────────────────────────────────

class TestWriterAgentRun:
    @pytest.mark.asyncio
    async def test_run_success_all_lanes(self, tmp_path):
        agent = make_writer(tmp_path)
        agent.claude.generate = AsyncMock(side_effect=[
            json.dumps(RESUME_JSON),
            json.dumps(COVER_LETTER_JSON),
            json.dumps(PREP_JSON),
        ])

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

        assert result["resume"] is not None
        assert result["degraded"] is False

    @pytest.mark.asyncio
    async def test_lane_a_failure_raises_writer_error(self, tmp_path):
        agent = make_writer(tmp_path)
        agent.claude.generate = AsyncMock(side_effect=WriterAgentError("Claude failed"))

        with patch("agents.writer_agent._generate_docx"):
            with pytest.raises(WriterAgentError, match="Lane A"):
                await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

    @pytest.mark.asyncio
    async def test_lane_b_failure_is_degraded(self, tmp_path):
        agent = make_writer(tmp_path)

        async def side_effects(system_prompt, user_message, **kwargs):
            lane = kwargs.get("lane", "")
            if lane == "lane_a":
                return json.dumps(RESUME_JSON)
            elif lane == "lane_b":
                raise Exception("Cover letter API error")
            else:
                return json.dumps(PREP_JSON)

        agent.claude.generate = side_effects

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

        assert result["cover_letter"] is None
        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_lane_c_failure_is_degraded(self, tmp_path):
        agent = make_writer(tmp_path)

        async def side_effects(system_prompt, user_message, **kwargs):
            lane = kwargs.get("lane", "")
            if lane == "lane_a":
                return json.dumps(RESUME_JSON)
            elif lane == "lane_b":
                return json.dumps(COVER_LETTER_JSON)
            else:
                raise Exception("Prep API error")

        agent.claude.generate = side_effects

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

        assert result["interview_prep"] is None
        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_both_degraded_lanes_still_passes(self, tmp_path):
        agent = make_writer(tmp_path)

        async def side_effects(system_prompt, user_message, **kwargs):
            lane = kwargs.get("lane", "")
            if lane == "lane_a":
                return json.dumps(RESUME_JSON)
            raise Exception("degraded lane error")

        agent.claude.generate = side_effects

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

        assert result["resume"] is not None
        assert result["degraded"] is True

    @pytest.mark.asyncio
    async def test_creates_output_dir(self, tmp_path):
        agent = make_writer(tmp_path)
        agent.claude.generate = AsyncMock(side_effect=[
            json.dumps(RESUME_JSON),
            json.dumps(COVER_LETTER_JSON),
            json.dumps(PREP_JSON),
        ])

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

        out = Path(result["output_dir"])
        assert out.exists()
        assert (out / "job_details.md").exists()

    @pytest.mark.asyncio
    async def test_high_score_goes_to_best_match(self, tmp_path):
        agent = make_writer(tmp_path)
        job = {**SAMPLE_JOB, "score": 82}
        agent.claude.generate = AsyncMock(side_effect=[
            json.dumps(RESUME_JSON),
            json.dumps(COVER_LETTER_JSON),
            json.dumps(PREP_JSON),
        ])

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(job, SAMPLE_PROFILE)

        assert "Best_Match" in result["output_dir"]

    @pytest.mark.asyncio
    async def test_low_score_goes_to_possible_match(self, tmp_path):
        agent = make_writer(tmp_path)
        job = {**SAMPLE_JOB, "score": 55}
        agent.claude.generate = AsyncMock(side_effect=[
            json.dumps(RESUME_JSON),
            json.dumps(COVER_LETTER_JSON),
            json.dumps(PREP_JSON),
        ])

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(job, SAMPLE_PROFILE)

        assert "Possible_Match" in result["output_dir"]

    @pytest.mark.asyncio
    async def test_backup_on_existing_resume(self, tmp_path):
        agent = make_writer(tmp_path)
        job = {**SAMPLE_JOB, "score": 82}

        out_dir = agent._make_output_dir(job)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tailored_resume.docx").write_bytes(b"old resume")

        agent.claude.generate = AsyncMock(side_effect=[
            json.dumps(RESUME_JSON),
            json.dumps(COVER_LETTER_JSON),
            json.dumps(PREP_JSON),
        ])

        with patch("agents.writer_agent._generate_docx"):
            await agent.run(job, SAMPLE_PROFILE)

        assert (out_dir / "v1_resume.docx").exists()

    @pytest.mark.asyncio
    async def test_fix_mode_calls_lane_a_fix(self, tmp_path):
        agent = make_writer(tmp_path)
        fix_instructions = {
            "resume_fixes": [{"location": "skills", "issue": "Missing Python", "fix": "Add Python"}]
        }
        agent.claude.generate = AsyncMock(return_value=json.dumps(RESUME_JSON))

        out_dir = agent._make_output_dir(SAMPLE_JOB)
        out_dir.mkdir(parents=True, exist_ok=True)

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE, fix_instructions=fix_instructions)

        agent.claude.generate.assert_called_once()
        call_kwargs = agent.claude.generate.call_args[1]
        assert call_kwargs.get("lane") == "lane_a_fix"
        assert result["resume"] is not None

    @pytest.mark.asyncio
    async def test_fix_mode_backs_up_existing_resume(self, tmp_path):
        agent = make_writer(tmp_path)
        fix_instructions = {"resume_fixes": []}

        out_dir = agent._make_output_dir(SAMPLE_JOB)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "tailored_resume.docx").write_bytes(b"old")

        agent.claude.generate = AsyncMock(return_value=json.dumps(RESUME_JSON))

        with patch("agents.writer_agent._generate_docx"):
            await agent.run(SAMPLE_JOB, SAMPLE_PROFILE, fix_instructions=fix_instructions)

        assert (out_dir / "v1_resume.docx").exists()

    @pytest.mark.asyncio
    async def test_writes_job_details_and_match_report(self, tmp_path):
        agent = make_writer(tmp_path)
        agent.claude.generate = AsyncMock(side_effect=[
            json.dumps(RESUME_JSON),
            json.dumps(COVER_LETTER_JSON),
            json.dumps(PREP_JSON),
        ])

        with patch("agents.writer_agent._generate_docx"):
            result = await agent.run(SAMPLE_JOB, SAMPLE_PROFILE)

        out = Path(result["output_dir"])
        assert (out / "job_details.md").read_text().startswith("# Senior Software Engineer @ Acme Corp")
        assert (out / "match_report.md").exists()
