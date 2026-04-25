"""
Structured logging for JobSearchAgent. Two output streams:
  - api_calls.jsonl  : Every LLM call — model, tokens, duration, cost estimate
  - audit.jsonl      : Every data read/write — GDPR Article 5 audit trail
  - run.log          : Human-readable run progress (PII-safe)

All entries are scrubbed of PII before writing.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from utils.pii_scrubber import scrub

# Paths are module-level so tests can monkeypatch them
_LOG_DIR = Path("data/logs")
_API_LOG = _LOG_DIR / "api_calls.jsonl"
_AUDIT_LOG = _LOG_DIR / "audit.jsonl"
_RUN_LOG = _LOG_DIR / "run.log"

# Approximate Claude API pricing per 1M tokens (update as pricing changes)
_INPUT_COST_PER_1M = 3.00    # USD  — standard input
_CACHE_READ_PER_1M = 0.30    # USD  — cache read (10% of input)
_OUTPUT_COST_PER_1M = 15.00  # USD  — output


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _append_jsonl(filepath: Path, entry: dict) -> None:
    _ensure_log_dir()
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── API / LLM call logging ────────────────────────────────────────────────────

def log_api_call(
    agent: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: float,
    job_id: Optional[str] = None,
    lane: Optional[str] = None,
    cached_tokens: int = 0,
) -> None:
    """Log a Claude API call with token counts and estimated cost."""
    billable_input = max(0, input_tokens - cached_tokens)
    cost = (
        billable_input * _INPUT_COST_PER_1M / 1_000_000
        + cached_tokens * _CACHE_READ_PER_1M / 1_000_000
        + output_tokens * _OUTPUT_COST_PER_1M / 1_000_000
    )
    _append_jsonl(_API_LOG, {
        "timestamp": _now(),
        "type": "api_call",
        "agent": agent,
        "model": model,
        "job_id": job_id,
        "lane": lane,
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "duration_ms": round(duration_ms, 1),
        "cost_usd": round(cost, 6),
    })


def log_local_call(
    agent: str,
    model: str,
    prompt_chars: int,
    response_chars: int,
    duration_ms: float,
    job_id: Optional[str] = None,
) -> None:
    """Log an Ollama local inference call (cost = $0.00)."""
    _append_jsonl(_API_LOG, {
        "timestamp": _now(),
        "type": "local_call",
        "agent": agent,
        "model": model,
        "job_id": job_id,
        "prompt_chars": prompt_chars,
        "response_chars": response_chars,
        "duration_ms": round(duration_ms, 1),
        "cost_usd": 0.0,
    })


# ── GDPR audit trail ──────────────────────────────────────────────────────────

def audit(
    action: str,
    agent: str,
    data_type: str,
    status: str,
    job_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """
    Write a GDPR audit trail entry. Records every read/write of personal data.
    action   : "read" | "write" | "delete" | "restore"
    data_type: "resume" | "profile" | "tracker" | "docx" | ...
    status   : "success" | "failure"
    detail   : Free text — PII is automatically scrubbed before writing
    """
    _append_jsonl(_AUDIT_LOG, {
        "timestamp": _now(),
        "action": action,
        "agent": agent,
        "data_type": data_type,
        "job_id": job_id,
        "status": status,
        "detail": scrub(detail) if detail else None,
    })


# ── Human-readable run log ────────────────────────────────────────────────────

def run_log(
    level: str,
    agent: str,
    message: str,
    job_id: Optional[str] = None,
) -> None:
    """
    Write a human-readable log line. PII is scrubbed before writing.
    level: INFO | WARNING | ERROR | DEBUG
    """
    _ensure_log_dir()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    job_tag = f" [{job_id}]" if job_id else ""
    line = f"{ts} {level.upper():8s} [{agent}]{job_tag} {scrub(message)}\n"
    with open(_RUN_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")
