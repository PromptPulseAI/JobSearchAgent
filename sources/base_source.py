"""
Abstract base class for all job board integrations.

To add a new source:
  1. Create sources/{name}_source.py
  2. Define a class inheriting BaseJobSource
  3. Set source_id, source_name, requires_auth class attributes
  4. Implement search_jobs() and normalize_job()
  5. Add a config entry in config.json under job_sources.sources
  6. Add the source_id to config.json job_sources.active_sources
  The registry auto-discovers it — no other changes needed.
"""
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseJobSource(ABC):
    """Abstract base for pluggable job board integrations."""

    source_id: str        # Machine-readable, e.g. "dice"
    source_name: str      # Human-readable, e.g. "Dice"
    requires_auth: bool   # Whether an API key env var is required

    @abstractmethod
    async def search_jobs(
        self,
        profile: Dict[str, Any],
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Search for jobs matching the candidate profile.
        Returns a list of normalized job dicts (common schema).
        Must implement its own retry logic according to source config.
        """

    @abstractmethod
    def normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize a raw job object from this source to the common schema.
        Common schema fields: job_id, source, title, company, url, date_posted,
        location, employment_type, job_description, company_context
        """

    async def health_check(self) -> bool:
        """Check if this source is reachable. Override for network checks."""
        return True

    def validate_config(self, source_config: Dict[str, Any]) -> Optional[str]:
        """
        Validate source-specific config. Return an error message string if invalid,
        or None if the config is acceptable. Override to add auth checks.
        """
        if self.requires_auth:
            key_env = source_config.get("api_key_env")
            if key_env and not os.environ.get(key_env):
                return f"Missing required environment variable: {key_env}"
        return None
