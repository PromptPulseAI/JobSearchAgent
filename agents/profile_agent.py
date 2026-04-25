"""
Profile Agent — resume and skills parser.
Reads: Input_Files/master_resume.docx + Skills/*.docx + Input_Files/job_requirements.docx
Writes: data/candidate_profile.json
Token cost: ~2,000 (Claude API, once per run)

Full implementation: Commit 4
"""
from pathlib import Path
from typing import Any, Dict

from agents.base_agent import BaseAgent


class ProfileAgent(BaseAgent):
    name = "profile_agent"

    async def run(self) -> Dict[str, Any]:
        """
        Parse input files and return structured candidate profile.
        Output written to data/candidate_profile.json by orchestrator.
        """
        # TODO(Commit 4):
        #   1. Read master_resume.docx via docx_reader
        #   2. Read all Skills/*.docx files
        #   3. Read job_requirements.docx (if exists)
        #   4. Call Claude API with profile_agent.txt system prompt + resume text
        #      (max_tokens=2000, temperature=0.1, cache system prompt)
        #   5. Parse and validate JSON response
        #   6. Return candidate_profile dict
        raise NotImplementedError("ProfileAgent not yet implemented — see Commit 4")
