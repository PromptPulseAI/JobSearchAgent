# JobSearchAgent

A multi-agent AI system that runs daily to find, score, and tailor job applications. Six specialized agents coordinate through a shared data layer, each with a focused system prompt and clear responsibilities.

**Target hardware:** Surface Pro 4 (6th-gen Intel, 4-16GB RAM, no discrete GPU, Windows 10)
**Daily cost:** ~$0.11 (3 approved jobs, hybrid local+API approach)

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Ollama (optional — for 8GB+ RAM systems)
- Anthropic API key

### Setup

```bash
# 1. Clone and install
git clone <repo>
cd job-search-agent
pip install -r requirements.txt
npm install

# 2. Configure
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY

# 3. Set GDPR consent (read GDPR.md first)
# In config.json: set "gdpr.consent_acknowledged": true

# 4. Add your input files
# Input_Files/master_resume.docx
# Input_Files/job_requirements.docx
# Skills/technical_skills.docx
# Skills/soft_skills.docx         (optional)
# Skills/certifications.docx      (optional)

# 5. Install local model (8GB+ RAM systems)
ollama pull phi4-mini

# 6. Test run (no API calls, no file writes)
python run.py --dry-run

# 7. First real run
python run.py
```

### 4GB RAM Systems

```bash
# Skip Ollama — use Claude API for all AI tasks (~30% higher cost)
python run.py --no-local-model
```

---

## Daily Automation (Windows Task Scheduler)

Import `scripts/job_search_daily.xml` into Task Scheduler, or set it up manually:

```
Program: python
Arguments: run.py --skip-gate1-if-no-new
Start in: C:\Users\YOUR_USER\job-search-agent
Time: 8:00 AM daily
```

Results are written to `Output/` and tracked in `data/application_tracker.json`.

---

## Job Sources

Currently supported: **Dice** (default, authless)

To enable additional sources, edit `config.json`:

```json
"job_sources": {
  "active_sources": ["dice", "indeed"],
  "sources": {
    "indeed": { "enabled": true }
  }
}
```

Add the required API key to `.env` (e.g. `INDEED_API_KEY=...`). A new source becomes available by creating `sources/{name}_source.py` — the registry auto-discovers it.

---

## Architecture

```
Orchestrator → Profile Agent → Scout Agent → Gate 1
                                              ↓ (user approves)
              Writer Agent → Reviewer Agent → Fix Loop → Gate 2
                                              ↓ (approved)
                              Tracker Agent → next job
```

Six agents, each with one responsibility, communicating via JSON files in `data/`. See `job_search_agent_spec_v5.md` for the full design specification.

---

## Privacy

This tool processes your resume and generates applications. See **GDPR.md** for the full data handling policy. To delete all personal data:

```bash
python scripts/gdpr_erasure.py
```

---

## CLI Reference

| Flag | Description |
|------|-------------|
| `--dry-run` | Run pipeline without API calls or file writes |
| `--skip-search` | Skip job search, process existing un-tailored jobs |
| `--job-id DICE_ID` | Process a specific job ID only |
| `--no-local-model` | Skip Ollama, use Claude API for all tasks (4GB RAM) |
| `--skip-gate1-if-no-new` | Skip Gate 1 if no new jobs found (automated runs) |
