"""
Dice.com job source adapter.
Uses the Dice MCP (Model Context Protocol) tool — authless.

ISSUE I-001: The exact Python invocation method for the Dice MCP tool
is not yet confirmed. `_call_dice_mcp()` is a placeholder that raises
NotImplementedError. Replace it in Commit 5 once the MCP client library
and call signature are confirmed.
"""
import asyncio
from typing import Any, Dict, List

from sources.base_source import BaseJobSource
from utils.exceptions import JobSourceError
from utils.logger import run_log


class DiceSource(BaseJobSource):
    source_id = "dice"
    source_name = "Dice"
    requires_auth = False

    async def search_jobs(
        self, profile: Dict[str, Any], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Search Dice via MCP tool call with exponential backoff (1s/2s/4s, max 3 retries).
        """
        source_cfg = config.get("job_sources", {}).get("sources", {}).get("dice", {})
        retry_cfg = source_cfg.get("retry", {"max_attempts": 3, "backoff_seconds": [1, 2, 4]})
        max_attempts = retry_cfg.get("max_attempts", 3)
        backoff = retry_cfg.get("backoff_seconds", [1, 2, 4])

        query = self._build_query(profile, config)
        last_exc = None

        for attempt in range(max_attempts):
            try:
                raw_jobs = await self._call_dice_mcp(query)
                run_log("INFO", "dice_source", f"Found {len(raw_jobs)} jobs (attempt {attempt + 1})")
                return [self.normalize_job(j) for j in raw_jobs]
            except NotImplementedError:
                raise  # Don't retry placeholder errors
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                    run_log("WARNING", "dice_source", f"Attempt {attempt + 1} failed ({exc}), retrying in {wait}s")
                    await asyncio.sleep(wait)

        raise JobSourceError(
            f"Dice search failed after {max_attempts} attempts: {last_exc}",
            source_id="dice",
        )

    async def _call_dice_mcp(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Call the Dice MCP search_jobs tool.
        TODO(I-001, Commit 5): Replace this placeholder with the actual MCP client call.
        Expected signature: search_jobs(keywords, location, employment_type, date_posted)
        """
        raise NotImplementedError(
            "Dice MCP integration not yet implemented. "
            "See ISSUES.md I-001 and implement in Commit 5."
        )

    def _build_query(self, profile: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """Build a Dice search query from the candidate profile and config."""
        candidate = config.get("candidate", {})
        titles = profile.get("target_titles", [])
        skills = [s["name"] for s in profile.get("skills", {}).get("technical", [])[:5]]
        return {
            "query": " ".join(titles[:2] + skills[:3]),
            "location": candidate.get("location", ""),
            "employment_type": candidate.get("employment_types", ["full-time"]),
            "date_posted": "last7Days",
        }

    def normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a Dice API job response to the common job schema."""
        company = raw_job.get("company", {})
        company_name = company.get("name", "") if isinstance(company, dict) else str(company)
        return {
            "job_id": f"dice_{raw_job.get('id', '')}",
            "source": "dice",
            "title": raw_job.get("title", ""),
            "company": company_name,
            "url": raw_job.get("applyUrl") or raw_job.get("url", ""),
            "date_posted": raw_job.get("postedDate", ""),
            "location": raw_job.get("location", ""),
            "employment_type": raw_job.get("employmentType", ""),
            "job_description": raw_job.get("description", ""),
            "company_context": {},
        }
