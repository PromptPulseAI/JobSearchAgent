# TODO Tracker — JobSearchAgent

Build order follows `claude_code_technical_instructions.md` Section 13.
Status: ✅ Done | 🔄 In Progress | ⏳ Pending | ❌ Blocked

---

## Phase 0 — Pre-Build Decisions (resolved in Commit 1)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 0.1 | Standardize all JSON data files to `data/` directory | ✅ | |
| 0.2 | Gate 1 headless mode: writes `data/pending_approval.json`, dashboard polls it | ✅ | |
| 0.3 | Dice MCP: Python adapter class (`sources/dice_source.py`) via Claude beta API | ✅ | I-001 resolved in Commit 14 |
| 0.4 | Pluggable source architecture via `sources/registry.py` auto-discovery | ✅ | |
| 0.5 | GDPR compliance framework (`pii_scrubber`, `gdpr_erasure.py`, `GDPR.md`) | ✅ | |

---

## Phase 1 — Foundation

### Commit 1: Project Scaffolding ✅

| # | Task | Status |
|---|------|--------|
| 1.1 | Directory structure | ✅ |
| 1.2 | `.gitignore` (personal data excluded) | ✅ |
| 1.3 | `requirements.txt` | ✅ |
| 1.4 | `requirements-dev.txt` | ✅ |
| 1.5 | `config.json` (pluggable sources + GDPR + all spec settings) | ✅ |
| 1.6 | `.env.example` | ✅ |
| 1.7 | `README.md` | ✅ |
| 1.8 | `ISSUES.md` | ✅ |
| 1.9 | `TODO.md` | ✅ |
| 1.10 | `GDPR.md` | ✅ |
| 1.11 | All agent skeletons (`base_agent`, `orchestrator`, `profile_agent`, etc.) | ✅ |
| 1.12 | All source skeletons (`base_source`, `registry`, `dice_source`, etc.) | ✅ |
| 1.13 | All util skeletons (`api_client`, `local_llm`, `ollama_manager`) | ✅ |
| 1.14 | `run.py` skeleton with all CLI flags | ✅ |
| 1.15 | `scripts/gdpr_erasure.py` | ✅ |
| 1.16 | `scripts/job_search_daily.xml` (Task Scheduler) | ✅ |
| 1.17 | `dashboard/` scaffolding | ✅ |
| 1.18 | `.gitkeep` files for empty dirs | ✅ |

### Commit 2: Utility Layer ✅

| # | Task | Status |
|---|------|--------|
| 2.1 | `utils/exceptions.py` — full custom exception hierarchy | ✅ |
| 2.2 | `utils/pii_scrubber.py` — full GDPR PII scrubbing | ✅ |
| 2.3 | `utils/logger.py` — full API call + audit logger | ✅ |
| 2.4 | `utils/file_io.py` — full atomic JSON I/O + backup | ✅ |
| 2.5 | `utils/docx_reader.py` — full .docx text extraction | ✅ |
| 2.6 | `utils/ats_scanner.py` — full ATS keyword extraction + coverage | ✅ |
| 2.7 | `utils/format_validator.py` — full resume + cover letter validation | ✅ |
| 2.8 | `tests/conftest.py` + fixtures | ✅ |
| 2.9–2.14 | All utility test files | ✅ |

### Commit 3: LLM Integration ✅

| # | Task | Status |
|---|------|--------|
| 3.1 | `utils/api_client.py` — full implementation (anthropic SDK, prompt caching, retry) | ✅ |
| 3.2 | `utils/local_llm.py` — full Ollama wrapper with unload/reload | ✅ |
| 3.3 | `utils/ollama_manager.py` — auto-start, model pull with progress | ✅ |
| 3.4 | `tests/test_llm_clients.py` smoke tests | ✅ |

---

## Phase 2 — Profile Agent ✅

### Commit 4: Profile Agent

| # | Task | Status |
|---|------|--------|
| 4.1 | `agents/profile_agent.py` — full implementation | ✅ |
| 4.2 | `prompts/profile_agent.txt` | ✅ |
| 4.3 | `tests/test_profile_agent.py` | ✅ |

---

## Phase 3 — Scout Agent ✅

### Commit 5: Scout Agent

| # | Task | Status |
|---|------|--------|
| 5.1 | `agents/scout_agent.py` — full implementation | ✅ |
| 5.2 | `sources/dice_source.py` — real implementation via Claude beta MCP API | ✅ |
| 5.3 | `prompts/scout_agent.txt` | ✅ |
| 5.4 | `tests/test_scout_agent.py` | ✅ |
| 5.5 | `tests/test_dice_source.py` | ✅ |

