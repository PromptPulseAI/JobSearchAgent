"""
Profile Agent — resume and skills parser.
Reads: Input_Files/master_resume.docx + Skills/*.docx + Input_Files/job_requirements.docx
Writes: data/candidate_profile.json
Token cost: ~2,000 (Claude API, once per run, system prompt cached)
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from utils.exceptions import FileIOError, ProfileAgentError
from utils.file_io import write_json


class ProfileAgent(BaseAgent):
    name = "profile_agent"

    async def run(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parse input files and return a structured candidate profile.
        Writes the profile to data/candidate_profile.json.
        """
        cfg = config or self.config
        paths = cfg.get("paths", {})
        input_dir = Path(paths.get("input_dir", "Input_Files"))
        skills_dir = Path(paths.get("skills_dir", "Skills"))
        data_dir = Path(paths.get("data_dir", "data"))

        self.log("INFO", "Starting profile extraction")

        # 1. Load system prompt
        system_prompt = self.load_prompt("profile_agent.txt")

        # 2. Read input documents
        resume_text = self._read_resume(input_dir)
        skills_text = self._read_skills(skills_dir)
        requirements_text = self._read_requirements(input_dir)

        # 3. Build extraction prompt
        user_message = _build_user_message(resume_text, skills_text, requirements_text)

        # 4. Call Claude API (max_tokens=2000, temp=0.1, system prompt cached)
        llm_params = cfg.get("llm", {}).get("api_params", {}).get("profile_extraction", {})
        try:
            raw_response = await self.claude.generate(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=llm_params.get("max_tokens", 2000),
                temperature=llm_params.get("temperature", 0.1),
                agent=self.name,
                cache_system_prompt=True,
            )
        except Exception as exc:
            raise ProfileAgentError(
                f"Claude API call failed during profile extraction: {exc}"
            ) from exc

        # 5. Parse and validate JSON response
        profile = _parse_json_response(raw_response)

        # 6. Merge candidate preferences from config (user overrides LLM defaults)
        profile = _merge_config_preferences(profile, cfg)

        # 7. Write to data/candidate_profile.json
        output_path = data_dir / "candidate_profile.json"
        try:
            write_json(output_path, profile, agent=self.name)
        except Exception as exc:
            raise ProfileAgentError(
                f"Failed to write candidate profile: {exc}"
            ) from exc

        self.audit("write", "profile", "success")
        n_skills = len(profile.get("skills", {}).get("technical", []))
        self.log("INFO", f"Profile extracted: {profile.get('name', 'unknown')}, {n_skills} technical skills")

        return profile

    # ── Private helpers ───────────────────────────────────────────────────────

    def _read_resume(self, input_dir: Path) -> str:
        from utils.docx_reader import read_docx_text
        resume_path = input_dir / "master_resume.docx"
        if not resume_path.exists():
            raise ProfileAgentError(
                f"master_resume.docx not found in {input_dir}. "
                "Add your resume to Input_Files/master_resume.docx and re-run."
            )
        try:
            text = read_docx_text(resume_path, agent=self.name)
            self.log("INFO", f"Read resume: {len(text)} chars")
            return text
        except Exception as exc:
            raise ProfileAgentError(f"Failed to read master_resume.docx: {exc}") from exc

    def _read_skills(self, skills_dir: Path) -> str:
        from utils.docx_reader import read_docx_text
        if not skills_dir.exists():
            return ""
        chunks: List[str] = []
        for docx_file in sorted(skills_dir.glob("*.docx")):
            try:
                text = read_docx_text(docx_file, agent=self.name)
                chunks.append(f"=== {docx_file.stem} ===\n{text}")
                self.log("INFO", f"Read skills file: {docx_file.name}")
            except Exception as exc:
                self.log("WARNING", f"Could not read {docx_file.name}: {exc}")
        return "\n\n".join(chunks)

    def _read_requirements(self, input_dir: Path) -> str:
        from utils.docx_reader import read_docx_text
        req_path = input_dir / "job_requirements.docx"
        if not req_path.exists():
            return ""
        try:
            text = read_docx_text(req_path, agent=self.name)
            self.log("INFO", f"Read job requirements: {len(text)} chars")
            return text
        except Exception as exc:
            self.log("WARNING", f"Could not read job_requirements.docx: {exc}")
            return ""


# ── Module-level helpers (pure functions, easier to test) ─────────────────────

def _build_user_message(resume_text: str, skills_text: str, requirements_text: str) -> str:
    parts = [f"## Master Resume\n\n{resume_text}"]
    if skills_text:
        parts.append(f"## Skills Documents\n\n{skills_text}")
    if requirements_text:
        parts.append(f"## Job Requirements / Preferences\n\n{requirements_text}")
    return "\n\n---\n\n".join(parts)


def _parse_json_response(raw: str) -> Dict[str, Any]:
    """
    Extract JSON from Claude's response. Handles both raw JSON and
    JSON wrapped in markdown code fences.
    """
    text = raw.strip()

    # Strip markdown code fence if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        profile = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileAgentError(
            f"Claude returned invalid JSON for profile extraction: {exc}\n"
            f"Raw response (first 500 chars): {raw[:500]}"
        )

    _validate_profile_schema(profile)
    return profile


def _validate_profile_schema(profile: Dict[str, Any]) -> None:
    """Raise ProfileAgentError if required top-level keys are missing."""
    required = {"target_titles", "years_experience", "skills"}
    missing = required - set(profile.keys())
    if missing:
        raise ProfileAgentError(
            f"Profile JSON missing required fields: {missing}. "
            "Check the profile_agent.txt system prompt."
        )
    if not isinstance(profile.get("skills"), dict):
        raise ProfileAgentError("Profile 'skills' field must be a dict")


def _merge_config_preferences(profile: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Overwrite LLM-inferred preferences with explicit config values.
    Config values are authoritative — the user set them intentionally.
    """
    candidate_cfg = config.get("candidate", {})
    if not candidate_cfg:
        return profile

    prefs = profile.setdefault("preferences", {})

    if "seniority" in candidate_cfg:
        prefs["seniority"] = candidate_cfg["seniority"]
    if "employment_types" in candidate_cfg:
        prefs["employment_types"] = candidate_cfg["employment_types"]
    if "location" in candidate_cfg:
        prefs["location"] = candidate_cfg["location"]
    if "work_arrangement" in candidate_cfg:
        prefs["arrangement"] = candidate_cfg["work_arrangement"]

    return profile
