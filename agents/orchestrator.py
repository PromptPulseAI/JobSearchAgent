"""
Orchestrator — daily job search pipeline coordinator.
Single entry point. Calls agents in sequence, manages both gates, enforces
rate limits, runs the writer→reviewer fix loop, and handles error fallbacks.
NEVER generates content, scores jobs, or writes documents.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from utils.exceptions import (
    AllSourcesFailedError,
    APIError,
    ConfigError,
    ConsentError,
    ProfileAgentError,
    RateLimitError,
    Severity,
    TrackerAgentError,
)
from utils.file_io import read_json, write_json
from utils.logger import run_log


class Orchestrator(BaseAgent):
    name = "orchestrator"

    def __init__(
        self,
        config_path: str = "config.json",
        dry_run: bool = False,
        skip_search: bool = False,
        target_job_id: Optional[str] = None,
        no_local_model: bool = False,
        skip_gate1_if_no_new: bool = False,
    ):
        self.config_path = config_path
        self.dry_run = dry_run
        self.skip_search = skip_search
        self.target_job_id = target_job_id
        self.no_local_model = no_local_model
        self.skip_gate1_if_no_new = skip_gate1_if_no_new

        # Load config first — everything else depends on it
        cfg = _load_and_validate_config(config_path)
        super().__init__(config=cfg)

        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize Claude client and local LLM based on flags and config."""
        from utils.api_client import ClaudeClient
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ConfigError("ANTHROPIC_API_KEY environment variable not set")

        rate_cfg = self.config.get("rate_limit", {})
        self.claude = ClaudeClient(
            api_key=api_key,
            max_concurrent=rate_cfg.get("max_concurrent_api_calls", 3),
            delay=rate_cfg.get("delay_between_jobs_ms", 2000) / 1000,
        )

        self.local = None
        if not self.no_local_model and self.config.get("llm", {}).get("use_local_model", True):
            from utils.local_llm import LocalLLM
            self.local = LocalLLM(self.config)

    # ── Main pipeline ─────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Daily run entry point. Coordinates the full 6-agent pipeline."""
        self.log("INFO", f"Daily run started — dry_run={self.dry_run}")
        run_summary: Dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
            "jobs_found": 0,
            "jobs_approved": 0,
            "jobs_completed": 0,
            "jobs_skipped": 0,
            "errors": [],
        }

        try:
            # Step 1: Profile Agent
            candidate_profile = await self._run_profile_agent()

            # Step 2: Scout Agent
            if not self.skip_search:
                job_matches = await self._run_scout_agent(candidate_profile)
            else:
                job_matches = self._load_existing_job_matches()

            all_jobs = (
                job_matches.get("best_match", [])
                + job_matches.get("possible_match", [])
            )
            run_summary["jobs_found"] = len(all_jobs)

            if self.target_job_id:
                all_jobs = [j for j in all_jobs if j.get("job_id") == self.target_job_id]

            # Step 3: Gate 1 — user approval
            approved_jobs = await self._gate1(all_jobs, job_matches)
            run_summary["jobs_approved"] = len(approved_jobs)

            if not approved_jobs:
                self.log("INFO", "No jobs approved at Gate 1 — run complete")
            else:
                # Step 4: Unload local LLM to free RAM before parallel API calls
                if self.local:
                    await self.local.unload()

                # Step 5: Process each approved job
                delay_s = self.config.get("rate_limit", {}).get("delay_between_jobs_ms", 2000) / 1000
                for job in approved_jobs:
                    success = await self._process_job(job, candidate_profile)
                    if success:
                        run_summary["jobs_completed"] += 1
                    else:
                        run_summary["jobs_skipped"] += 1
                    if len(approved_jobs) > 1:
                        await asyncio.sleep(delay_s)

                # Step 6: Reload local LLM
                if self.local:
                    await self.local.reload()

            # Step 7: End-of-run tracking
            await self._run_tracker("end_of_run", run_summary=run_summary)

        except (ProfileAgentError, ConsentError, ConfigError) as exc:
            self.log("ERROR", f"Fatal error — aborting run: {exc}")
            run_summary["errors"].append(exc.to_dict())
            raise
        except AllSourcesFailedError as exc:
            self.log("ERROR", f"All job sources failed: {exc}")
            run_summary["errors"].append(exc.to_dict())
            await self._run_tracker("end_of_run", run_summary=run_summary)

        run_summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.log("INFO", (
            f"Run complete — found {run_summary['jobs_found']}, "
            f"approved {run_summary['jobs_approved']}, "
            f"completed {run_summary['jobs_completed']}"
        ))

    # ── Agent runners ─────────────────────────────────────────────────────────

    async def _run_profile_agent(self) -> Dict[str, Any]:
        from agents.profile_agent import ProfileAgent
        agent = ProfileAgent(config=self.config, claude_client=self.claude, local_llm=self.local)
        if self.dry_run:
            self.log("INFO", "[dry-run] Skipping Profile Agent")
            return {}
        return await agent.run(config=self.config)

    async def _run_scout_agent(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        from agents.scout_agent import ScoutAgent
        agent = ScoutAgent(config=self.config, claude_client=self.claude, local_llm=self.local)
        if self.dry_run:
            self.log("INFO", "[dry-run] Skipping Scout Agent")
            return {"best_match": [], "possible_match": [], "not_matching": []}
        return await agent.run(profile)

    async def _process_job(self, job: Dict[str, Any], profile: Dict[str, Any]) -> bool:
        """Writer → Reviewer → fix loop → Gate 2 → Tracker for one job."""
        job_id = job.get("job_id", "unknown")
        self.log("INFO", f"Processing job: {job.get('title')} @ {job.get('company')}", job_id=job_id)

        # Record job as Discovered
        await self._run_tracker("record_job", job=job, status="Discovered")

        try:
            # Fix loop: Writer → Reviewer → fix (max 2 retries)
            writer_output = await self._fix_loop(job, profile)

            # Gate 2: ask user whether to continue
            if not await self._gate2(job, writer_output):
                self.log("INFO", "Gate 2: user skipped this job", job_id=job_id)
                return False

            await self._run_tracker("record_job", job=job, status="Tailored")
            self.log("INFO", f"Job complete: {job_id}", job_id=job_id)
            return True

        except Exception as exc:
            self.log("ERROR", f"Job processing failed for {job_id}: {exc}", job_id=job_id)
            await self._run_tracker("record_job", job=job, status="Rejected")
            return False

    async def _run_tracker(
        self,
        action: str,
        job: Optional[Dict] = None,
        status: Optional[str] = None,
        run_summary: Optional[Dict] = None,
    ) -> None:
        from agents.tracker_agent import TrackerAgent
        agent = TrackerAgent(config=self.config, claude_client=self.claude, local_llm=self.local)
        if self.dry_run:
            self.log("INFO", f"[dry-run] Skipping tracker action: {action}")
            return
        try:
            await agent.run(action=action, job=job, status=status, run_summary=run_summary)
        except TrackerAgentError as exc:
            self.log("ERROR", f"Tracker failed (action={action}): {exc}")

    # ── Gate 1 ────────────────────────────────────────────────────────────────

    async def _gate1(
        self, all_jobs: List[Dict], job_matches: Dict
    ) -> List[Dict[str, Any]]:
        """Present search results and collect user approval for each job."""
        if not all_jobs:
            self.log("INFO", "Gate 1: No new jobs to approve")
            return []

        if self.skip_gate1_if_no_new:
            self.log("INFO", "Gate 1: --skip-gate1-if-no-new set, auto-approving all jobs")
            return all_jobs

        if self.dry_run:
            self.log("INFO", "[dry-run] Gate 1: would present jobs for approval")
            return []

        # Write pending_approval.json for headless/dashboard mode
        pending = _build_pending_approval(all_jobs, job_matches)
        pending_path = Path(
            self.config.get("automation", {}).get("pending_approval_file", "data/pending_approval.json")
        )
        if not self.config.get("automation", {}).get("headless_mode", False):
            return await _gate1_cli(all_jobs, pending_path)
        else:
            write_json(pending_path, pending, agent=self.name)
            self.log("INFO", f"Gate 1 (headless): pending_approval.json written — {len(all_jobs)} jobs awaiting dashboard approval")
            return []

    # ── Gate 2 ────────────────────────────────────────────────────────────────

    async def _gate2(self, job: Dict, writer_output: Dict) -> bool:
        """Ask user whether to continue to next job. Returns True to continue."""
        if self.dry_run or self.skip_gate1_if_no_new:
            return True

        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        print(f"\n{'='*60}")
        print(f"Gate 2 — Output ready for: {title} @ {company}")
        print(f"Output folder: {writer_output.get('output_dir', 'N/A')}")
        print(f"{'='*60}")

        answer = input("Continue to next job? [Y/n]: ").strip().lower()
        return answer in ("", "y", "yes")

    # ── Fix loop (Commit 9 full implementation) ───────────────────────────────

    async def _fix_loop(
        self, job: Dict[str, Any], profile: Dict[str, Any], retry_count: int = 0
    ) -> Dict[str, Any]:
        """Writer → Reviewer → fix cycle. Max 2 auto-retries."""
        from agents.writer_agent import WriterAgent
        from agents.reviewer_agent import ReviewerAgent

        max_retries = self.config.get("quality", {}).get("max_auto_fix_retries", 2)

        writer = WriterAgent(config=self.config, claude_client=self.claude, local_llm=self.local)
        reviewer = ReviewerAgent(config=self.config, claude_client=self.claude, local_llm=self.local)

        fix_instructions = None
        writer_output: Dict[str, Any] = {}

        for attempt in range(max_retries + 1):
            if self.dry_run:
                return {"output_dir": "dry_run", "resume": None, "cover_letter": None}

            try:
                writer_output = await writer.run(job, profile, fix_instructions=fix_instructions)
            except NotImplementedError:
                self.log("WARNING", "Writer raised NotImplementedError — skipping", job_id=job.get("job_id"))
                return {"output_dir": "not_implemented", "resume": None, "cover_letter": None}

            try:
                review = await reviewer.run(job, writer_output, profile, review_pass=attempt + 1)
            except NotImplementedError:
                self.log("WARNING", "Reviewer raised NotImplementedError — skipping review")
                return writer_output

            if review.get("passed", False) or attempt >= max_retries:
                if not review.get("passed") and attempt >= max_retries:
                    self.log("WARNING", f"Max retries reached for {job.get('job_id')}, accepting output")
                return writer_output

            fix_instructions = review.get("fix_instructions")
            self.log("INFO", f"Fix loop attempt {attempt + 1}/{max_retries} for {job.get('job_id')}", job_id=job.get("job_id"))

        return writer_output

    def _load_existing_job_matches(self) -> Dict[str, Any]:
        """Load existing job_matches.json when --skip-search is used."""
        data_dir = Path(self.config.get("paths", {}).get("data_dir", "data"))
        path = data_dir / "job_matches.json"
        if not path.exists():
            self.log("WARNING", "--skip-search: no existing job_matches.json found")
            return {"best_match": [], "possible_match": [], "not_matching": []}
        try:
            return read_json(path, agent=self.name)
        except Exception as exc:
            self.log("ERROR", f"Failed to load job_matches.json: {exc}")
            return {"best_match": [], "possible_match": [], "not_matching": []}


# ── Module-level helpers ──────────────────────────────────────────────────────

def _load_and_validate_config(config_path: str) -> Dict[str, Any]:
    """Load config.json and enforce GDPR consent gate (I-006)."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"config.json not found at: {path.absolute()}")

    try:
        cfg = read_json(path, agent="orchestrator")
    except Exception as exc:
        raise ConfigError(f"Failed to read config.json: {exc}") from exc

    if not cfg.get("gdpr", {}).get("consent_acknowledged", False):
        raise ConsentError(
            "GDPR consent not acknowledged. Read GDPR.md then set "
            "'gdpr.consent_acknowledged': true in config.json"
        )

    return cfg


def _build_pending_approval(
    jobs: List[Dict[str, Any]], job_matches: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_jobs": len(jobs),
        "best_match_count": len(job_matches.get("best_match", [])),
        "possible_match_count": len(job_matches.get("possible_match", [])),
        "jobs": [
            {
                "job_id": j.get("job_id"),
                "title": j.get("title"),
                "company": j.get("company"),
                "location": j.get("location"),
                "score": j.get("score", 0),
                "score_breakdown": j.get("score_breakdown", {}),
                "url": j.get("url"),
            }
            for j in jobs
        ],
        "status": "awaiting_approval",
    }


async def _gate1_cli(jobs: List[Dict], pending_path: Path) -> List[Dict[str, Any]]:
    """Interactive CLI Gate 1: present jobs and collect approvals."""
    approved = []
    print(f"\n{'='*60}")
    print(f"Gate 1 — {len(jobs)} new job(s) found")
    print(f"{'='*60}\n")

    for i, job in enumerate(jobs, 1):
        score = job.get("score", 0)
        reasoning = job.get("score_breakdown", {}).get("reasoning", "")
        print(f"[{i}/{len(jobs)}] {job.get('title')} @ {job.get('company')}")
        print(f"       Score: {score:.0f}/100  |  {job.get('location', 'N/A')}")
        print(f"       URL:   {job.get('url', 'N/A')}")
        if reasoning:
            print(f"       Match: {reasoning}")

        answer = input("       Apply? [Y/n/q(uit)]: ").strip().lower()
        if answer == "q":
            break
        if answer in ("", "y", "yes"):
            approved.append(job)
        print()

    print(f"\n{len(approved)} job(s) approved for tailoring.\n")
    return approved