---

## Phase 4 — Orchestrator + Gate 1 ✅

### Commit 6: Orchestrator

| # | Task | Status |
|---|------|--------|
| 6.1 | `agents/orchestrator.py` — full pipeline coordinator | ✅ |
| 6.2 | GDPR consent gate (`consent_acknowledged` check) | ✅ |
| 6.3 | `run.py` — wired to orchestrator | ✅ |
| 6.4 | `tests/test_orchestrator.py` | ✅ |

---

## Phase 5 — Writer Agent ✅

### Commit 7: Writer Agent

| # | Task | Status |
|---|------|--------|
| 7.1 | `agents/writer_agent.py` — full implementation | ✅ |
| 7.2 | `prompts/writer_agent.txt` | ✅ |
| 7.3 | `tests/test_writer_agent.py` | ✅ |

---

## Phase 6 — Reviewer Agent ✅

### Commit 8: Reviewer Agent

| # | Task | Status |
|---|------|--------|
| 8.1 | `agents/reviewer_agent.py` — full implementation | ✅ |
| 8.2 | `prompts/reviewer_agent.txt` | ✅ |
| 8.3 | `tests/test_reviewer_agent.py` | ✅ |

---

## Fix Loop + Gate 2 ✅

### Commit 9: Fix Loop Integration

| # | Task | Status |
|---|------|--------|
| 9.1 | `orchestrator._fix_loop()` — Writer → Reviewer → fix cycle, max 2 retries | ✅ |
| 9.2 | `orchestrator._gate2()` — user approval before moving to next job | ✅ |
| 9.3 | `tests/test_fix_loop.py` | ✅ |

---

## Phase 7 — Tracker Agent ✅

### Commit 10: Tracker Agent

| # | Task | Status |
|---|------|--------|
| 10.1 | `agents/tracker_agent.py` — full implementation | ✅ |
| 10.2 | `prompts/tracker_agent.txt` | ✅ |
| 10.3 | `tests/test_tracker_agent.py` | ✅ |

---

## Phase 8 — Integration + Dashboard ✅

### Commit 11: run.py + E2E Tests

| # | Task | Status |
|---|------|--------|
| 11.1 | `run.py` — fully wired orchestrator entry point | ✅ |
| 11.2 | `tests/test_e2e.py` — full pipeline integration tests | ✅ |

### Commit 12: Dashboard

| # | Task | Status |
|---|------|--------|
| 12.1 | `dashboard/api_server.py` — Python stdlib REST API server | ✅ |
| 12.2 | `dashboard/src/dashboard.jsx` — React dashboard (6 panels) | ✅ |
| 12.3 | Gate 1 headless approval via dashboard | ✅ |
| 12.4 | Status update UI with forward-only transition enforcement | ✅ |

---

## Phase 9 — Polish + Automation ✅

### Commit 13: Polish

| # | Task | Status |
|---|------|--------|
| 13.1 | `scripts/push_results.py` — optional GitHub auto-push | ✅ |
| 13.2 | `scripts/job_search_daily.xml` — Windows Task Scheduler | ✅ |
| 13.3 | `README.md` — complete setup + usage guide | ✅ |

---

## Commit 14: Dice MCP Integration ✅

| # | Task | Status |
|---|------|--------|
| 14.1 | `utils/api_client.py` — `call_mcp_tool()` via `beta.messages.create` + `mcp_servers` | ✅ |
| 14.2 | `sources/dice_source.py` — real `_call_dice_mcp()` replacing `NotImplementedError` | ✅ |
| 14.3 | `sources/base_source.py` — `claude = None` attribute for injection | ✅ |
| 14.4 | `agents/scout_agent.py` — inject `source.claude` before each search | ✅ |
| 14.5 | `requirements.txt` — `mcp>=1.0.0` | ✅ |
| 14.6 | `tests/test_dice_source.py` — 25 new tests | ✅ |
| 14.7 | `tests/test_llm_clients.py` — 6 new `call_mcp_tool` tests | ✅ |

---

## Deferred / Future

- Automated scoring weight adjustment from `scoring_feedback.json` (I-004)
- Ollama model pull progress indicator (I-005)
- `pyspellchecker` tech term allowlist expansion (I-008)
- Multiple additional job boards: ZipRecruiter, Glassdoor, LinkedIn (when API available)
- Skill gap analysis and learning path recommendations
- Email follow-up template generation
