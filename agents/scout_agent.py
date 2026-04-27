"""
Scout Agent — job market analyst.
Reads: candidate_profile.json, config.json, application_tracker.json, scoring_feedback.json
Writes: data/job_matches.json
Token cost: ~500 + local Ollama for scoring breakdown

Queries all active job sources via sources/registry.py.
Dedup, exclusion filter, and freshness boost are pure Python (zero tokens).

Full implementation: Commit 5
"""
from typing import Any, Dict

from agents.base_agent import BaseAgent


class ScoutAgent(BaseAgent):
    name = "scout_agent"

    async def run(self, candidate_profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search active job sources, score results, write job_matches.json.
        Returns job_matches dict (best_match, possible_match, not_matching groups).
        """
        # TODO(Commit 5):
        #   1. Load source registry (active sources from config)
        #   2. For each source: search_jobs() with retry
        #   3. Dedup against application_tracker.json (pure Python set lookup)
        #   4. Apply exclusion filters (pure Python if/else)
        #   5. Score each job via local Ollama (6 weighted criteria)
        #   6. Apply freshness boost (pure Python date arithmetic)
        #   7. Sort and group into best/possible/not_matching
        #   8. Read scoring_feedback.json to adjust heuristics (v1: log-only)
        #   9. Return grouped job_matches dict
        raise NotImplementedError("ScoutAgent not yet implemented — see Commit 5")
