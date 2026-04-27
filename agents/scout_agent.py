"""
Scout Agent — job market analyst.
Reads: candidate_profile.json, config.json, application_tracker.json, scoring_feedback.json
Writes: data/job_matches.json
Token cost: ~500 (local Ollama for scoring — zero Claude API cost)
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from agents.base_agent import BaseAgent
from sources.registry import SourceRegistry
from utils.exceptions import AllSourcesFailedError, JobSourceError, ScoutAgentError
from utils.file_io import read_json, write_json


class ScoutAgent(BaseAgent):
    name = "scout_agent"

    async def run(self, candidate_profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Search active sources, score results, write data/job_matches.json.
        Returns {"best_match": [...], "possible_match": [...], "not_matching": [...]}.
        """
        paths = self.config.get("paths", {})
        data_dir = Path(paths.get("data_dir", "data"))
        scoring_cfg = self.config.get("scoring", {})
        thresholds = scoring_cfg.get("thresholds", {"best_match": 75, "possible_match": 50})

        self.log("INFO", "Starting job search across active sources")

        # 1. Load scoring prompt
        scoring_prompt = self.load_prompt("scout_agent.txt")

        # 2. Search all active sources
        raw_jobs = await self._search_all_sources(candidate_profile)
        self.log("INFO", f"Found {len(raw_jobs)} raw jobs before dedup/filter")

        # 3. Dedup against existing tracker
        seen_ids = _load_seen_job_ids(data_dir / "application_tracker.json")
        jobs = [j for j in raw_jobs if j.get("job_id") not in seen_ids]
        self.log("INFO", f"{len(jobs)} jobs after dedup ({len(raw_jobs) - len(jobs)} duplicates removed)")

        # 4. Apply exclusion filters
        exclusions = self.config.get("exclusions", {})
        jobs, excluded = _apply_exclusions(jobs, exclusions)
        self.log("INFO", f"{len(jobs)} jobs after exclusion ({excluded} excluded)")

        # 5. Score each job (local LLM)
        scored_jobs = await self._score_jobs(jobs, candidate_profile, scoring_prompt)

        # 6. Apply freshness boost
        scored_jobs = [_apply_freshness_boost(j) for j in scored_jobs]

        # 7. Sort by score descending
        scored_jobs.sort(key=lambda j: j.get("score", 0), reverse=True)

        # 8. Read scoring_feedback.json (v1: log-only)
        _log_scoring_feedback(data_dir / "scoring_feedback.json", self)

        # 9. Group into match tiers
        best_threshold = thresholds.get("best_match", 75)
        possible_threshold = thresholds.get("possible_match", 50)

        result = _group_by_tier(scored_jobs, best_threshold, possible_threshold)

        self.log(
            "INFO",
            f"Match results: {len(result['best_match'])} best, "
            f"{len(result['possible_match'])} possible, "
            f"{len(result['not_matching'])} not matching"
        )

        # 10. Write job_matches.json
        output_path = data_dir / "job_matches.json"
        write_json(output_path, result, agent=self.name)
        self.audit("write", "job_matches", "success")

        return result

    # ── Source search ─────────────────────────────────────────────────────────

    async def _search_all_sources(self, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        registry = SourceRegistry(self.config)
        sources = registry.active_sources

        if not sources:
            raise AllSourcesFailedError("No active job sources configured")

        all_jobs: List[Dict[str, Any]] = []
        failed: List[str] = []

        for source in sources:
            try:
                jobs = await source.search_jobs(profile, self.config)
                all_jobs.extend(jobs)
                self.log("INFO", f"{source.source_name}: {len(jobs)} jobs found")
            except NotImplementedError:
                self.log("WARNING", f"{source.source_name}: not yet implemented (see ISSUES.md I-001)")
                failed.append(source.source_id)
            except JobSourceError as exc:
                self.log("WARNING", f"{source.source_name} failed: {exc}")
                failed.append(source.source_id)

        if failed and len(failed) == len(sources):
            raise AllSourcesFailedError(
                f"All sources failed: {failed}. Check network and API credentials."
            )

        return all_jobs

    # ── Scoring ───────────────────────────────────────────────────────────────

    async def _score_jobs(
        self,
        jobs: List[Dict[str, Any]],
        profile: Dict[str, Any],
        scoring_prompt: str,
    ) -> List[Dict[str, Any]]:
        scored = []
        weights = self.config.get("scoring", {}).get("weights", _DEFAULT_WEIGHTS)

        for job in jobs:
            try:
                breakdown = await _score_one_job(job, profile, scoring_prompt, weights, self)
                job["score"] = breakdown["total_score"]
                job["score_breakdown"] = breakdown
            except Exception as exc:
                self.log("WARNING", f"Scoring failed for {job.get('job_id')}: {exc} — assigning score 0")
                job["score"] = 0
                job["score_breakdown"] = {"error": str(exc)}
            scored.append(job)

        return scored


# ── Pure-function helpers ──────────────────────────────────────────────────────

_DEFAULT_WEIGHTS = {
    "core_skills_match": 0.35,
    "title_seniority_alignment": 0.20,
    "industry_domain_fit": 0.15,
    "years_experience_fit": 0.15,
    "nice_to_have_skills": 0.10,
    "company_culture_signals": 0.05,
}

_CLEARANCE_RE = re.compile(
    r"\b(?:security clearance|clearance required|top secret|TS/SCI|secret clearance)\b",
    re.IGNORECASE,
)
_JUNIOR_RE = re.compile(
    r"\b(?:junior|entry.?level|intern|internship|graduate|new grad|0-2 years|0-1 years?)\b",
    re.IGNORECASE,
)


async def _score_one_job(
    job: Dict[str, Any],
    profile: Dict[str, Any],
    scoring_prompt: str,
    weights: Dict[str, float],
    agent: "ScoutAgent",
) -> Dict[str, Any]:
    """Score a single job via local LLM, Claude API fallback, or keyword heuristic."""
    user_msg = _build_scoring_message(job, profile)

    if agent.local is not None:
        raw = await agent.local.generate(
            prompt=f"{scoring_prompt}\n\n{user_msg}",
            max_tokens=300,
            agent=agent.name,
        )
        scores = _parse_score_response(raw)
    elif agent.claude is not None:
        # Fallback: use Claude (costs tokens but correct)
        raw = await agent.claude.generate(
            system_prompt=scoring_prompt,
            user_message=user_msg,
            max_tokens=300,
            temperature=0.1,
            agent=agent.name,
        )
        scores = _parse_score_response(raw)
    else:
        # Last resort: pure Python keyword heuristic (free, approximate)
        scores = _keyword_fallback_score(job, profile)

    total = round(sum(scores.get(k, 0) * w for k, w in weights.items()), 1)

    return {
        "total_score": total,
        "weights_used": weights,
        **scores,
    }


def _keyword_fallback_score(job: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Pure-Python keyword heuristic when no LLM is available. Approximate but non-zero."""
    jd = (job.get("job_description", "") + " " + job.get("title", "")).lower()
    profile_skills = {s["name"].lower() for s in profile.get("skills", {}).get("technical", [])}
    target_titles = [t.lower() for t in profile.get("target_titles", [])]
    industries = [i.lower() for i in profile.get("industries", [])]

    # core_skills_match: % of profile skills found in JD (capped at 100)
    matched_skills = sum(1 for s in profile_skills if s in jd)
    core = min(100, int(matched_skills / max(len(profile_skills), 1) * 100)) if profile_skills else 50

    # title_seniority_alignment: does job title match target titles?
    job_title = job.get("title", "").lower()
    title_score = 80 if any(t in job_title or job_title in t for t in target_titles) else 40

    # industry_domain_fit: industries mentioned in JD
    industry_score = 70 if any(ind in jd for ind in industries) else 45

    # years_experience_fit: profile years vs JD requirement (basic)
    profile_years = profile.get("years_experience", 0)
    import re as _re
    years_match = _re.search(r"(\d+)\+?\s*years?", jd)
    if years_match:
        required = int(years_match.group(1))
        years_score = 90 if profile_years >= required else max(30, int(profile_years / required * 80))
    else:
        years_score = 70

    return {
        "core_skills_match": core,
        "title_seniority_alignment": title_score,
        "industry_domain_fit": industry_score,
        "years_experience_fit": years_score,
        "nice_to_have_skills": 50,
        "company_culture_signals": 50,
        "reasoning": "Keyword heuristic (no LLM available)",
    }


def _build_scoring_message(job: Dict[str, Any], profile: Dict[str, Any]) -> str:
    skills = [s["name"] for s in profile.get("skills", {}).get("technical", [])]
    return (
        f"## Candidate Profile\n"
        f"Target titles: {', '.join(profile.get('target_titles', []))}\n"
        f"Years experience: {profile.get('years_experience', 0)}\n"
        f"Technical skills: {', '.join(skills[:15])}\n"
        f"Industries: {', '.join(profile.get('industries', []))}\n\n"
        f"## Job Posting\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description:\n{job.get('job_description', '')[:2000]}"
    )


def _parse_score_response(raw: str) -> Dict[str, Any]:
    """Extract JSON scores from local LLM response. Returns zero scores on failure."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
        # Clamp all numeric values to 0-100
        for key in _DEFAULT_WEIGHTS:
            if key in data:
                data[key] = max(0, min(100, int(data[key])))
        return data
    except (json.JSONDecodeError, ValueError):
        return {k: 0 for k in _DEFAULT_WEIGHTS}


def _apply_exclusions(
    jobs: List[Dict[str, Any]], exclusions: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], int]:
    """Filter out excluded jobs. Returns (kept_jobs, excluded_count)."""
    kept = []
    excluded = 0

    blacklist = {c.lower() for c in exclusions.get("companies_blacklist", [])}
    avoid_tech = {t.lower() for t in exclusions.get("technologies_avoid", [])}

    for job in jobs:
        jd = (job.get("job_description", "") + " " + job.get("title", "")).lower()
        company = job.get("company", "").lower()

        if exclusions.get("security_clearance") and _CLEARANCE_RE.search(jd):
            excluded += 1
            continue
        if exclusions.get("entry_level_junior") and _JUNIOR_RE.search(jd):
            excluded += 1
            continue
        if company in blacklist:
            excluded += 1
            continue
        if avoid_tech and any(tech in jd for tech in avoid_tech):
            excluded += 1
            continue

        kept.append(job)

    return kept, excluded


def _apply_freshness_boost(job: Dict[str, Any]) -> Dict[str, Any]:
    """Add up to +5 points for recently posted jobs (pure Python, zero tokens)."""
    date_str = job.get("date_posted", "")
    if not date_str:
        return job

    try:
        posted = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - posted).days

        boost = 5 if age_days <= 3 else 2 if age_days <= 7 else 0
        if boost:
            job["score"] = min(100, job.get("score", 0) + boost)
            job["freshness_boost"] = boost
    except (ValueError, TypeError):
        pass

    return job


