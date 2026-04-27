"""
Writer Agent — resume writer and career content specialist.
Reads: candidate_profile.json, master_resume.docx, Skills/*.docx, one job entry
Writes per job folder: tailored_resume.docx, cover_letter.docx, interview_prep.md,
                       job_details.md, match_report.md, v{N}_resume.docx (backups)
Token cost: ~8,000 per job (initial); ~1,000 per fix attempt

Three parallel asyncio lanes per job:
  Lane A (resume)        — critical: WriterAgentError on failure
  Lane B (cover letter)  — degraded: log warning, continue
  Lane C (interview prep)— degraded: log warning, continue
"""
import asyncio
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from utils.exceptions import DocxGenerationError, WriterAgentError
from utils.file_io import write_json


class WriterAgent(BaseAgent):
    name = "writer_agent"

    async def run(
        self,
        job: Dict[str, Any],
        candidate_profile: Dict[str, Any],
        fix_instructions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate resume, cover letter, and interview prep for one job.
        If fix_instructions provided, apply targeted fixes only.
        Returns paths dict: {output_dir, resume, cover_letter, interview_prep, degraded}
        """
        job_id = job.get("job_id", "unknown")
        output_dir = self._make_output_dir(job)
        output_dir.mkdir(parents=True, exist_ok=True)

        self.log("INFO", f"Writing documents for {job.get('title')} @ {job.get('company')}", job_id=job_id)

        # Write job_details.md (always, free)
        self._write_job_details(job, output_dir)

        if fix_instructions:
            return await self._apply_fixes(job, candidate_profile, fix_instructions, output_dir)

        # Backup existing resume before fresh generation (version backup)
        existing_resume = output_dir / "tailored_resume.docx"
        if existing_resume.exists():
            _backup_resume(existing_resume, output_dir)

        # Run 3 lanes in parallel
        lane_a = self._lane_a_resume(job, candidate_profile, output_dir, job_id)
        lane_b = self._lane_b_cover_letter(job, candidate_profile, output_dir, job_id)
        lane_c = self._lane_c_interview_prep(job, candidate_profile, output_dir, job_id)

        results = await asyncio.gather(lane_a, lane_b, lane_c, return_exceptions=True)
        resume_path, cover_path, prep_path = results

        # Lane A is critical
        if isinstance(resume_path, Exception):
            raise WriterAgentError(
                f"Resume generation failed (Lane A): {resume_path}",
                job_id=job_id,
            )

        # Lanes B/C are degraded-mode
        if isinstance(cover_path, Exception):
            self.log("WARNING", f"Cover letter failed (degraded): {cover_path}", job_id=job_id)
            cover_path = None
        if isinstance(prep_path, Exception):
            self.log("WARNING", f"Interview prep failed (degraded): {prep_path}", job_id=job_id)
            prep_path = None

        degraded = cover_path is None or prep_path is None
        if degraded:
            self.log("WARNING", "Running in degraded mode — some outputs missing", job_id=job_id)

        self._write_match_report(job, output_dir)
        self.audit("write", "writer_output", "success", job_id=job_id)

        return {
            "output_dir": str(output_dir),
            "resume": str(resume_path) if resume_path else None,
            "cover_letter": str(cover_path) if cover_path else None,
            "interview_prep": str(prep_path) if prep_path else None,
            "degraded": degraded,
        }

    # ── Lane A: Resume ────────────────────────────────────────────────────────

    async def _lane_a_resume(
        self, job: Dict, profile: Dict, output_dir: Path, job_id: str
    ) -> Path:
        system_prompt = self.load_prompt("writer_resume.txt")
        user_msg = _build_resume_prompt(job, profile)

        llm_cfg = self.config.get("llm", {}).get("api_params", {}).get("resume_tailoring", {})
        raw = await self.claude.generate(
            system_prompt=system_prompt,
            user_message=user_msg,
            max_tokens=llm_cfg.get("max_tokens", 4000),
            temperature=llm_cfg.get("temperature", 0.3),
            agent=self.name,
            job_id=job_id,
            lane="lane_a",
            cache_system_prompt=True,
        )

        resume_data = _parse_json_response(raw, context="resume")
        docx_path = output_dir / "tailored_resume.docx"
        _generate_docx({"type": "resume", "content": resume_data}, docx_path)
        self.log("INFO", "Lane A: resume generated", job_id=job_id)
        return docx_path

    # ── Lane B: Cover Letter ──────────────────────────────────────────────────

    async def _lane_b_cover_letter(
        self, job: Dict, profile: Dict, output_dir: Path, job_id: str
    ) -> Path:
        system_prompt = self.load_prompt("writer_cover_letter.txt")
        user_msg = _build_cover_letter_prompt(job, profile)

        llm_cfg = self.config.get("llm", {}).get("api_params", {}).get("cover_letter", {})
        raw = await self.claude.generate(
            system_prompt=system_prompt,
            user_message=user_msg,
            max_tokens=llm_cfg.get("max_tokens", 2000),
            temperature=llm_cfg.get("temperature", 0.4),
            agent=self.name,
            job_id=job_id,
            lane="lane_b",
            cache_system_prompt=True,
        )

        cl_data = _parse_json_response(raw, context="cover_letter")
        docx_path = output_dir / "cover_letter.docx"
        _generate_docx({"type": "cover_letter", "content": cl_data}, docx_path)
        self.log("INFO", "Lane B: cover letter generated", job_id=job_id)
        return docx_path

    # ── Lane C: Interview Prep ────────────────────────────────────────────────

    async def _lane_c_interview_prep(
        self, job: Dict, profile: Dict, output_dir: Path, job_id: str
    ) -> Path:
        system_prompt = self.load_prompt("writer_interview_prep.txt")
        user_msg = _build_prep_prompt(job, profile)

        llm_cfg = self.config.get("llm", {}).get("api_params", {}).get("interview_prep", {})
        raw = await self.claude.generate(
            system_prompt=system_prompt,
            user_message=user_msg,
            max_tokens=llm_cfg.get("max_tokens", 1500),
            temperature=llm_cfg.get("temperature", 0.7),
            agent=self.name,
            job_id=job_id,
            lane="lane_c",
            cache_system_prompt=True,
        )

        prep_data = _parse_json_response(raw, context="interview_prep")
        md_path = output_dir / "interview_prep.md"
        md_path.write_text(_prep_to_markdown(prep_data), encoding="utf-8")
        self.log("INFO", "Lane C: interview prep generated", job_id=job_id)
        return md_path

    # ── Fix mode ──────────────────────────────────────────────────────────────

    async def _apply_fixes(
        self, job: Dict, profile: Dict, fix_instructions: Dict, output_dir: Path
    ) -> Dict[str, Any]:
        """Apply targeted fixes from reviewer. Backup resume first."""
        job_id = job.get("job_id", "unknown")
        existing = output_dir / "tailored_resume.docx"
        if existing.exists():
            _backup_resume(existing, output_dir)

        fix_prompt = _build_fix_prompt(job, profile, fix_instructions)
        system_prompt = self.load_prompt("writer_resume.txt")

        raw = await self.claude.generate(
            system_prompt=system_prompt,
            user_message=fix_prompt,
            max_tokens=4000,
            temperature=0.2,
            agent=self.name,
            job_id=job_id,
            lane="lane_a_fix",
        )

        resume_data = _parse_json_response(raw, context="resume_fix")
        docx_path = output_dir / "tailored_resume.docx"
        _generate_docx({"type": "resume", "content": resume_data}, docx_path)
        self.log("INFO", "Fix applied to resume", job_id=job_id)

        return {
            "output_dir": str(output_dir),
            "resume": str(docx_path),
            "cover_letter": str(output_dir / "cover_letter.docx") if (output_dir / "cover_letter.docx").exists() else None,
            "interview_prep": str(output_dir / "interview_prep.md") if (output_dir / "interview_prep.md").exists() else None,
            "degraded": False,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_output_dir(self, job: Dict) -> Path:
        output_root = Path(self.config.get("paths", {}).get("output_dir", "Output"))
        score = job.get("score", 0)
        best_threshold = self.config.get("scoring", {}).get("thresholds", {}).get("best_match", 75)
        tier = "Best_Match" if score >= best_threshold else "Possible_Match"

        slug = _slugify(f"{job.get('company', 'unknown')}_{job.get('title', 'job')}_{job.get('job_id', '')}")
        return output_root / tier / slug

    def _write_job_details(self, job: Dict, output_dir: Path) -> None:
        lines = [
            f"# {job.get('title', 'Unknown')} @ {job.get('company', 'Unknown')}",
            f"",
            f"**Score:** {job.get('score', 0):.0f}/100",
            f"**Location:** {job.get('location', 'N/A')}",
            f"**Employment Type:** {job.get('employment_type', 'N/A')}",
            f"**Posted:** {job.get('date_posted', 'N/A')}",
            f"**URL:** {job.get('url', 'N/A')}",
            f"",
            f"## Job Description",
            f"",
            job.get("job_description", ""),
        ]
        (output_dir / "job_details.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_match_report(self, job: Dict, output_dir: Path) -> None:
        breakdown = job.get("score_breakdown", {})
        lines = [
            f"# Match Report — {job.get('title')} @ {job.get('company')}",
            f"",
            f"**Total Score:** {job.get('score', 0):.0f}/100",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"",
            f"## Score Breakdown",
            f"",
        ]
        for criterion, weight in [
            ("core_skills_match", 0.35),
            ("title_seniority_alignment", 0.20),
            ("industry_domain_fit", 0.15),
            ("years_experience_fit", 0.15),
            ("nice_to_have_skills", 0.10),
            ("company_culture_signals", 0.05),
        ]:
            score = breakdown.get(criterion, 0)
            lines.append(f"- **{criterion.replace('_', ' ').title()}** ({int(weight*100)}%): {score}/100")

        if breakdown.get("reasoning"):
            lines += ["", f"**Reasoning:** {breakdown['reasoning']}"]

        (output_dir / "match_report.md").write_text("\n".join(lines), encoding="utf-8")


# ── Module-level helpers ──────────────────────────────────────────────────────

def _backup_resume(resume_path: Path, output_dir: Path) -> None:
    """Create a versioned backup: v1_resume.docx, v2_resume.docx, etc."""
    n = 1
    while (output_dir / f"v{n}_resume.docx").exists():
        n += 1
    resume_path.rename(output_dir / f"v{n}_resume.docx")


def _slugify(text: str) -> str:
    """Convert to a safe directory name."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s-]+", "_", text)
    return text[:80]


