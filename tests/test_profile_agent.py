"""Tests for agents/profile_agent.py — resume parsing and profile extraction."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.profile_agent import (
    ProfileAgent,
    _build_user_message,
    _merge_config_preferences,
    _parse_json_response,
)
from utils.exceptions import ProfileAgentError


# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_PROFILE_JSON = {
    "name": "Jane Smith",
    "target_titles": ["Senior Software Engineer", "Lead Engineer"],
    "years_experience": 8,
    "skills": {
        "technical": [
            {"name": "Python", "years": 8, "proficiency": "expert"},
            {"name": "AWS", "years": 5, "proficiency": "advanced"},
        ],
        "soft": [{"name": "Team Leadership", "years": 3}],
        "certifications": [],
    },
    "industries": ["fintech", "saas"],
    "education": [{"degree": "BS Computer Science", "school": "Test U", "year": 2018}],
    "keywords": ["microservices", "REST API", "CI/CD"],
    "experience_summary": [
        {
            "title": "Senior Software Engineer",
            "company": "Acme",
            "years": "2020-2026",
            "highlights": ["Built microservices on AWS"],
        }
    ],
    "preferences": {
        "seniority": ["senior", "lead"],
        "employment_types": ["full-time"],
        "location": "anywhere_us",
        "arrangement": "remote",
    },
}

MINIMAL_CONFIG = {
    "paths": {
        "input_dir": "Input_Files",
        "skills_dir": "Skills",
        "data_dir": "data",
        "prompts_dir": "prompts",
    },
    "llm": {
        "api_params": {
            "profile_extraction": {"max_tokens": 2000, "temperature": 0.1}
        }
    },
    "candidate": {
        "seniority": ["senior", "lead"],
        "employment_types": ["full-time", "contract"],
        "location": "anywhere_us",
        "work_arrangement": "all",
    },
}


@pytest.fixture
def mock_claude():
    client = MagicMock()
    client.generate = AsyncMock(return_value=json.dumps(VALID_PROFILE_JSON))
    return client


@pytest.fixture
def agent(mock_claude):
    return ProfileAgent(config=MINIMAL_CONFIG, claude_client=mock_claude)


# ── _build_user_message ───────────────────────────────────────────────────────

class TestBuildUserMessage:
    def test_includes_resume(self):
        msg = _build_user_message("my resume", "", "")
        assert "my resume" in msg

    def test_includes_skills_when_present(self):
        msg = _build_user_message("resume", "Python skills", "")
        assert "Python skills" in msg
        assert "Skills Documents" in msg

    def test_excludes_skills_section_when_empty(self):
        msg = _build_user_message("resume", "", "")
        assert "Skills Documents" not in msg

    def test_includes_requirements_when_present(self):
        msg = _build_user_message("resume", "", "Senior remote roles only")
        assert "Senior remote roles only" in msg
        assert "Job Requirements" in msg

    def test_excludes_requirements_section_when_empty(self):
        msg = _build_user_message("resume", "", "")
        assert "Job Requirements" not in msg


# ── _parse_json_response ──────────────────────────────────────────────────────

class TestParseJsonResponse:
    def test_parses_plain_json(self):
        raw = json.dumps(VALID_PROFILE_JSON)
        result = _parse_json_response(raw)
        assert result["name"] == "Jane Smith"

    def test_parses_json_in_code_fence(self):
        raw = f"```json\n{json.dumps(VALID_PROFILE_JSON)}\n```"
        result = _parse_json_response(raw)
        assert result["years_experience"] == 8

    def test_parses_json_in_plain_fence(self):
        raw = f"```\n{json.dumps(VALID_PROFILE_JSON)}\n```"
        result = _parse_json_response(raw)
        assert "skills" in result

    def test_raises_on_invalid_json(self):
        with pytest.raises(ProfileAgentError, match="invalid JSON"):
            _parse_json_response("not json at all")

    def test_raises_on_missing_required_fields(self):
        incomplete = {"name": "Jane"}  # missing target_titles, years_experience, skills
        with pytest.raises(ProfileAgentError, match="missing required fields"):
            _parse_json_response(json.dumps(incomplete))

    def test_raises_when_skills_not_dict(self):
        bad = {**VALID_PROFILE_JSON, "skills": ["python", "aws"]}
        with pytest.raises(ProfileAgentError, match="skills.*dict"):
            _parse_json_response(json.dumps(bad))


# ── _merge_config_preferences ─────────────────────────────────────────────────

class TestMergeConfigPreferences:
    def test_config_seniority_overwrites_profile(self):
        profile = {**VALID_PROFILE_JSON, "preferences": {"seniority": ["junior"]}}
        cfg = {"candidate": {"seniority": ["senior", "lead"]}}
        result = _merge_config_preferences(profile, cfg)
        assert result["preferences"]["seniority"] == ["senior", "lead"]

    def test_config_employment_types_applied(self):
        profile = {**VALID_PROFILE_JSON}
        cfg = {"candidate": {"employment_types": ["contract", "c2c"]}}
        result = _merge_config_preferences(profile, cfg)
        assert result["preferences"]["employment_types"] == ["contract", "c2c"]

    def test_no_candidate_config_leaves_profile_unchanged(self):
        profile = {**VALID_PROFILE_JSON}
        original_prefs = dict(profile["preferences"])
        result = _merge_config_preferences(profile, {})
        assert result["preferences"] == original_prefs

    def test_work_arrangement_mapped_to_arrangement_key(self):
        profile = {**VALID_PROFILE_JSON}
        cfg = {"candidate": {"work_arrangement": "remote"}}
        result = _merge_config_preferences(profile, cfg)
        assert result["preferences"]["arrangement"] == "remote"


# ── ProfileAgent.run() ────────────────────────────────────────────────────────

class TestProfileAgentRun:
    async def test_run_returns_profile_dict(self, agent, tmp_path):
        cfg = {**MINIMAL_CONFIG, "paths": {**MINIMAL_CONFIG["paths"], "data_dir": str(tmp_path)}}

        with patch.object(agent, "load_prompt", return_value="system prompt"):
            with patch.object(agent, "_read_resume", return_value="resume text"):
                with patch.object(agent, "_read_skills", return_value="skills text"):
                    with patch.object(agent, "_read_requirements", return_value=""):
                        result = await agent.run(config=cfg)

        assert result["name"] == "Jane Smith"
        assert result["years_experience"] == 8

    async def test_run_writes_profile_to_disk(self, agent, tmp_path):
        cfg = {**MINIMAL_CONFIG, "paths": {**MINIMAL_CONFIG["paths"], "data_dir": str(tmp_path)}}

        with patch.object(agent, "load_prompt", return_value="sys"):
            with patch.object(agent, "_read_resume", return_value="r"):
                with patch.object(agent, "_read_skills", return_value=""):
                    with patch.object(agent, "_read_requirements", return_value=""):
                        await agent.run(config=cfg)

        profile_file = tmp_path / "candidate_profile.json"
        assert profile_file.exists()
        saved = json.loads(profile_file.read_text())
        assert saved["name"] == "Jane Smith"

    async def test_run_raises_profile_agent_error_on_api_failure(self, agent, tmp_path):
        cfg = {**MINIMAL_CONFIG, "paths": {**MINIMAL_CONFIG["paths"], "data_dir": str(tmp_path)}}
        agent.claude.generate = AsyncMock(side_effect=Exception("API down"))

        with patch.object(agent, "load_prompt", return_value="sys"):
            with patch.object(agent, "_read_resume", return_value="r"):
                with patch.object(agent, "_read_skills", return_value=""):
                    with patch.object(agent, "_read_requirements", return_value=""):
                        with pytest.raises(ProfileAgentError, match="Claude API call failed"):
                            await agent.run(config=cfg)

    async def test_run_raises_when_resume_missing(self, agent, tmp_path):
        cfg = {**MINIMAL_CONFIG, "paths": {**MINIMAL_CONFIG["paths"], "data_dir": str(tmp_path)}}

        with patch.object(agent, "load_prompt", return_value="sys"):
            with pytest.raises(ProfileAgentError, match="master_resume.docx not found"):
                await agent.run(config=cfg)

    async def test_config_preferences_applied_to_output(self, agent, tmp_path):
        cfg = {
            **MINIMAL_CONFIG,
            "paths": {**MINIMAL_CONFIG["paths"], "data_dir": str(tmp_path)},
            "candidate": {"seniority": ["principal"], "employment_types": ["full-time"]},
        }

        with patch.object(agent, "load_prompt", return_value="sys"):
            with patch.object(agent, "_read_resume", return_value="r"):
                with patch.object(agent, "_read_skills", return_value=""):
                    with patch.object(agent, "_read_requirements", return_value=""):
                        result = await agent.run(config=cfg)

        assert result["preferences"]["seniority"] == ["principal"]

    async def test_claude_called_with_correct_params(self, agent, tmp_path):
        cfg = {**MINIMAL_CONFIG, "paths": {**MINIMAL_CONFIG["paths"], "data_dir": str(tmp_path)}}

        with patch.object(agent, "load_prompt", return_value="test system prompt"):
            with patch.object(agent, "_read_resume", return_value="resume text"):
                with patch.object(agent, "_read_skills", return_value="skills"):
                    with patch.object(agent, "_read_requirements", return_value=""):
                        await agent.run(config=cfg)

        call_kwargs = agent.claude.generate.call_args[1]
        assert call_kwargs["system_prompt"] == "test system prompt"
        assert call_kwargs["max_tokens"] == 2000
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["cache_system_prompt"] is True
        assert call_kwargs["agent"] == "profile_agent"
