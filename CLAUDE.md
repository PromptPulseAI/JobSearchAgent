# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install Python dependencies
pip install -r requirements-dev.txt

# Run all tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_ats_scanner.py -v

# Run a single test by name
python -m pytest tests/test_logger.py::TestLogApiCall::test_creates_entry -v

# Run the agent (dry-run — no API calls, no files written)
python run.py --dry-run

# Run with existing job matches, skip live search
python run.py --skip-search --no-local-model

# GDPR right-to-erasure (deletes all personal data)
python scripts/gdpr_erasure.py

# Dashboard (start API server, then open in browser)
python dashboard/api_server.py &
cd dashboard && npm install && npm run dev
```

## Architecture

### Six-agent pipeline

```
Orchestrator → Profile Agent → Scout Agent → Gate 1 (user approval)
                                              ↓
              Writer Agent → Reviewer Agent → Fix Loop → Gate 2 → Tracker Agent
```

All agents inherit `BaseAgent` (`agents/base_agent.py`). They communicate exclusively via JSON files in `data/`. No agent calls another agent directly. The Orchestrator (`agents/orchestrator.py`) is the only entry point.

### Build order

Commits 1–14 are complete. The full pipeline is implemented and all 354 tests pass. When adding new features, follow the same pattern: write tests first, keep the suite green.

### Pluggable job sources

`sources/registry.py` auto-discovers any file matching `sources/*_source.py` that subclasses `BaseJobSource`. To add a new source: create the file, subclass `BaseJobSource`, set `source_id`/`source_name`/`requires_auth`, implement `search_jobs()` and `normalize_job()`, add a config block in `config.json`. No other registration needed.

### Hybrid LLM strategy (three tiers)

- **Tier 1 — pure Python** (zero cost): ATS scanning, format validation, dedup, scoring math
- **Tier 2 — Ollama Phi-4-mini** (~$0.00): keyword extraction, skills cross-reference, scoring breakdown — CPU-only, ~15-20 tok/s on Surface Pro 4
- **Tier 3 — Claude API** (`claude-sonnet-4-6`): profile extraction, resume tailoring, cover letter, quality review

Call `local_llm.unload()` before Writer Agent's 3 parallel API lanes to free ~3.5GB RAM. Call `reload()` after.

### Prompt caching

`ClaudeClient.generate()` (Commit 3) wraps the system prompt in `cache_control: {type: "ephemeral"}` by default. The candidate profile (long, stable) is also cached per run. This cuts input token costs ~50-60%.

### Data flow

Every agent reads from and writes to `data/`. Key files:
- `data/candidate_profile.json` — written by Profile Agent, read by all others
- `data/job_matches.json` — written by Scout Agent
- `data/application_tracker.json` — written exclusively by Tracker Agent via `atomic_write_json()`
- `data/pending_approval.json` — Gate 1 writes this for headless/dashboard mode

### GDPR compliance

- `utils/pii_scrubber.py` — `scrub()` and `scrub_dict()` must wrap all text before it reaches any log
- `utils/logger.py` — `audit()` records every data read/write; `log_api_call()` records every LLM call
- `config.json` — `gdpr.consent_acknowledged` must be `true` before the orchestrator will run (enforced in Commit 6)
- `scripts/gdpr_erasure.py` — Article 17 right to erasure; writes an erasure certificate

### Atomic writes

Only `atomic_write_json()` from `utils/file_io.py` may write `application_tracker.json`. The pattern: backup → temp file → validate readback → `os.replace()`. Never use `write_json()` for the tracker.

### Error hierarchy

`utils/exceptions.py` defines 16 typed exceptions. All carry `agent`, `job_id`, `severity` (Severity enum), `recoverable`, and `context`. Catch by type in the orchestrator — not by message. `JobSourceError` adds `source_id`; `RateLimitError` adds `retry_after`.

### Issue and TODO tracking

`ISSUES.md` — open blockers with severity and linked commit. Update when a blocker is found or resolved.  
`TODO.md` — build tracker mirroring commit order. Mark tasks done as each commit is completed.

Key open issues (non-blocking):
- **I-004** 🟢 — `scoring_feedback.json` is log-only; automated weight adjustment is future work
- **I-005** 🟢 — Ollama model pull (~2.3GB) has no progress bar on first run
- **I-008** 🟡 — `pyspellchecker` may flag tech terms; allowlist can be expanded

See `ISSUES.md` for the full list including resolved items.

### Dice MCP integration

`DiceSource` calls the Dice MCP server (`https://mcp.dice.com/mcp`) via
`ClaudeClient.call_mcp_tool()`, which uses `client.beta.messages.create` with
`mcp_servers`. Anthropic's infrastructure makes the actual HTTP call (Dice
allowlists Anthropic's IPs). The `mcp-client-2025-04-04` beta flag is required.

### Testing

`pytest.ini` sets `testpaths = tests` and `asyncio_mode = auto`. Fixtures are in `tests/conftest.py` and `tests/fixtures/`. All 354 tests must stay green before any new commit.