def _load_seen_job_ids(tracker_path: Path) -> Set[str]:
    """Load job IDs already in the tracker. Returns empty set if file missing."""
    if not tracker_path.exists():
        return set()
    try:
        tracker = read_json(tracker_path, agent="scout_agent")
        return {entry.get("job_id") for entry in tracker.get("jobs", []) if entry.get("job_id")}
    except Exception:
        return set()


def _group_by_tier(
    scored_jobs: List[Dict[str, Any]],
    best_threshold: float,
    possible_threshold: float,
) -> Dict[str, List[Dict[str, Any]]]:
    best, possible, not_matching = [], [], []
    for job in scored_jobs:
        score = job.get("score", 0)
        if score >= best_threshold:
            best.append(job)
        elif score >= possible_threshold:
            possible.append(job)
        else:
            not_matching.append(job)
    return {"best_match": best, "possible_match": possible, "not_matching": not_matching}


def _log_scoring_feedback(feedback_path: Path, agent: "ScoutAgent") -> None:
    """v1: read scoring_feedback.json and log it. Automated weight adjustment is future work."""
    if not feedback_path.exists():
        return
    try:
        feedback = read_json(feedback_path, agent=agent.name)
        # scoring_feedback.json is a list of override records written by TrackerAgent
        overrides = feedback if isinstance(feedback, list) else []
        if overrides:
            agent.log("INFO", f"scoring_feedback.json has {len(overrides)} user override(s) — logged for future weight tuning (I-004)")
    except Exception:
        pass
