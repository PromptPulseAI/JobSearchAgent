# Issue Tracker — JobSearchAgent

Issues are categorized by severity: 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## Open Issues

| ID | Sev | Status | Description | Blocking | Linked Commit |
|----|-----|--------|-------------|----------|---------------|
| I-004 | 🟢 | Open | `scoring_feedback.json` consumption: v1 logs only; automated weight adjustment deferred | Nothing | Future |
| I-007 | 🟢 | Open | Windows Task Scheduler XML requires machine to be on at 8AM | Nothing | Future |

---

## Resolved Issues

| ID | Resolved In | Description | Resolution |
|----|-------------|-------------|------------|
| I-005 | Commit 15 | Ollama model pull had no progress bar on first run | `_pull_model_with_progress()` streams `/api/pull` and prints MB progress every 5% |
| I-008 | Commit 15 | `pyspellchecker` flagged valid tech terms | Expanded `_TECH_ALLOWLIST` to 100+ terms across cloud, ML, DevOps, security domains |
| I-001 | Commit 14 | Dice MCP Python invocation method not confirmed; `_call_dice_mcp()` was a placeholder | Implemented via `ClaudeClient.call_mcp_tool()` using `beta.messages.create` with `mcp_servers`; Anthropic's infra is on Dice's allowlist |
| I-002 | Commit 12 | Dashboard needs Vite bundler + React setup | Implemented `dashboard/` with Vite + React; Python `api_server.py` provides REST API |
| I-003 | Commit 12 | Gate 1 headless mode `pending_approval.json` polling UX | Dashboard PendingReview panel polls `/api/pending` every 5s; `POST /api/approve` accepts/rejects |
| I-006 | Commit 6 | `gdpr.consent_acknowledged` gate missing from orchestrator | `_load_and_validate_config()` raises `ConsentError` if not set; `config.json` documents it |
| I-R01 | Commit 1 | `asyncio` in requirements.txt (it's stdlib) | Removed |
| I-R02 | Commit 1 | Missing `anthropic` SDK | Added to requirements.txt |
| I-R03 | Commit 1 | Missing `python-dotenv` | Added to requirements.txt |
| I-R04 | Commit 1 | Missing `pyspellchecker` | Added to requirements.txt |
| I-R05 | Commit 1 | `ollama_manager.py` absent from folder structure | Added to `utils/` |
| I-R06 | Commit 1 | JSON data files: root vs `data/` inconsistency | Standardized to `data/` directory |
| I-R07 | Commit 1 | `asyncio.get_event_loop()` deprecated in Python 3.10+ | Using `asyncio.get_running_loop()` throughout |
| I-R08 | Commit 1 | `--skip-gate1-if-no-new` used in Task Scheduler XML but not in `run.py` args | Added to argparse |
| I-R09 | Commit 1 | `--no-local-model` flag missing from `run.py` | Added to argparse |
| I-R10 | Commit 1 | API call logger described but had no home | `utils/logger.py` created |
| I-R11 | Commit 1 | Prompt caching entirely absent | Added to `api_client.py` with `cache_control: ephemeral` |
| I-R12 | Commit 1 | No pluggable source architecture | `sources/` directory with registry pattern |
| I-R13 | Commit 1 | No GDPR compliance | `utils/pii_scrubber.py`, `GDPR.md`, `scripts/gdpr_erasure.py` |
| I-R14 | Commit 1 | No custom exception hierarchy | `utils/exceptions.py` |
| I-R15 | Commit 1 | No `requirements-dev.txt` | Created with pytest, pytest-asyncio, pytest-mock |

---

## How to File an Issue

Add a row to the Open Issues table above with:
- **ID**: Next sequential `I-NNN`
- **Sev**: 🔴/🟠/🟡/🟢 based on impact
- **Status**: Open | In Progress | Blocked
- **Description**: One sentence, clear and specific
- **Blocking**: What can't be built until this is resolved
- **Linked Commit**: Which commit this belongs to
