"""
Custom exception hierarchy for JobSearchAgent.
Every exception carries: agent name, job_id, severity, recoverability, and context dict.
This makes error handling in the orchestrator deterministic — catch by type, not message.
"""
from enum import Enum
from typing import Any, Dict, Optional


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class JobSearchAgentError(Exception):
    """Base exception. All agent errors inherit from this."""

    def __init__(
        self,
        message: str,
        agent: Optional[str] = None,
        job_id: Optional[str] = None,
        severity: Severity = Severity.MEDIUM,
        recoverable: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.agent = agent
        self.job_id = job_id
        self.severity = severity
        self.recoverable = recoverable
        self.context = context or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": type(self).__name__,
            "message": str(self),
            "agent": self.agent,
            "job_id": self.job_id,
            "severity": self.severity.value,
            "recoverable": self.recoverable,
            "context": self.context,
        }


# ── Configuration ─────────────────────────────────────────────────────────────

class ConfigError(JobSearchAgentError):
    """Invalid or missing configuration. Always non-recoverable."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.CRITICAL)
        kwargs["recoverable"] = False
        super().__init__(message, **kwargs)


class ConsentError(ConfigError):
    """GDPR consent not acknowledged in config.json."""


# ── File I/O ──────────────────────────────────────────────────────────────────

class FileIOError(JobSearchAgentError):
    """File read/write failure."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.HIGH)
        super().__init__(message, **kwargs)


# ── Agent errors ──────────────────────────────────────────────────────────────

class ProfileAgentError(JobSearchAgentError):
    """Profile agent failed to parse input files. Critical — pipeline cannot continue."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.CRITICAL)
        kwargs.setdefault("recoverable", False)
        super().__init__(message, agent="profile_agent", **kwargs)


class ScoutAgentError(JobSearchAgentError):
    """Scout agent failed to search or score jobs."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, agent="scout_agent", **kwargs)


class WriterAgentError(JobSearchAgentError):
    """Writer agent failed to generate documents."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, agent="writer_agent", **kwargs)


class DocxGenerationError(WriterAgentError):
    """Failed to generate a valid .docx file after retry."""


class ReviewerAgentError(JobSearchAgentError):
    """Reviewer agent failed. Degraded — mechanical checks still shown."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.MEDIUM)
        super().__init__(message, agent="reviewer_agent", **kwargs)


class TrackerAgentError(JobSearchAgentError):
    """Tracker agent failed to update state. Critical — data integrity risk."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.CRITICAL)
        super().__init__(message, agent="tracker_agent", **kwargs)


# ── Job sources ───────────────────────────────────────────────────────────────

class JobSourceError(ScoutAgentError):
    """A specific job board source failed."""
    def __init__(self, message: str, source_id: Optional[str] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.source_id = source_id

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["source_id"] = self.source_id
        return d


class AllSourcesFailedError(ScoutAgentError):
    """Every configured job source failed — no jobs can be fetched."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.HIGH)
        super().__init__(message, **kwargs)


# ── Claude API ────────────────────────────────────────────────────────────────

class APIError(JobSearchAgentError):
    """Claude API call failed."""
    def __init__(self, message: str, status_code: Optional[int] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.status_code = status_code


class RateLimitError(APIError):
    """Hit rate limit on Claude API (HTTP 429). Retry after delay."""
    def __init__(self, message: str, retry_after: Optional[float] = None, **kwargs):
        super().__init__(message, status_code=429, **kwargs)
        self.retry_after = retry_after


class APITimeoutError(APIError):
    """Claude API call timed out."""
    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)


# ── Local LLM ─────────────────────────────────────────────────────────────────

class LocalLLMError(JobSearchAgentError):
    """Ollama / local model call failed."""
    def __init__(self, message: str, **kwargs):
        kwargs.setdefault("severity", Severity.MEDIUM)
        super().__init__(message, **kwargs)


class OllamaNotAvailableError(LocalLLMError):
    """Ollama server is not running and could not be started."""
    def __init__(self, message: str = "Ollama server unavailable", **kwargs):
        kwargs.setdefault("severity", Severity.HIGH)
        super().__init__(message, **kwargs)
