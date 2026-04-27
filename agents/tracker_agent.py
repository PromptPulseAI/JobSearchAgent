"""
Tracker Agent — data clerk and metrics engine.
Reads: all agent outputs, user status updates from dashboard
Writes: application_tracker.json (atomic), run_history.json, master_summary.md,
        scoring_feedback.json
Token cost: ~200 (mostly pure Python file I/O)

NEVER generates creative content or makes subjective judgments.
All writes to application_tracker.json use atomic_write_json() with backup.

Full implementation: Commit 10
"""
from typing import Any, Dict, Optional

from agents.base_agent import BaseAgent


class TrackerAgent(BaseAgent):
    name = "tracker_agent"

    async def run(
        self,
        action: str,
        job: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        run_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Perform a tracker action. Valid actions:
          "record_job"   — add/update a job entry with given status
          "end_of_run"   — finalize metrics, flag follow-ups, archive, write summary
          "status_update"— user changed a job's status (from dashboard)
        """
        # TODO(Commit 10):
        #   record_job:
        #     - Dedup check (job_id + title + company)
        #     - Validate status transition (only forward transitions allowed)
        #     - atomic_write_json() with backup
        #     - Append to run_history.json
        #   end_of_run:
        #     - Flag Applied jobs >= 7 days old
        #     - Archive Rejected entries >= 30 days old
        #     - Compute conversion funnel metrics
        #     - Regenerate master_summary.md
        #     - Write scoring_feedback.json if user overrides happened
        #   status_update:
        #     - Validate new status is a valid transition
        #     - Record in scoring_feedback.json if it's an override signal
        raise NotImplementedError("TrackerAgent not yet implemented — see Commit 10")
