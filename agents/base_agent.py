"""
Abstract base class for all JobSearchAgent agents.
Provides: logging interface, prompt loading, and standard error-handling pattern.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import run_log, audit
from utils.file_io import read_text
from utils.exceptions import FileIOError


class BaseAgent(ABC):
    """
    All six agents inherit from this base.
    Subclasses must declare a `name` class attribute and implement `run()`.
    """

    name: str  # Set by each subclass, e.g. "profile_agent"

    def __init__(self, config: Dict[str, Any], claude_client=None, local_llm=None):
        self.config = config
        self.claude = claude_client
        self.local = local_llm
        self._prompts_dir = Path(config.get("paths", {}).get("prompts_dir", "prompts"))

    def load_prompt(self, filename: str) -> str:
        """Load a system prompt from the prompts/ directory."""
        try:
            return read_text(self._prompts_dir / filename, agent=self.name)
        except FileIOError as exc:
            raise FileIOError(
                f"Prompt file missing: {filename}. Did you run setup?",
                agent=self.name,
            ) from exc

    def log(self, level: str, message: str, job_id: Optional[str] = None) -> None:
        run_log(level, self.name, message, job_id=job_id)

    def audit(
        self,
        action: str,
        data_type: str,
        status: str,
        job_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        audit(action, self.name, data_type, status, job_id=job_id, detail=detail)

    @abstractmethod
    async def run(self, *args, **kwargs) -> Any:
        """Main entry point for this agent. Implemented by each subclass."""
