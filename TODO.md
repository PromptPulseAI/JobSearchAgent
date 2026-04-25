# TODO Tracker — JobSearchAgent

Build order follows `claude_code_technical_instructions.md` Section 13.
Status: ✅ Done | 🔄 In Progress | ⏳ Pending | ❌ Blocked

---

## Phase 0 — Pre-Build Decisions (resolved in Commit 1)

| # | Task | Status | Notes |
|---|------|--------|-------|
| 0.1 | Standardize all JSON data files to `data/` directory | ✅ | |
| 0.2 | Gate 1 headless mode: writes `data/pending_approval.json`, dashboard polls it | ✅ | See I-003 |
| 0.3 | Dice MCP: Python adapter class (`sources/dice_source.py`) wrapping MCP tool | ✅ | See I-001 |
| 0.4 | Pluggable source architecture via `sources/registry.py` auto-discovery | ✅ | |
| 0.5 | GDPR compliance framework (`pii_scrubber`, `gdpr_erasure.py`, `GDPR.md`) | ✅ | |

---

## Phase 1 — Foundation

### Commit 1: Project Scaffolding

| # | Task | Status |
|---|------|--------|
| 1.1 | Directory structure | ✅ |
| 1.2 | `.gitignore` (personal data excluded) | ✅ |
| 1.3 | `requirements.txt` (anthropic, python-docx, httpx, python-dotenv, pyspellchecker) | ✅ |
| 1.4 | `requirements-dev.txt` (pytest, pytest-asyncio, pytest-mock) | ✅ |
| 1.5 | `package.json` (root, docx npm package) | ✅ |
| 1.6 | `config.json` (pluggable sources + GDPR settings + all spec settings) | ✅ |
| 1.7 | `.env.example` | ✅ |
| 1.8 | `README.md` (full setup guide) | 🔄 |
| 1.9 | `ISSUES.md` (issue tracker) | ✅ |
| 1.10 | `TODO.md` (this file) | 🔄 |
| 1.11 | `GDPR.md` (data handling policy) | ⏳ |
| 1.12 | `agents/base_agent.py` (abstract base) | ⏳ |
| 1.13 | `agents/orchestrator.py` (skeleton) | ⏳ |
| 1.14 | `agents/profile_agent.py` (skeleton) | ⏳ |
| 1.15 | `agents/scout_agent.py` (skeleton) | ⏳ |
| 1.16 | `agents/writer_agent.py` (skeleton) | ⏳ |
| 1.17 | `agents/reviewer_agent.py` (skeleton) | ⏳ |
| 1.18 | `agents/tracker_agent.py` (skeleton) | ⏳ |
| 1.19 | `sources/base_source.py` (abstract base) | ⏳ |
| 1.20 | `sources/registry.py` (auto-discovery) | ⏳ |
| 1.21 | `sources/dice_source.py` (adapter with I-001 placeholder) | ⏳ |
| 1.22 | `sources/indeed_source.py` (stub) | ⏳ |
| 1.23 | `sources/linkedin_source.py` (stub) | ⏳ |
| 1.24 | `utils/api_client.py` (skeleton — full in Commit 3) | ⏳ |
| 1.25 | `utils/local_llm.py` (skeleton — full in Commit 3) | ⏳ |
| 1.26 | `utils/ollama_manager.py` (skeleton — full in Commit 3) | ⏳ |
| 1.27 | `utils/docx_writer.js` (Node.js skeleton) | ⏳ |
| 1.28 | All `prompts/*.txt` files (placeholders) | ⏳ |
| 1.29 | `run.py` (skeleton with ALL CLI flags) | ⏳ |
| 1.30 | `scripts/gdpr_erasure.py` | ⏳ |
| 1.31 | `scripts/job_search_daily.xml` (Task Scheduler) | ⏳ |
| 1.32 | `dashboard/package.json` + `vite.config.js` + `index.html` | ⏳ |
| 1.33 | `dashboard/src/dashboard.jsx` (skeleton) | ⏳ |
| 1.34 | `.gitkeep` files for empty dirs | ⏳ |

### Commit 2: Utility Layer (full implementations + tests)

| # | Task | Status |
|---|------|--------|
| 2.1 | `utils/exceptions.py` — full custom exception hierarchy | ⏳ |
| 2.2 | `utils/pii_scrubber.py` — full GDPR PII scrubbing | ⏳ |
| 2.3 | `utils/logger.py` — full API call + audit logger | ⏳ |
| 2.4 | `utils/file_io.py` — full atomic JSON I/O + backup | ⏳ |
| 2.5 | `utils/docx_reader.py` — full .docx text extraction | ⏳ |
| 2.6 | `utils/ats_scanner.py` — full ATS keyword extraction + coverage | ⏳ |
| 2.7 | `utils/format_validator.py` — full resume + cover letter validation | ⏳ |
| 2.8 | `tests/conftest.py` + fixtures | ⏳ |
| 2.9 | `tests/test_exceptions.py` | ⏳ |
| 2.10 | `tests/test_pii_scrubber.py` | ⏳ |
| 2.11 | `tests/test_logger.py` | ⏳ |
| 2.12 | `tests/test_file_io.py` | ⏳ |
| 2.13 | `tests/test_ats_scanner.py` | ⏳ |
| 2.14 | `tests/test_format_validator.py` | ⏳ |
| 2.15 | Run `pytest` — all tests must pass before commit | ⏳ |

### Commit 3: LLM Integration

| # | Task | Status |
|---|------|--------|
| 3.1 | `utils/api_client.py` — full implementation (anthropic SDK, prompt caching, retry) | ⏳ |
| 3.2 | `utils/local_llm.py` — full Ollama wrapper with unload/reload | ⏳ |
| 3.3 | `utils/ollama_manager.py` — auto-start, model pull, progress indicator (I-005) | ⏳ |
| 3.4 | Smoke tests for both (mock API calls) | ⏳ |

---

## Phase 2 — Profile Agent (Commit 4)
⏳ Pending — starts after Commit 3

## Phase 3 — Scout Agent (Commit 5)
⏳ Pending — resolve I-001 before starting

## Phase 4 — Orchestrator + Gate 1 (Commit 6)
⏳ Pending — resolve I-006 (GDPR consent check)

## Phase 5 — Writer Agent (Commit 7)
⏳ Pending

## Phase 6 — Reviewer Agent (Commit 8)
⏳ Pending

## Fix Loop + Gate 2 (Commit 9)
⏳ Pending

## Phase 7 — Tracker Agent (Commit 10)
⏳ Pending

## Phase 8 — Integration + Dashboard (Commits 11-12)
⏳ Pending

## Phase 9 — Polish + Automation (Commit 13)
⏳ Pending

---

## Deferred / Future
- Automated scoring weight adjustment from `scoring_feedback.json` (see I-004)
- Multiple job boards: ZipRecruiter, Glassdoor, etc.
- Skill gap analysis and learning path recommendations
- Email follow-up template generation
- Tailscale remote monitoring setup