def _parse_json_response(raw: str, context: str = "") -> Dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise WriterAgentError(
            f"Invalid JSON from Claude ({context}): {exc}. Raw: {raw[:300]}"
        )


def _generate_docx(data: Dict[str, Any], output_path: Path) -> None:
    """
    Call Node.js docx_writer.js via subprocess to generate the .docx file.
    Falls back to writing a JSON stub if Node.js is unavailable.
    """
    import tempfile, os

    input_path = Path(tempfile.mktemp(suffix=".json"))
    try:
        input_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        result = subprocess.run(
            ["node", "utils/docx_writer.js", str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise DocxGenerationError(
                f"docx_writer.js failed (exit {result.returncode}): {result.stderr[:300]}"
            )
    except FileNotFoundError:
        # Node.js not installed — write a JSON stub so pipeline doesn't crash
        stub_path = output_path.with_suffix(".json")
        stub_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        output_path.write_bytes(b"STUB")  # placeholder .docx
    finally:
        if input_path.exists():
            input_path.unlink()


def _build_resume_prompt(job: Dict, profile: Dict) -> str:
    skills = [s["name"] for s in profile.get("skills", {}).get("technical", [])]
    exp = profile.get("experience_summary", [])
    exp_text = "\n".join(
        f"- {e.get('title')} @ {e.get('company')} ({e.get('years')}): "
        + "; ".join(e.get("highlights", []))
        for e in exp
    )
    return (
        f"## Target Job\n\nTitle: {job.get('title')}\nCompany: {job.get('company')}\n"
        f"Location: {job.get('location')}\n\n{job.get('job_description', '')[:3000]}\n\n"
        f"## Candidate Profile\n\nName: {profile.get('name', '')}\n"
        f"Years experience: {profile.get('years_experience', 0)}\n"
        f"Technical skills: {', '.join(skills)}\n"
        f"Industries: {', '.join(profile.get('industries', []))}\n\n"
        f"## Experience\n\n{exp_text}\n\n"
        f"## Education\n\n"
        + "\n".join(
            f"- {e.get('degree')} — {e.get('school')} ({e.get('year')})"
            for e in profile.get("education", [])
        )
    )


def _build_cover_letter_prompt(job: Dict, profile: Dict) -> str:
    skills = [s["name"] for s in profile.get("skills", {}).get("technical", [])]
    return (
        f"## Target Job\n\nTitle: {job.get('title')}\nCompany: {job.get('company')}\n"
        f"Location: {job.get('location')}\n\n{job.get('job_description', '')[:2000]}\n\n"
        f"## Company Context\n\n{json.dumps(job.get('company_context', {}))}\n\n"
        f"## Candidate Profile\n\nName: {profile.get('name', '')}\n"
        f"Years experience: {profile.get('years_experience', 0)}\n"
        f"Top skills: {', '.join(skills[:8])}\n"
        f"Keywords: {', '.join(profile.get('keywords', []))}"
    )


def _build_prep_prompt(job: Dict, profile: Dict) -> str:
    skills = [s["name"] for s in profile.get("skills", {}).get("technical", [])]
    return (
        f"## Target Job\n\nTitle: {job.get('title')}\nCompany: {job.get('company')}\n\n"
        f"{job.get('job_description', '')[:2000]}\n\n"
        f"## Candidate Profile\n\nYears experience: {profile.get('years_experience', 0)}\n"
        f"Technical skills: {', '.join(skills)}\n"
        f"Industries: {', '.join(profile.get('industries', []))}\n\n"
        f"## Experience Highlights\n\n"
        + "\n".join(
            f"- {e.get('title')} @ {e.get('company')}: " + "; ".join(e.get("highlights", []))
            for e in profile.get("experience_summary", [])
        )
    )


def _build_fix_prompt(job: Dict, profile: Dict, fix_instructions: Dict) -> str:
    base = _build_resume_prompt(job, profile)
    fixes = json.dumps(fix_instructions.get("resume_fixes", []), indent=2)
    return (
        f"{base}\n\n"
        f"## Fix Instructions\n\n"
        f"Apply ONLY these targeted fixes to the resume. Do not change anything else:\n\n{fixes}"
    )


def _prep_to_markdown(data: Dict) -> str:
    """Convert interview prep JSON to readable markdown."""
    lines = ["# Interview Preparation Guide\n"]

    if cr := data.get("company_research"):
        lines.append("## Company Research\n")
        if what := cr.get("what_they_do"):
            lines.append(f"**What they do:** {what}\n")
        if ts := cr.get("tech_stack_signals"):
            lines.append(f"**Tech signals:** {', '.join(ts)}\n")
        if ktp := cr.get("key_talking_points"):
            lines.append("\n**Talking points:**")
            lines.extend(f"- {p}" for p in ktp)
        lines.append("")

    if ltq := data.get("likely_technical_questions"):
        lines.append("## Likely Technical Questions\n")
        for q in ltq:
            lines.append(f"### {q.get('question')}")
            lines.append(f"*Why asked:* {q.get('why_asked', '')}")
            lines.append(f"**Answer framework:** {q.get('answer_framework', '')}\n")

    if lbq := data.get("likely_behavioral_questions"):
        lines.append("## Likely Behavioral Questions\n")
        for q in lbq:
            lines.append(f"### {q.get('question')}")
            lines.append(f"**Answer framework:** {q.get('answer_framework', '')}\n")

    if ste := data.get("skills_to_emphasize"):
        lines.append(f"## Skills to Emphasize\n")
        lines.extend(f"- {s}" for s in ste)
        lines.append("")

    if gap := data.get("skills_gap_awareness"):
        lines.append("## Skills Gap — Prepare to Address\n")
        lines.extend(f"- {s}" for s in gap)
        lines.append("")

    if qta := data.get("questions_to_ask"):
        lines.append("## Questions to Ask\n")
        lines.extend(f"- {q}" for q in qta)

    return "\n".join(lines)
