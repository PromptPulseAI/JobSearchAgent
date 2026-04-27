"""Tests for utils/exceptions.py — custom exception hierarchy."""
import pytest
from utils.exceptions import (
    JobSearchAgentError, ConfigError, ConsentError,
    ProfileAgentError, ScoutAgentError, WriterAgentError,
    ReviewerAgentError, TrackerAgentError,
    APIError, RateLimitError, APITimeoutError,
    LocalLLMError, OllamaNotAvailableError,
    JobSourceError, AllSourcesFailedError,
    FileIOError, DocxGenerationError, Severity,
)


class TestJobSearchAgentError:
    def test_basic_construction(self):
        err = JobSearchAgentError("test error", agent="orchestrator", job_id="dice_123")
        assert str(err) == "test error"
        assert err.agent == "orchestrator"
        assert err.job_id == "dice_123"
        assert err.recoverable is True

    def test_to_dict_contains_all_fields(self):
        err = JobSearchAgentError("test", agent="scout", severity=Severity.HIGH, job_id="x")
        d = err.to_dict()
        assert d["error_type"] == "JobSearchAgentError"
        assert d["severity"] == "high"
        assert d["agent"] == "scout"
        assert d["job_id"] == "x"
        assert "context" in d

    def test_context_defaults_to_empty_dict(self):
        err = JobSearchAgentError("msg")
        assert err.context == {}

    def test_custom_context(self):
        err = JobSearchAgentError("msg", context={"key": "val"})
        assert err.context["key"] == "val"


class TestSpecializedErrors:
    def test_config_error_is_critical_and_not_recoverable(self):
        err = ConfigError("bad config")
        assert err.severity == Severity.CRITICAL
        assert err.recoverable is False

    def test_consent_error_inherits_config_error(self):
        err = ConsentError("no consent")
        assert isinstance(err, ConfigError)
        assert err.recoverable is False

    def test_profile_agent_error_defaults(self):
        err = ProfileAgentError("parse failed")
        assert err.agent == "profile_agent"
        assert err.severity == Severity.CRITICAL
        assert err.recoverable is False

    def test_tracker_error_is_critical(self):
        err = TrackerAgentError("write failed")
        assert err.severity == Severity.CRITICAL

    def test_file_io_error_is_high_severity(self):
        err = FileIOError("not found")
        assert err.severity == Severity.HIGH

    def test_rate_limit_error_has_status_and_retry(self):
        err = RateLimitError("too fast", retry_after=30.0)
        assert err.status_code == 429
        assert err.retry_after == 30.0

    def test_job_source_error_has_source_id(self):
        err = JobSourceError("dice down", source_id="dice")
        assert err.source_id == "dice"
        d = err.to_dict()
        assert d["source_id"] == "dice"

    def test_docx_generation_inherits_writer(self):
        err = DocxGenerationError("bad docx")
        assert isinstance(err, WriterAgentError)

    def test_all_sources_failed_inherits_scout(self):
        err = AllSourcesFailedError("nothing found")
        assert isinstance(err, ScoutAgentError)

    def test_ollama_not_available_inherits_local_llm(self):
        err = OllamaNotAvailableError()
        assert isinstance(err, LocalLLMError)
        assert "unavailable" in str(err)

    def test_api_timeout_inherits_api_error(self):
        err = APITimeoutError("timed out")
        assert isinstance(err, APIError)

    def test_rate_limit_inherits_api_then_base(self):
        err = RateLimitError("slow down")
        assert isinstance(err, APIError)
        assert isinstance(err, JobSearchAgentError)
        assert isinstance(err, Exception)
