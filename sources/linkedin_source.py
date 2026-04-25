"""
LinkedIn job source adapter — STUB.

Status: Not yet implemented. Requires LinkedIn OAuth credentials.
To enable: set "enabled": true in config.json under job_sources.sources.linkedin,
and add LINKEDIN_CLIENT_ID + LINKEDIN_CLIENT_SECRET to your .env file.

Implementation guide: https://learn.microsoft.com/en-us/linkedin/talent/job-postings
Note: LinkedIn API access for job search requires a partnership agreement.
"""
from typing import Any, Dict, List

from sources.base_source import BaseJobSource
from utils.exceptions import JobSourceError


class LinkedInSource(BaseJobSource):
    source_id = "linkedin"
    source_name = "LinkedIn"
    requires_auth = True

    async def search_jobs(
        self, profile: Dict[str, Any], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "LinkedIn source not yet implemented. "
            "See sources/linkedin_source.py for the implementation guide."
        )

    def normalize_job(self, raw_job: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("LinkedIn job normalization not yet implemented.")
