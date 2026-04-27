"""
Tracker Agent — data clerk and metrics engine.
Reads: all agent outputs, user status updates from dashboard
Writes: application_tracker.json (atomic), run_history.json, master_summary.md,
        scoring_feedback.json
Token cost: ~200 (mostly pure Python file I/O)

NEVER generates creative content or makes subjective judgments.
All writes to application_tracker.json use atomic_write_json() with backup.

Status lifecycle (forward transitions only):
  Discovered → Tailored | Rejected
  Tailored   → Applied  | Rejected
  Applied    → Interview | Rejected | Ghosted
  Interview  → Offered  | Rejected
  Offered    → Accepted | Declined
  Ghosted    → Applied  (re-applied after ghosting)
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agents.base_agent import BaseAgent
from utils.exceptions import TrackerAgentError
from utils.file_io import atomic_write_json, read_json, write_json

# Valid forward transitions
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "Discovered": {"Tailored", "Rejected"},
    "Tailored": {"Applied", "Rejected"},
    "Applied": {"Interview", "Rejected", "Ghosted"},
    "Interview": {"Offered", "Rejected"},
    "Offered": {"Accepted", "Declined"},
    "Ghosted": {"Applied"},
    "Accepted": set(),
    "Declined": set(),
    "Rejected": set(),
}

ALL_STATUSES = set(VALID_TRANSITIONS.keys())

EMPTY_TRACKER: Dict[str, Any] = {
    "jobs": [],
    "archived_jobs": [],
    "last_run_at": None,
    "metrics": {
        "total_discovered": 0,
        "total_tailored": 0,
        "total_applied": 0,
        "total_interview": 0,
        "total_offered": 0,
        "total_rejected": 0,
        "total_accepted": 0,
    },
}


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
        Perform a tracker action.
          "record_job"    — add/update a job entry with given status
          "end_of_run"    — flag follow-ups, archive old entries, compute metrics
          "status_update" — user changed a job's status (from dashboard)
        """
        if action == "record_job":
            if job is None or status is None:
                raise TrackerAgentError("record_job requires job and status")
            return await self._record_job(job, status)

        if action == "end_of_run":
            return await self._end_of_run(run_summary or {})

        if action == "status_update":
            if job is None or status is None:
                raise TrackerAgentError("status_update requires job and status")
            return await self._status_update(job.get("job_id", ""), status, user_override=True)

        raise TrackerAgentError(f"Unknown tracker action: {action!r}")

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _record_job(self, job: Dict[str, Any], status: str) -> Dict[str, Any]:
        job_id = job.get("job_id", "")
        if status not in ALL_STATUSES:
            raise TrackerAgentError(f"Invalid status {status!r}")

        tracker = self._load_tracker()
        now = datetime.now(timezone.utc).isoformat()

        existing = _find_job(tracker["jobs"], job_id)
        if existing:
            current_status = existing.get("status", "Discovered")
            if status != current_status:
                if status not in VALID_TRANSITIONS.get(current_status, set()):
                    raise TrackerAgentError(
                        f"Invalid transition {current_status!r} → {status!r} for {job_id}"
                    )
                existing["status"] = status
                existing["updated_at"] = now
        else:
            tracker["jobs"].append(_build_entry(job, status, now))

        tracker["last_run_at"] = now
        self._save_tracker(tracker)
        self.audit("write", "application_tracker.json", "success", job_id=job_id)
        self.log("INFO", f"Recorded job {job_id} as {status}", job_id=job_id)
        return {"job_id": job_id, "status": status}

    async def _end_of_run(self, run_summary: Dict[str, Any]) -> Dict[str, Any]:
        tracker = self._load_tracker()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Flag follow-ups: Applied jobs >= 7 days old
        followup_threshold = now - timedelta(days=7)
        followups = []
        for entry in tracker["jobs"]:
            if entry.get("status") == "Applied":
                updated = _parse_dt(entry.get("updated_at", entry.get("created_at", now_iso)))
                if updated <= followup_threshold:
                    entry["follow_up_needed"] = True
                    followups.append(entry["job_id"])

        # Archive: Rejected/Ghosted entries >= 30 days old
        archive_threshold = now - timedelta(days=30)
        active_jobs = []
        for entry in tracker["jobs"]:
            if entry.get("status") in ("Rejected", "Ghosted", "Declined"):
                updated = _parse_dt(entry.get("updated_at", entry.get("created_at", now_iso)))
                if updated <= archive_threshold:
                    entry["archived"] = True
                    tracker["archived_jobs"].append(entry)
                    continue
            active_jobs.append(entry)
        tracker["jobs"] = active_jobs

        # Compute metrics
        all_entries = tracker["jobs"] + tracker["archived_jobs"]
        tracker["metrics"] = _compute_metrics(all_entries)
        tracker["last_run_at"] = now_iso

        self._save_tracker(tracker)

        # Append to run_history.json
        self._append_run_history(run_summary, tracker["metrics"], now_iso)

        # Write master_summary.md
        self._write_master_summary(tracker, followups)

        # Write scoring_feedback.json
        self._write_scoring_feedback(tracker)

        self.audit("write", "application_tracker.json", "success")
        self.log("INFO", f"End-of-run: {len(followups)} follow-ups flagged, {len(tracker['archived_jobs'])} archived")
        return {"followups": len(followups), "metrics": tracker["metrics"]}

    async def _status_update(self, job_id: str, new_status: str, user_override: bool = False) -> Dict[str, Any]:
        if new_status not in ALL_STATUSES:
            raise TrackerAgentError(f"Invalid status {new_status!r}")

        tracker = self._load_tracker()
        entry = _find_job(tracker["jobs"], job_id)
        if not entry:
            raise TrackerAgentError(f"Job {job_id} not found in tracker")

        current = entry.get("status", "Discovered")
        if new_status not in VALID_TRANSITIONS.get(current, set()):
            raise TrackerAgentError(
                f"Invalid transition {current!r} → {new_status!r}"
            )

        now = datetime.now(timezone.utc).isoformat()
        entry["status"] = new_status
        entry["updated_at"] = now
        if user_override:
            entry["user_override"] = True

        self._save_tracker(tracker)

        if user_override:
            self._record_scoring_feedback(job_id, entry.get("score", 0), current, new_status)

        self.log("INFO", f"Status update {job_id}: {current} → {new_status}")
        return {"job_id": job_id, "old_status": current, "new_status": new_status}

    # ── I/O helpers ───────────────────────────────────────────────────────────

    def _tracker_path(self) -> Path:
        data_dir = Path(self.config.get("paths", {}).get("data_dir", "data"))
        return data_dir / "application_tracker.json"

    def _load_tracker(self) -> Dict[str, Any]:
        path = self._tracker_path()
        if not path.exists():
            return {
                "jobs": [],
                "archived_jobs": [],
                "last_run_at": None,
                "metrics": {**EMPTY_TRACKER["metrics"]},
            }
        try:
            return read_json(path, agent=self.name)
        except Exception as exc:
            raise TrackerAgentError(f"Failed to load tracker: {exc}") from exc

    def _save_tracker(self, tracker: Dict[str, Any]) -> None:
        path = self._tracker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_json(path, tracker, agent=self.name)
        except Exception as exc:
            raise TrackerAgentError(f"Failed to save tracker: {exc}") from exc

    def _append_run_history(self, run_summary: Dict, metrics: Dict, timestamp: str) -> None:
        data_dir = Path(self.config.get("paths", {}).get("data_dir", "data"))
        path = data_dir / "run_history.json"
        history: List[Dict] = []
        if path.exists():
            try:
                history = read_json(path, agent=self.name)
            except Exception:
                pass
        history.append({
            "timestamp": timestamp,
            "jobs_found": run_summary.get("jobs_found", 0),
            "jobs_approved": run_summary.get("jobs_approved", 0),
            "jobs_completed": run_summary.get("jobs_completed", 0),
            "jobs_skipped": run_summary.get("jobs_skipped", 0),
            "dry_run": run_summary.get("dry_run", False),
            "metrics_snapshot": metrics,
        })
        # Keep last 90 entries
        write_json(path, history[-90:], agent=self.name)

    def _write_master_summary(self, tracker: Dict, followups: List[str]) -> None:
        data_dir = Path(self.config.get("paths", {}).get("data_dir", "data"))
        metrics = tracker.get("metrics", {})
        jobs = tracker.get("jobs", [])

        lines = [
            "# JobSearchAgent — Master Summary",
            f"",
            f"**Last Updated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Active Applications:** {len(jobs)}",
            f"",
            "## Conversion Funnel",
            f"",
            f"| Stage | Count |",
            f"|-------|-------|",
        ]
        for key, label in [
            ("total_discovered", "Discovered"),
            ("total_tailored", "Tailored"),
            ("total_applied", "Applied"),
            ("total_interview", "Interview"),
            ("total_offered", "Offered"),
            ("total_accepted", "Accepted"),
        ]:
            lines.append(f"| {label} | {metrics.get(key, 0)} |")

        if followups:
            lines += [
                f"",
                f"## Follow-up Needed ({len(followups)})",
                f"",
            ]
            for job_id in followups:
                entry = _find_job(jobs, job_id)
                if entry:
                    lines.append(f"- {entry.get('title')} @ {entry.get('company')} (`{job_id}`)")

        lines += [
            f"",
            "## Recent Applications",
            f"",
        ]
        recent = sorted(jobs, key=lambda e: e.get("updated_at", ""), reverse=True)[:10]
        for entry in recent:
            lines.append(
                f"- **{entry.get('status')}** — {entry.get('title')} @ {entry.get('company')} "
                f"(score: {entry.get('score', 0):.0f})"
            )

        (data_dir / "master_summary.md").write_text("\n".join(lines), encoding="utf-8")

    def _write_scoring_feedback(self, tracker: Dict) -> None:
        overrides = [
            {
                "job_id": e["job_id"],
                "score": e.get("score", 0),
                "company": e.get("company"),
                "title": e.get("title"),
                "final_status": e.get("status"),
                "user_override": e.get("user_override", False),
            }
            for e in tracker.get("jobs", []) + tracker.get("archived_jobs", [])
            if e.get("user_override")
        ]
        data_dir = Path(self.config.get("paths", {}).get("data_dir", "data"))
        write_json(data_dir / "scoring_feedback.json", overrides, agent=self.name)

    def _record_scoring_feedback(self, job_id: str, score: float, old_status: str, new_status: str) -> None:
        data_dir = Path(self.config.get("paths", {}).get("data_dir", "data"))
        path = data_dir / "scoring_feedback.json"
        feedback: List[Dict] = []
        if path.exists():
            try:
                feedback = read_json(path, agent=self.name)
            except Exception:
                pass
        feedback.append({
            "job_id": job_id,
            "score": score,
            "old_status": old_status,
            "new_status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_override": True,
        })
        write_json(path, feedback, agent=self.name)


