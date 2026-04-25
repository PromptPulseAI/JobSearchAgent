"""Tests for utils/logger.py — structured API call and audit logging."""
import json
from pathlib import Path
import pytest
from utils import logger as log_module


@pytest.fixture(autouse=True)
def redirect_logs(tmp_path, monkeypatch):
    """Redirect all log files to a temp directory for isolation."""
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(log_module, "_LOG_DIR", log_dir)
    monkeypatch.setattr(log_module, "_API_LOG", log_dir / "api_calls.jsonl")
    monkeypatch.setattr(log_module, "_AUDIT_LOG", log_dir / "audit.jsonl")
    monkeypatch.setattr(log_module, "_RUN_LOG", log_dir / "run.log")
    return log_dir


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestLogApiCall:
    def test_creates_entry(self):
        log_module.log_api_call(
            agent="writer", model="claude-sonnet-4-6",
            input_tokens=1000, output_tokens=500, duration_ms=2500.0,
            job_id="dice_123"
        )
        entries = _read_jsonl(log_module._API_LOG)
        assert len(entries) == 1
        e = entries[0]
        assert e["agent"] == "writer"
        assert e["model"] == "claude-sonnet-4-6"
        assert e["input_tokens"] == 1000
        assert e["output_tokens"] == 500
        assert e["job_id"] == "dice_123"
        assert e["type"] == "api_call"
        assert e["cost_usd"] > 0

    def test_cached_tokens_reduce_cost(self):
        log_module.log_api_call("a", "m", 1000, 100, 1000.0, cached_tokens=900)
        log_module.log_api_call("a", "m", 1000, 100, 1000.0, cached_tokens=0)
        entries = _read_jsonl(log_module._API_LOG)
        assert entries[0]["cost_usd"] < entries[1]["cost_usd"]

    def test_multiple_calls_appended(self):
        for i in range(3):
            log_module.log_api_call("a", "m", 100, 50, 500.0)
        assert len(_read_jsonl(log_module._API_LOG)) == 3

    def test_lane_field_recorded(self):
        log_module.log_api_call("writer", "m", 500, 200, 1000.0, lane="lane_a")
        entries = _read_jsonl(log_module._API_LOG)
        assert entries[0]["lane"] == "lane_a"


class TestLogLocalCall:
    def test_local_call_has_zero_cost(self):
        log_module.log_local_call("scout", "phi4-mini", 500, 200, 3000.0)
        entries = _read_jsonl(log_module._API_LOG)
        assert entries[0]["cost_usd"] == 0.0
        assert entries[0]["type"] == "local_call"


class TestAudit:
    def test_creates_audit_entry(self):
        log_module.audit("read", "profile_agent", "resume", "success")
        entries = _read_jsonl(log_module._AUDIT_LOG)
        assert len(entries) == 1
        e = entries[0]
        assert e["action"] == "read"
        assert e["agent"] == "profile_agent"
        assert e["data_type"] == "resume"
        assert e["status"] == "success"

    def test_pii_scrubbed_from_detail(self):
        log_module.audit("read", "agent", "file", "success",
                         detail="Processed email: user@example.com")
        entries = _read_jsonl(log_module._AUDIT_LOG)
        assert "user@example.com" not in (entries[0]["detail"] or "")

    def test_null_detail_is_null(self):
        log_module.audit("write", "tracker", "tracker", "success")
        entries = _read_jsonl(log_module._AUDIT_LOG)
        assert entries[0]["detail"] is None

    def test_job_id_recorded(self):
        log_module.audit("write", "tracker", "tracker", "success", job_id="dice_999")
        entries = _read_jsonl(log_module._AUDIT_LOG)
        assert entries[0]["job_id"] == "dice_999"


class TestRunLog:
    def test_writes_to_log_file_and_stdout(self, capsys):
        log_module.run_log("INFO", "orchestrator", "Starting daily run")
        log_file = log_module._RUN_LOG
        assert log_file.exists()
        content = log_file.read_text()
        assert "orchestrator" in content
        assert "Starting daily run" in content
        # Also printed to stdout
        out = capsys.readouterr().out
        assert "orchestrator" in out

    def test_pii_scrubbed_from_message(self):
        log_module.run_log("INFO", "agent", "Processed user@example.com profile")
        content = log_module._RUN_LOG.read_text()
        assert "user@example.com" not in content

    def test_job_id_in_log_line(self):
        log_module.run_log("INFO", "writer", "Generating resume", job_id="dice_456")
        content = log_module._RUN_LOG.read_text()
        assert "dice_456" in content
