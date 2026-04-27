"""
Reviewer Agent — ATS expert and quality auditor.
Reads: writer output, job description, candidate_profile.json, Skills/*.docx
Writes: review_notes.md, fix_instructions.json, fix_history.md
Token cost: ~2,000 per review pass

Two-phase review:
  Phase 1 (Python): ATS keyword scan, format validation, skills cross-reference
  Phase 2 (Claude): Story alignment, tone, claim verification, quantification
NEVER writes or rewrites resume/cover letter content.

Full implementation: Commit 8
"""
from typing import Any, Dict, Optional

from agents.base_agent import BaseAgent


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
        Review writer output for ATS compliance and content quality.
        Returns: {"passed": bool, "review_notes": str, "fix_instructions": dict | None, "score": int}
        """
        # TODO(Commit 8):
        #   Phase 1 (pure Python, free):
        #     - ats_scanner.compute_coverage() on resume vs job keywords
        #     - format_validator.validate_resume()
        #     - Cross-reference claimed skills vs Skills/*.docx
        #   Phase 2 (Claude API):
        #     - Story alignment, tone check, claim verification
        #     - max_tokens=1500, temp=0.1, cache system prompt + candidate profile
        #   If Phase 1 fails: write fix_instructions.json, return passed=False
        #   Always write review_notes.md and append to fix_history.md
        raise NotImplementedError("ReviewerAgent not yet implemented — see Commit 8")
