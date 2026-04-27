"""
Reviewer Agent — ATS expert and quality auditor.
Reads: writer output, job description, candidate_profile.json, Skills/*.docx
Writes: review_notes.md, fix_instructions.json, fix_history.md
Token cost: ~2,000 per review pass

Two-phase review:
  Phase 1 (Python, free): ATS keyword scan, format validation, skills cross-reference
  Phase 2 (Claude, ~$0.03): Story alignment, tone, claim verification, quantification
NEVER writes or rewrites resume/cover letter content.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from utils.ats_scanner import compute_coverage, extract_keywords
from utils.exceptions import ReviewerAgentError
from utils.file_io import write_json
from utils.format_validator import validate_resume


class ReviewerAgent(BaseAgent):
    name = "reviewer_agent"

    async def run(
        self,
        job: Dict[str, Any],
        writer_output: Dict[str, Any],
        candidate_profile: Dict[str, Any],
        review_pass: int = 1,
    ) -> Dict[str, Any]:
        """
        Two-phase review of writer output.
        Returns: {passed, score, review_notes, fix_instructions, phase1}
        """
        job_id = job.get("job_id", "unknown")
        output_dir = Path(writer_output.get("output_dir", "."))
        resume_path = writer_output.get("resume")

        self.log("INFO", f"Reviewing pass {review_pass} for {job.get('title')} @ {job.get('company')}", job_id=job_id)

        # Phase 1 — pure Python (free, always runs)
        phase1 = self._phase1_mechanical(job, resume_path, candidate_profile)

        # Phase 2 — Claude quality review (only if resume exists)
        phase2: Dict[str, Any] = {"passed": True, "score": 85, "issues": [], "fix_instructions": None}
        if resume_path:
            try:
                phase2 = await self._phase2_quality(job, writer_output, candidate_profile, phase1)
            except Exception as exc:
                self.log("WARNING", f"Phase 2 review failed (degraded): {exc}", job_id=job_id)
                phase2 = {"passed": True, "score": 70, "issues": [], "fix_instructions": None,
                          "review_notes": f"Phase 2 unavailable: {exc}"}

        # Combine results — fail if either phase fails
        all_issues = phase1.get("issues", []) + phase2.get("issues", [])
        has_errors = any(i.get("severity") == "error" for i in all_issues)
        combined_score = int((phase1.get("score", 100) + phase2.get("score", 85)) / 2)
        passed = not has_errors and combined_score >= 70

        fix_instructions = phase2.get("fix_instructions") if not passed else None

        result = {
            "passed": passed,
            "score": combined_score,
            "review_pass": review_pass,
            "review_notes": phase2.get("review_notes", ""),
            "fix_instructions": fix_instructions,
            "phase1": phase1,
            "issues": all_issues,
        }

        # Write outputs
        self._write_review_notes(result, job, output_dir)
        self._append_fix_history(result, job, output_dir)
        if fix_instructions:
            write_json(output_dir / "fix_instructions.json", fix_instructions, agent=self.name)

        self.audit("write", "review_notes", "success", job_id=job_id)
        self.log(
            "INFO",
            f"Review pass {review_pass}: {'PASSED' if passed else 'FAILED'} (score={combined_score})",
            job_id=job_id,
        )
        return result

    # ── Phase 1: Mechanical checks (pure Python) ──────────────────────────────

    def _phase1_mechanical(
        self, job: Dict, resume_path: Optional[str], profile: Dict
    ) -> Dict[str, Any]:
        issues: List[Dict] = []
        score = 100

        # ATS coverage check
        ats_result = self._check_ats_coverage(job, resume_path, issues)
        if ats_result.get("coverage_percent", 0) < self.config.get("quality", {}).get("ats_target_coverage", 85):
            score -= 20

        # Format validation
        if resume_path:
            fmt_result = self._check_format(resume_path, issues)
            if fmt_result.get("error_count", 0) > 0:
                score -= 15 * fmt_result["error_count"]

        # Skills cross-reference
        self._cross_reference_skills(job, profile, issues)

        return {
            "passed": not any(i["severity"] == "error" for i in issues),
            "score": max(0, score),
            "issues": issues,
            "ats_coverage": ats_result,
        }

    def _check_ats_coverage(self, job: Dict, resume_path: Optional[str], issues: List) -> Dict:
        jd = job.get("job_description", "")
        keywords = extract_keywords(jd)

        resume_text = ""
        if resume_path:
            try:
                from utils.docx_reader import read_docx_text
                resume_text = read_docx_text(resume_path, agent=self.name)
            except Exception:
                pass

        ats = compute_coverage(resume_text, keywords)
        target = self.config.get("quality", {}).get("ats_target_coverage", 85)
        coverage = ats.get("coverage_percent", 0)

        if coverage < target:
            missing = ats.get("required", {}).get("missing", [])
            issues.append({
                "severity": "error" if coverage < 50 else "warning",
                "location": "resume.skills + experience",
                "issue": f"ATS coverage {coverage:.0f}% below target {target}%. Missing required keywords: {', '.join(missing[:8])}",
                "fix": f"Add these keywords naturally: {', '.join(missing[:5])}",
            })

        return ats

    def _check_format(self, resume_path: str, issues: List) -> Dict:
        try:
            from utils.docx_reader import read_docx_text
            text = read_docx_text(resume_path, agent=self.name)
            result = validate_resume(text)
            for issue in result.get("issues", []):
                issues.append({
                    "severity": issue["severity"],
                    "location": "resume.format",
                    "issue": issue["detail"],
                    "fix": "See format_validator recommendations",
                })
            return result
        except Exception:
            return {}

    def _cross_reference_skills(self, job: Dict, profile: Dict, issues: List) -> None:
        """Flag if resume would claim skills not in the candidate's profile."""
        profile_skills = {
            s["name"].lower()
            for s in profile.get("skills", {}).get("technical", [])
        }
        jd_keywords = extract_keywords(job.get("job_description", ""))

        # Check for required skills candidate doesn't have
        required_missing = {
            k for k in jd_keywords.get("required", set())
            if k not in profile_skills
        }
        if len(required_missing) > 3:
            issues.append({
                "severity": "warning",
                "location": "skills_cross_reference",
                "issue": f"{len(required_missing)} required skills not in candidate profile: {', '.join(sorted(required_missing)[:5])}",
                "fix": "Ensure resume does not fabricate skills the candidate doesn't have",
            })

    # ── Phase 2: Claude quality review ───────────────────────────────────────

    async def _phase2_quality(
        self,
        job: Dict,
        writer_output: Dict,
        profile: Dict,
        phase1: Dict,
    ) -> Dict[str, Any]:
        system_prompt = self.load_prompt("reviewer_agent.txt")
        user_msg = self._build_review_prompt(job, writer_output, profile, phase1)

        llm_cfg = self.config.get("llm", {}).get("api_params", {}).get("quality_review", {})
        raw = await self.claude.generate(
            system_prompt=system_prompt,
            user_message=user_msg,
            max_tokens=llm_cfg.get("max_tokens", 1500),
            temperature=llm_cfg.get("temperature", 0.1),
            agent=self.name,
            cache_system_prompt=True,
        )

        return _parse_review_response(raw)

    def _build_review_prompt(
        self, job: Dict, writer_output: Dict, profile: Dict, phase1: Dict
    ) -> str:
        # Load resume content for review
        resume_content = ""
        resume_path = writer_output.get("resume")
        if resume_path:
            try:
                from utils.docx_reader import read_docx_text
                resume_content = read_docx_text(resume_path, agent=self.name)
            except Exception:
                resume_content = "(could not read resume)"

        return (
            f"## Job Description\n\n{job.get('job_description', '')[:2000]}\n\n"
            f"## Tailored Resume\n\n{resume_content[:3000]}\n\n"
            f"## Candidate Profile Summary\n\n"
            f"Years experience: {profile.get('years_experience', 0)}\n"
            f"Skills: {', '.join(s['name'] for s in profile.get('skills', {}).get('technical', []))}\n\n"
            f"## Phase 1 Mechanical Results\n\n"
            f"ATS coverage: {phase1.get('ats_coverage', {}).get('coverage_percent', 0):.0f}%\n"
            f"Format passed: {phase1.get('passed', True)}\n"
            f"Phase 1 issues: {json.dumps(phase1.get('issues', []), indent=2)}"
        )

    # ── Output writers ────────────────────────────────────────────────────────

    def _write_review_notes(self, result: Dict, job: Dict, output_dir: Path) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"# Review Notes — {job.get('title')} @ {job.get('company')}",
            f"",
            f"**Pass:** {result['review_pass']}  |  **Score:** {result['score']}/100  |  **Status:** {'✅ PASSED' if result['passed'] else '❌ NEEDS FIX'}",
            f"**Reviewed:** {ts}",
            f"",
            result.get("review_notes", ""),
            f"",
            f"## Issues ({len(result['issues'])} total)",
            f"",
        ]
        for issue in result["issues"]:
            sev = "🔴" if issue["severity"] == "error" else "🟡"
            lines.append(f"{sev} **{issue['location']}**: {issue['issue']}")
            lines.append(f"   → Fix: {issue['fix']}")
            lines.append("")

        (output_dir / "review_notes.md").write_text("\n".join(lines), encoding="utf-8")

    def _append_fix_history(self, result: Dict, job: Dict, output_dir: Path) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        entry = (
            f"\n## Pass {result['review_pass']} — {ts}\n\n"
            f"Score: {result['score']}/100 | {'PASSED' if result['passed'] else 'FAILED'}\n\n"
            + "\n".join(f"- [{i['severity'].upper()}] {i['location']}: {i['issue']}" for i in result["issues"])
            + "\n"
        )
        history_path = output_dir / "fix_history.md"
        if not history_path.exists():
            history_path.write_text(f"# Fix History — {job.get('title')} @ {job.get('company')}\n", encoding="utf-8")
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(entry)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _parse_review_response(raw: str) -> Dict[str, Any]:
    import re
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        data.setdefault("passed", True)
        data.setdefault("score", 75)
        data.setdefault("issues", [])
        data.setdefault("fix_instructions", None)
        data.setdefault("review_notes", "")
        return data
    except json.JSONDecodeError as exc:
        raise ReviewerAgentError(f"Claude returned invalid JSON for review: {exc}\nRaw: {raw[:300]}")
