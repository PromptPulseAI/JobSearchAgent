"""
Indeed job source adapter — STUB.

Status: Not yet implemented. Requires Indeed Publisher API key (INDEED_API_KEY).
To enable: set "enabled": true in config.json under job_sources.sources.indeed,
and add INDEED_API_KEY to your .env file.

Implementation guide: https://developer.indeed.com/docs
"""
from typing import Any, Dict, List

from sources.base_source import BaseJobSource
from utils.exceptions import JobSourceError


class IndeedSource(BaseJobSource):
    source_id = "indeed"
    source_name = "Indeed"
    requires_auth = True

    async def search_jobs(
        self, profile: Dict[str, Any], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Indeed source not yet implemented. "
            "See sources/indeed_source.py for the implementation guide."
        )

    def normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Indeed job normalization not yet implemented.")
