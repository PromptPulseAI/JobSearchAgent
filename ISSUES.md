# Issue Tracker — JobSearchAgent

Issues are categorized by severity: 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low

---

## Open Issues

| ID | Sev | Status | Description | Blocking | Linked Commit |
|----|-----|--------|-------------|----------|---------------|
| I-001 | 🟠 | Open | Dice MCP Python invocation method not confirmed. `DiceSource._call_dice_mcp()` is a placeholder. | Commit 5 | Commit 5 |
| I-002 | 🟢 | Open | Dashboard needs Vite bundler + React setup (single JSX file cannot run standalone) | Commit 12 | Commit 12 |
| I-003 | 🟡 | Open | Gate 1 headless mode: `pending_approval.json` polling UX needs UI design before dashboard build | Commit 12 | Commit 12 |
| I-004 | 🟢 | Open | `scoring_feedback.json` consumption logic in Scout Agent: v1 logs only; automated weight adjustment deferred | Commit 5 | Future |
| I-005 | 🟢 | Open | Ollama model pull (~2.3GB) can take 10+ minutes on first run — need progress indicator in `ollama_manager.py` | Commit 3 | Commit 3 |
| I-006 | 🟡 | Open | `gdpr.consent_acknowledged` is false by default — orchestrator should warn user and refuse to run until set to true | Commit 6 | Commit 6 |
| I-007 | 🟢 | Open | Windows Task Scheduler XML uses `--skip-gate1-if-no-new` which requires Surface Pro 4 to be on at 8AM | Commit 13 | Commit 13 |
| I-008 | 🟡 | Open | `pyspellchecker` may flag valid tech terms (e.g., "Kubernetes", "PostgreSQL") as misspelled — needs allowlist | Commit 2 | Commit 2 |

---

## Resolved Issues

| ID | Resolved In | Description | Resolution |
|----|-------------|-------------|------------|
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
| I-R11 | Commit 1 | Prompt caching entirely absent | Added to `api_client.py` design (Commit 3) |
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