# ── Module-level helpers ──────────────────────────────────────────────────────

def _build_entry(job: Dict[str, Any], status: str, now: str) -> Dict[str, Any]:
    return {
        "job_id": job.get("job_id", ""),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "score": job.get("score", 0),
        "url": job.get("url", ""),
        "status": status,
        "created_at": now,
        "updated_at": now,
        "follow_up_needed": False,
        "archived": False,
        "user_override": False,
    }


def _find_job(jobs: List[Dict], job_id: str) -> Optional[Dict]:
    for job in jobs:
        if job.get("job_id") == job_id:
            return job
    return None


def _parse_dt(iso_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def _compute_metrics(entries: List[Dict]) -> Dict[str, int]:
    metrics = {k: 0 for k in EMPTY_TRACKER["metrics"]}
    for e in entries:
        status = e.get("status", "")
        if status == "Discovered":
            metrics["total_discovered"] += 1
        elif status == "Tailored":
            metrics["total_tailored"] += 1
        elif status == "Applied":
            metrics["total_applied"] += 1
        elif status == "Interview":
            metrics["total_interview"] += 1
        elif status in ("Offered", "Accepted", "Declined"):
            metrics["total_offered"] += 1
            if status == "Accepted":
                metrics["total_accepted"] += 1
        elif status in ("Rejected", "Ghosted"):
            metrics["total_rejected"] += 1
    return metrics
