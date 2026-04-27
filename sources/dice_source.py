"""
Dice.com job source adapter.
Uses the Dice MCP (https://mcp.dice.com/mcp) via Claude's beta MCP-client API.
Claude connects to the MCP server from Anthropic's infrastructure, which is on
the Dice allowlist. No API key required on the Dice side.
"""
import asyncio
from typing import Any, Dict, List

from sources.base_source import BaseJobSource
from utils.exceptions import JobSourceError
from utils.logger import run_log

DICE_MCP_URL = "https://mcp.dice.com/mcp"
DICE_MCP_NAME = "dice"


class DiceSource(BaseJobSource):
    source_id = "dice"
    source_name = "Dice"
    requires_auth = False

    async def search_jobs(
        self, profile: Dict[str, Any], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Search Dice via MCP tool call with exponential backoff (1s/2s/4s, max 3 retries).
        Requires self.claude (ClaudeClient) to be set on the agent.
        """
        source_cfg = (
            config.get("job_sources", {}).get("sources", {}).get("dice", {})
        )
        retry_cfg = source_cfg.get(
            "retry", {"max_attempts": 3, "backoff_seconds": [1, 2, 4]}
        )
        max_attempts = retry_cfg.get("max_attempts", 3)
        backoff = retry_cfg.get("backoff_seconds", [1, 2, 4])

        if self.claude is None:
            raise JobSourceError(
                "DiceSource requires a ClaudeClient (claude attribute) on the agent",
                source_id="dice",
            )

        query = self._build_query(profile, config)
        last_exc: Exception = RuntimeError("No attempts made")

        for attempt in range(max_attempts):
            try:
                raw_jobs = await self._call_dice_mcp(query)
                run_log(
                    "INFO",
                    "dice_source",
                    f"Found {len(raw_jobs)} jobs (attempt {attempt + 1})",
                )
                return [self.normalize_job(j) for j in raw_jobs]
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                    run_log(
                        "WARNING",
                        "dice_source",
                        f"Attempt {attempt + 1} failed ({exc}), retrying in {wait}s",
                    )
                    await asyncio.sleep(wait)

        raise JobSourceError(
            f"Dice search failed after {max_attempts} attempts: {last_exc}",
            source_id="dice",
        )

    async def _call_dice_mcp(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Ask Claude to call the Dice MCP search tool and return raw job results.
        Claude executes the MCP call from Anthropic's infrastructure (which is on
        Dice's allowlist), so direct HTTP from this machine is not needed.
        """
        prompt = _build_mcp_prompt(query)
        result = await self.claude.call_mcp_tool(
            server_url=DICE_MCP_URL,
            server_name=DICE_MCP_NAME,
            prompt=prompt,
            agent="dice_source",
        )

        if isinstance(result, list):
            return result
        # Some MCP servers wrap results: {"jobs": [...]} or {"results": [...]}
        if isinstance(result, dict):
            for key in ("jobs", "results", "data", "items"):
                if isinstance(result.get(key), list):
                    return result[key]
        return []

    def _build_query(self, profile: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """Build a Dice search query from the candidate profile and config."""
        candidate = config.get("candidate", {})
        titles = profile.get("target_titles", [])
        skills = [
            s["name"]
            for s in profile.get("skills", {}).get("technical", [])[:5]
        ]
        emp_types = candidate.get("employment_types", ["full-time"])

        query_str = (
            " OR ".join(f'"{t}"' for t in titles[:2])
            if titles
            else " ".join(skills[:3])
        )
        return {
            "query": query_str,
            "location": _map_location(candidate.get("location", "")),
            "employment_type": _map_employment_types(emp_types),
            "date_posted": "LAST_7_DAYS",
            "page_size": 25,
        }

    def normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a Dice MCP job response to the common job schema."""
        company = raw_job.get("company", {})
        company_name = (
            company.get("name", "") if isinstance(company, dict) else str(company)
        )
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


# ── Module-level helpers ──────────────────────────────────────────────────────

def _build_mcp_prompt(query: Dict[str, Any]) -> str:
    """Build the user prompt sent to Claude to drive the Dice MCP tool call."""
    return (
        "Use the Dice job search tool to find tech jobs matching these criteria:\n\n"
        f"- Search query: {query['query']}\n"
        f"- Location: {query.get('location') or 'Remote / Anywhere US'}\n"
        f"- Employment type: {query.get('employment_type', 'FULLTIME')}\n"
        f"- Date posted: {query.get('date_posted', 'LAST_7_DAYS')}\n"
        f"- Page size: {query.get('page_size', 25)}\n\n"
        "Return the complete raw JSON array of job results exactly as returned by "
        "the tool. Do not summarize, filter, or modify the data."
    )


def _map_location(location: str) -> str:
    """Map config location values to Dice-friendly strings."""
    mapping = {
        "anywhere_us": "Remote",
        "remote": "Remote",
        "": "Remote",
    }
    return mapping.get(location.lower(), location)


def _map_employment_types(types: List[str]) -> str:
    """Map config employment_types list to Dice employmentType string."""
    type_map = {
        "full-time": "FULLTIME",
        "fulltime": "FULLTIME",
        "contract": "CONTRACTS",
        "c2c": "CONTRACTS",
        "part-time": "PARTTIME",
    }
    dice_types = list({type_map.get(t.lower(), "FULLTIME") for t in types})
    return ",".join(dice_types) if dice_types else "FULLTIME"
