"""
Writer Agent — resume writer and career content specialist.
Reads: candidate_profile.json, master_resume.docx, Skills/*.docx, one job entry
Writes (per job folder): tailored_resume.docx, cover_letter.docx, job_details.md,
       match_report.md, interview_prep.md, v{N}_resume.docx (backups)
Token cost: ~8,000 per job (initial); ~1,000 per fix attempt

Three parallel asyncio lanes per job (A: resume, B: cover letter, C: prep).
Applies targeted fixes from fix_instructions.json when in fix loop.
NEVER reviews its own output.

Full implementation: Commit 7
"""
from typing import Any, Dict, Optional

from agents.base_agent import BaseAgent


class WriterAgent(BaseAgent):
    name = "writer_agent"

    async def run(
        self,
        job: Dict[str, Any],
        candidate_profile: Dict[str, Any],
        fix_instructions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate resume, cover letter, and prep materials for one job.
        If fix_instructions is provided, apply targeted fixes only (no full regeneration).
        Returns paths dict: {"resume": Path, "cover_letter": Path, "prep": Path, ...}
        """
        # TODO(Commit 7):
        #   Lane A: tailor_resume() — Claude API, max_tokens=4000, temp=0.3
        #   Lane B: write_cover_letter() — Claude API + web search, max_tokens=2000, temp=0.4
        #   Lane C: generate_prep() — Claude API, max_tokens=1500, temp=0.7
        #   Run lanes with asyncio.gather(); Lane A failure is critical, B/C are degraded
        #   Validate .docx output; retry once on malformed; save v{N} backups before fixes
        raise NotImplementedError("WriterAgent not yet implemented — see Commit 7")
