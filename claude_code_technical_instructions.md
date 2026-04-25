# Claude Code — Technical Build Instructions

> **Target hardware:** Surface Pro 4 (6th-gen Intel Skylake, 4-16GB RAM, no discrete GPU, Intel HD 520/Iris 540)
> **OS:** Windows 10 (cannot upgrade to Windows 11)
> **Design spec:** job_search_agent_spec_v5.md (multi-agent architecture)
> **Priority:** Token efficiency, minimal resource usage, daily unattended runs

---

## 1. Hardware Reality Check

The Surface Pro 4 is a 2015 device. Every architectural decision must respect these hard limits:

| Resource | Spec | Constraint |
|----------|------|------------|
| CPU | Intel Core m3/i5/i7 6th gen (2 cores) | CPU-only inference for local models |
| RAM | 4GB / 8GB / 16GB (depending on model) | Must leave ~3GB free for OS + Python |
| GPU | Intel HD 520 / Iris 540 (integrated) | No VRAM. No CUDA. No ROCm. |
| Storage | 128-512GB SSD | Keep model files small. No 70B downloads. |
| Battery | ~5-6 hours real usage | Daily runs should complete in <10 min |

**Bottom line:** We can run small local models (≤4B parameters) for cheap tasks, but anything requiring quality reasoning MUST go to the Claude API. The split matters enormously for cost and performance.

---

## 2. Local vs API Decision Matrix

This is the most important section. Every AI call in the pipeline falls into one of three tiers:

### Tier 1: NO AI NEEDED — Pure Python logic
These tasks are deterministic. Using any LLM (local or API) is token waste.

| Task | Implementation | Why no AI |
|------|---------------|-----------|
| Dedup check | Python dict lookup on tracker JSON | Exact match on job_id + title + company |
| Exclusion filter | Python if/else on config rules | "Contains 'clearance'" is a string match |
| ATS keyword scan | Python set intersection | Extract keywords → count matches → compute % |
| Format validation | Python checks (section count, page length, spelling) | Deterministic rules |
| Freshness boost | Python date arithmetic | Posted date vs today → +5/+3/+1 points |
| File I/O | Python (python-docx, json) | Read/write files |
| Atomic writes | Python (tempfile + os.rename) | No AI involved |
| Version management | Python (shutil.copy) | File copy operations |
| Follow-up flagging | Python (date diff > 7 days) | Simple date comparison |
| Archival | Python (filter + move in JSON) | 30-day cutoff |
| Conversion metrics | Python (count by status / total) | Arithmetic |
| Rate limiting | Python (asyncio.Semaphore + sleep) | Concurrency control |

**Token savings: ~40% of the pipeline runs with zero AI calls.**

### Tier 2: LOCAL MODEL (Ollama) — Cheap, good-enough tasks
For tasks where we need language understanding but NOT high-quality generation. These run on CPU via Ollama. Expect 5-15 tokens/second — slow but free.

| Task | Local model | Why local is enough |
|------|------------|-------------------|
| Keyword extraction from JD | Phi-4-mini (3.8B) Q4_K_M | Pull structured keywords from job descriptions — simple extraction, not generation |
| Skills cross-reference | Phi-4-mini (3.8B) Q4_K_M | Compare two lists and flag mismatches — classification task |
| Fix instruction parsing | Phi-4-mini (3.8B) Q4_K_M | Read fix_instructions.json and identify which bullet points to edit — locating task |
| Scoring breakdown | Phi-4-mini (3.8B) Q4_K_M | Given profile + JD, assign weighted scores — structured output, not creative |

**Model choice: Phi-4-mini (3.8B) at Q4_K_M quantization.**
- Memory footprint: ~3.5GB (leaves room for OS + Python on 8GB system)
- Speed: ~15-20 tokens/sec on CPU (Surface Pro 4 i5)
- Quality: MMLU 68.5 — sufficient for extraction and classification
- Alternative for 4GB RAM systems: Qwen3 4B 2507 (~2.75GB at Q4)

**Install:**
```bash
# Install Ollama for Windows
winget install Ollama.Ollama

# Pull the model (one-time, ~2.3GB download)
ollama pull phi4-mini

# Test
ollama run phi4-mini "Extract the top 5 technical skills from this job description: ..."
```

**API endpoint:** `http://localhost:11434/api/generate` (OpenAI-compatible)

### Tier 3: CLAUDE API — High-quality generation only
These tasks require nuanced writing, creative judgment, or complex reasoning. This is where tokens cost money — every call must be justified.

| Task | Agent | Why API is needed |
|------|-------|------------------|
| Profile extraction from resume | Profile agent | Needs to understand career narrative, not just keyword extract |
| Resume tailoring | Writer agent (Lane A) | Creative rewriting while preserving voice and injecting keywords |
| Cover letter generation | Writer agent (Lane B) | Personalized writing matching company culture |
| Interview prep generation | Writer agent (Lane C) | Requires understanding of role + candidate fit |
| Story alignment review | Reviewer agent | Subjective quality judgment |
| Cover letter tone review | Reviewer agent | Cultural fit assessment |
| Company research synthesis | Writer agent (Lane B) | Summarize web search results into usable context |

**Model:** `claude-sonnet-4-20250514` (best balance of quality and cost for this use case)

**API call rules (STRICT):**
1. Every API call MUST include the system prompt for that specific agent
2. Never send the full candidate_profile.json if only skills are needed — send the relevant subset
3. Set `max_tokens` per call based on expected output:
   - Profile extraction: max_tokens=2000
   - Resume tailoring: max_tokens=4000
   - Cover letter: max_tokens=2000
   - Interview prep: max_tokens=1500
   - Review: max_tokens=1500
4. Never repeat the job description in follow-up calls — reference it by job_id and pass only the delta
5. Use `temperature=0.3` for resume/cover letter (consistent), `temperature=0.7` for interview prep (creative)

---

## 3. Architecture for Surface Pro 4

### Runtime stack
```
Python 3.11+           ← orchestrator + all agents (single process)
  ├── python-docx      ← read .docx input files
  ├── docx (npm)       ← write .docx output files (called via subprocess)
  ├── httpx            ← async HTTP for Claude API + Ollama
  ├── asyncio          ← parallel lanes within writer agent
  └── json             ← all inter-agent communication

Ollama (background)    ← local model server (Phi-4-mini)
Node.js 18+            ← docx generation only (npm docx package)
```

### Why single-process Python, not microservices
On a Surface Pro 4, spinning up separate processes or Docker containers for each agent would waste RAM. Instead:
- Each agent is a **Python class** with its own system prompt
- The orchestrator calls agents as **async functions**
- Agents communicate via **JSON files on disk** (not in-memory message passing)
- This keeps RAM usage to: Python process (~200MB) + Ollama model (~3.5GB) + OS (~3GB) = ~6.7GB total

### File-based inter-agent protocol
```python
# Agent writes output
agent_output = profile_agent.run(input_files)
write_json("candidate_profile.json", agent_output)

# Next agent reads input
profile = read_json("candidate_profile.json")
scout_output = scout_agent.run(profile, config)
write_json("job_matches.json", scout_output)
```

No message queues, no Redis, no SQLite. JSON files are the message bus. This is deliberate — the Surface Pro 4 doesn't have RAM to spare on infrastructure.

---

## 4. Token Budget — Optimized for Surface Pro 4

### Per-job cost breakdown (hybrid local+API)

| Step | Engine | Tokens | Cost |
|------|--------|--------|------|
| Keyword extraction from JD | LOCAL (free) | 0 | $0 |
| Scoring | LOCAL (free) | 0 | $0 |
| ATS scan | PYTHON (free) | 0 | $0 |
| Dedup + filter | PYTHON (free) | 0 | $0 |
| Resume tailoring | API | ~4,000 | ~$0.012 |
| Cover letter | API | ~3,000 | ~$0.009 |
| Interview prep | API | ~1,500 | ~$0.005 |
| Quality review | API | ~2,000 | ~$0.006 |
| Auto-fix (if needed) | API | ~1,000 | ~$0.003 |
| **Total per job** | | **~11,500** | **~$0.035** |

### Per-run cost (daily)

| Scenario | Jobs | API Tokens | Local Tokens | Cost |
|----------|------|-----------|-------------|------|
| Light day (1 approved) | 1 | ~13,500 | ~2,000 | ~$0.04 |
| Normal day (3 approved) | 3 | ~36,500 | ~6,000 | ~$0.11 |
| Heavy day (5 approved) | 5 | ~59,500 | ~10,000 | ~$0.18 |
| No matches | 0 | ~2,500 | ~2,000 | ~$0.008 |

### vs. pure API approach

| Approach | Monthly cost (30 days, 3 jobs/day) |
|----------|----------------------------------|
| All API (v4 design) | ~$9.90 |
| Hybrid local+API (v5) | ~$3.30 |
| **Savings** | **~67%** |

---

## 5. Project Structure for Claude Code

```
job-search-agent/
├── README.md
├── requirements.txt              # Python dependencies
├── package.json                  # Node.js (docx generation only)
├── config.json                   # User configuration
│
├── agents/                       # One file per agent
│   ├── __init__.py
│   ├── orchestrator.py           # Main loop, gates, rate limiter, retry logic
│   ├── profile_agent.py          # Reads resume/skills → candidate_profile.json
│   ├── scout_agent.py            # Searches Dice, scores → job_matches.json
│   ├── writer_agent.py           # Generates resume/cover/prep (parallel lanes)
│   ├── reviewer_agent.py         # ATS check, quality review → fix_instructions.json
│   └── tracker_agent.py          # Status tracking, metrics, archival
│
├── prompts/                      # System prompts (separate files, easy to tune)
│   ├── profile_agent.txt
│   ├── scout_agent.txt
│   ├── writer_resume.txt
│   ├── writer_cover_letter.txt
│   ├── writer_interview_prep.txt
│   └── reviewer_agent.txt
│
├── utils/                        # Shared utilities
│   ├── __init__.py
│   ├── docx_reader.py            # Read .docx files (python-docx)
│   ├── docx_writer.js            # Write .docx files (Node.js docx package)
│   ├── api_client.py             # Claude API wrapper with rate limiting
│   ├── local_llm.py              # Ollama wrapper (Phi-4-mini)
│   ├── file_io.py                # Atomic JSON read/write with backup
│   ├── ats_scanner.py            # Keyword extraction + coverage % (pure Python)
│   └── format_validator.py       # Section checks, length, spelling (pure Python)
│
├── data/                         # Inter-agent communication files
│   ├── candidate_profile.json    # Profile agent output
│   ├── job_matches.json          # Scout agent output
│   ├── fix_instructions.json     # Reviewer → Writer handoff
│   ├── scoring_feedback.json     # Tracker → Scout feedback
│   ├── application_tracker.json  # Master tracker
│   ├── application_tracker.backup.json
│   └── run_history.json
│
├── Skills/                       # User's skill files (isolated)
│   ├── technical_skills.docx
│   ├── soft_skills.docx
│   └── certifications.docx
│
├── Input_Files/                  # User's input files
│   ├── master_resume.docx
│   └── job_requirements.docx
│
├── Output/                       # Generated deliverables
│   ├── Best_Match/
│   └── Possible_Match/
│
├── templates/                    # .docx templates for consistent formatting
│   ├── resume_template.docx
│   └── cover_letter_template.docx
│
├── tests/                        # Unit + integration tests
│   ├── test_profile_agent.py
│   ├── test_scout_agent.py
│   ├── test_writer_agent.py
│   ├── test_reviewer_agent.py
│   ├── test_tracker_agent.py
│   ├── test_ats_scanner.py
│   └── test_integration.py
│
├── dashboard.jsx                 # React dashboard
├── run.py                        # Daily run entry point
└── master_summary.md             # Generated each run
```

---

## 6. Key Implementation Details

### 6.1 Ollama integration (local_llm.py)

```python
import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"
LOCAL_MODEL = "phi4-mini"

async def local_generate(prompt: str, max_tokens: int = 500) -> str:
    """Call local Phi-4-mini via Ollama. CPU-only, ~15 tok/sec."""
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(OLLAMA_URL, json={
            "model": LOCAL_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.1,  # Low temp for extraction tasks
                "num_thread": 4,      # Use all cores on Surface Pro 4
            }
        })
        return response.json()["response"]
```

### 6.2 Claude API integration (api_client.py)

```python
import httpx
import asyncio

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

class ClaudeClient:
    def __init__(self, api_key: str, max_concurrent: int = 3, delay: float = 2.0):
        self.api_key = api_key
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.delay = delay
        self._last_call = 0

    async def generate(self, system_prompt: str, user_message: str,
                       max_tokens: int = 1000, temperature: float = 0.3) -> str:
        async with self.semaphore:
            # Enforce delay between calls
            now = asyncio.get_event_loop().time()
            wait = self.delay - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)

            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(API_URL, headers={
                    "x-api-key": self.api_key,
                    "content-type": "application/json",
                    "anthropic-version": "2023-06-01"
                }, json={
                    "model": MODEL,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}]
                })
                self._last_call = asyncio.get_event_loop().time()
                data = response.json()
                return data["content"][0]["text"]
```

### 6.3 Atomic file writes (file_io.py)

```python
import json, os, shutil, tempfile

def atomic_write_json(filepath: str, data: dict):
    """Write JSON atomically: temp file → validate → rename."""
    # Backup current file
    if os.path.exists(filepath):
        shutil.copy2(filepath, filepath.replace(".json", ".backup.json"))

    # Write to temp file in same directory (required for os.rename)
    dir_path = os.path.dirname(filepath) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".json")
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        # Validate by reading back
        with open(tmp_path) as f:
            json.load(f)  # Will throw if invalid
        # Atomic rename
        os.replace(tmp_path, filepath)
    except Exception:
        os.unlink(tmp_path)
        raise
```

### 6.4 ATS scanner (ats_scanner.py) — Pure Python, zero tokens

```python
import re
from collections import Counter

def extract_keywords(job_description: str) -> set:
    """Extract technical keywords from JD. No AI needed."""
    # Common technical terms pattern
    tech_patterns = [
        r'\b(?:Python|Java|JavaScript|TypeScript|Go|Rust|C\+\+|Ruby|PHP|Swift|Kotlin)\b',
        r'\b(?:AWS|Azure|GCP|Docker|Kubernetes|Terraform|Jenkins|CI/CD)\b',
        r'\b(?:React|Angular|Vue|Node\.js|Django|Flask|Spring|FastAPI)\b',
        r'\b(?:PostgreSQL|MySQL|MongoDB|Redis|Elasticsearch|Kafka)\b',
        r'\b(?:REST|GraphQL|gRPC|microservices|API)\b',
        r'\b(?:Agile|Scrum|DevOps|SRE|TDD|BDD)\b',
    ]
    keywords = set()
    for pattern in tech_patterns:
        keywords.update(re.findall(pattern, job_description, re.IGNORECASE))

    # Also extract from "Requirements" / "Qualifications" sections
    req_section = re.search(
        r'(?:requirements|qualifications|must.have|required)[\s:]*(.+?)(?:preferred|nice.to.have|benefits|\Z)',
        job_description, re.IGNORECASE | re.DOTALL
    )
    if req_section:
        words = re.findall(r'\b[A-Z][a-zA-Z+#.]+\b', req_section.group(1))
        keywords.update(words)

    return {k.lower() for k in keywords}

def compute_ats_coverage(resume_text: str, job_keywords: set) -> dict:
    """Compare resume against JD keywords. Returns coverage % and missing list."""
    resume_lower = resume_text.lower()
    matched = {kw for kw in job_keywords if kw in resume_lower}
    missing = job_keywords - matched
    coverage = (len(matched) / len(job_keywords) * 100) if job_keywords else 100

    return {
        "coverage_percent": round(coverage, 1),
        "matched_keywords": sorted(matched),
        "missing_keywords": sorted(missing),
        "total_required": len(job_keywords),
        "total_matched": len(matched)
    }
```

### 6.5 Parallel lanes in writer agent

```python
async def generate_for_job(self, job: dict, profile: dict, claude: ClaudeClient):
    """Run Lanes A, B, C in parallel for one job."""
    lane_a = self.tailor_resume(job, profile, claude)
    lane_b = self.write_cover_letter(job, profile, claude)
    lane_c = self.generate_prep(job, profile, claude)

    results = await asyncio.gather(lane_a, lane_b, lane_c, return_exceptions=True)

    # Handle partial failures
    resume, cover_letter, prep = results
    if isinstance(resume, Exception):
        raise resume  # Resume is critical, can't continue
    if isinstance(cover_letter, Exception):
        cover_letter = None  # Degraded mode, note in review
    if isinstance(prep, Exception):
        prep = None  # Non-critical, skip

    return {"resume": resume, "cover_letter": cover_letter, "prep": prep}
```

---

## 7. Daily Run Entry Point (run.py)

```python
#!/usr/bin/env python3
"""
Job Search Agent — Daily Run
Target: Surface Pro 4 (8GB RAM, no GPU)
Usage: python run.py [--dry-run] [--skip-search] [--job-id DICE_ID]
"""

import asyncio
import argparse
from agents.orchestrator import Orchestrator

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Run pipeline without API calls or file writes")
    parser.add_argument("--skip-search", action="store_true",
                        help="Skip Dice search, process existing un-tailored jobs")
    parser.add_argument("--job-id", type=str,
                        help="Process a specific job ID only")
    args = parser.parse_args()

    orchestrator = Orchestrator(
        config_path="config.json",
        dry_run=args.dry_run,
        skip_search=args.skip_search,
        target_job_id=args.job_id
    )
    await orchestrator.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 8. Performance Targets on Surface Pro 4

| Phase | Target Duration | Bottleneck |
|-------|----------------|------------|
| Profile agent | <30 seconds | Claude API (1 call) |
| Scout agent | <60 seconds | Dice MCP + local model scoring |
| Gate 1 (user review) | User-dependent | Waiting for input |
| Writer (per job) | <90 seconds | Claude API (3 parallel calls) |
| Reviewer (per job) | <45 seconds | Claude API (1 call) + Python checks |
| Fix loop (if needed) | <60 seconds per attempt | Claude API (1 call) |
| Tracker | <5 seconds | Pure Python file I/O |
| **Total (3 jobs, no fixes)** | **<8 minutes** | |

### Memory usage targets

| Component | RAM |
|-----------|-----|
| Windows 10 OS | ~2.5GB |
| Python process (orchestrator + all agents) | ~200MB |
| Ollama + Phi-4-mini model | ~3.5GB |
| Node.js (docx generation, spawned per file) | ~100MB (transient) |
| **Total** | **~6.3GB** |
| **Available for 8GB system** | **~1.7GB headroom** |
| **Available for 16GB system** | **~9.7GB headroom** |

### For 4GB RAM systems
If you have the 4GB model:
- Do NOT run Ollama locally — use Claude API for all AI tasks
- Use the `--no-local-model` flag
- Token costs increase ~30% but the pipeline will complete without memory pressure

---

## 9. Ollama Startup and Management

```python
# utils/ollama_manager.py

import subprocess
import httpx
import time

def ensure_ollama_running():
    """Start Ollama if not already running. Pull model if needed."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if "phi4-mini:latest" not in models:
            print("Pulling Phi-4-mini model (one-time, ~2.3GB)...")
            subprocess.run(["ollama", "pull", "phi4-mini"], check=True)
    except httpx.ConnectError:
        print("Starting Ollama server...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        time.sleep(5)
        ensure_ollama_running()  # Retry after startup
```

---

## 10. Dependencies

### requirements.txt
```
httpx>=0.27.0
python-docx>=1.1.0
asyncio
```

### package.json (minimal — docx generation only)
```json
{
  "name": "job-search-docx",
  "private": true,
  "dependencies": {
    "docx": "^9.0.0"
  }
}
```

### System requirements
```
- Python 3.11+
- Node.js 18+ (for docx generation only)
- Ollama (latest) — optional for 4GB RAM systems
- Windows 10 (Surface Pro 4 cannot run Windows 11)
```

---

## 11. Environment Variables

```bash
# .env file (never commit)
ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_HOST=http://localhost:11434   # Default, change if remote
USE_LOCAL_MODEL=true                  # Set false for 4GB RAM systems
LOCAL_MODEL_NAME=phi4-mini           # Override if testing other models
```

---

## 12. Testing Strategy

### Unit tests (run fast, no API calls)
```bash
# Mock Claude API + Ollama responses
python -m pytest tests/ -k "not integration" --timeout=30
```

### Integration tests (needs API key + Ollama running)
```bash
# Full pipeline with sample data
python -m pytest tests/test_integration.py --timeout=300
```

### Sample test data
Create `tests/fixtures/` with:
- `sample_resume.docx` — fake resume with known skills
- `sample_skills.docx` — matching skills file
- `sample_job_description.json` — fake JD with known keywords
- `expected_profile.json` — expected profile agent output
- `expected_ats_result.json` — expected ATS coverage result

---

## 13. Build Order for Claude Code

Follow this exact sequence. Each step should be a working commit.

```
COMMIT 1: Project scaffolding
  - Create folder structure
  - requirements.txt + package.json
  - config.json with all settings
  - Empty agent class skeletons
  - README.md

COMMIT 2: Utility layer
  - file_io.py (atomic JSON read/write with backup)
  - docx_reader.py (read .docx files)
  - ats_scanner.py (pure Python keyword extraction + coverage)
  - format_validator.py (section checks, length validation)
  - Unit tests for all utilities

COMMIT 3: Local LLM integration
  - local_llm.py (Ollama wrapper)
  - ollama_manager.py (auto-start, model pull)
  - api_client.py (Claude API wrapper with rate limiting)
  - Test both with simple prompts

COMMIT 4: Profile agent
  - profile_agent.py (reads inputs → candidate_profile.json)
  - prompts/profile_agent.txt
  - Unit test with sample resume

COMMIT 5: Scout agent
  - scout_agent.py (Dice MCP search → score → job_matches.json)
  - Scoring engine with freshness boost
  - Dedup logic
  - Exclusion filter
  - Unit test with sample job data

COMMIT 6: Orchestrator + Gate 1
  - orchestrator.py (agent call sequence)
  - Gate 1 (show results, get user approval via CLI)
  - Rate limiter (semaphore + delay)
  - Error fallback handling
  - Integration test: profile → scout → gate 1

COMMIT 7: Writer agent
  - writer_agent.py (3 parallel lanes)
  - docx_writer.js (Node.js docx generation)
  - prompts/writer_resume.txt
  - prompts/writer_cover_letter.txt
  - prompts/writer_interview_prep.txt
  - Version backup logic
  - Unit test with sample job

COMMIT 8: Reviewer agent
  - reviewer_agent.py (ATS check + quality review)
  - fix_instructions.json generation
  - fix_history.md logging
  - prompts/reviewer_agent.txt
  - Unit test

COMMIT 9: Fix loop + Gate 2
  - Fix loop in orchestrator (writer ← reviewer cycle)
  - Retry counter (max 2)
  - User approval gate (approve/edit/skip)
  - Gate 2 (continue to next job?)
  - Integration test: full single-job cycle

COMMIT 10: Tracker agent
  - tracker_agent.py (all CRUD + metrics + archival + follow-ups)
  - scoring_feedback.json generation
  - master_summary.md generation
  - Unit test

COMMIT 11: Full integration
  - run.py (daily entry point with CLI flags)
  - End-to-end integration test
  - Error scenario tests

COMMIT 12: Dashboard
  - dashboard.jsx (React, all 6 panels)
  - Inline resume preview
  - Status update actions
  - Bulk operations

COMMIT 13: Polish
  - .env.example
  - Setup instructions in README
  - Windows Task Scheduler config for daily runs
  - Performance profiling on Surface Pro 4
```

---

## 14. Windows Task Scheduler (Daily Automation)

To run the agent daily at 8:00 AM without opening it manually:

```xml
<!-- Save as job_search_daily.xml, import into Task Scheduler -->
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-04-25T08:00:00</StartBoundary>
      <Repetition>
        <Interval>P1D</Interval>
      </Repetition>
    </CalendarTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>python</Command>
      <Arguments>run.py --skip-gate1-if-no-new</Arguments>
      <WorkingDirectory>C:\Users\{user}\job-search-agent</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <StartWhenAvailable>true</StartWhenAvailable>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
  </Settings>
</Task>
```

---

## 15. Critical Rules for Claude Code

1. **NEVER use Claude API for tasks that can be done with Python string matching or set operations.** ATS scanning, dedup, filtering, date arithmetic, file I/O — these are ALL pure Python.

2. **NEVER send the full candidate_profile.json to every API call.** Send only the relevant subset. Resume tailoring needs experience + skills. Cover letter needs skills + target titles. Interview prep needs highlights + matched keywords.

3. **ALWAYS use Ollama for extraction/classification tasks.** Keyword extraction from job descriptions, skills cross-referencing, scoring breakdowns — these don't need Claude-quality output.

4. **ALWAYS set max_tokens explicitly on every API call.** Never leave it at the default. Profile=2000, Resume=4000, Cover letter=2000, Prep=1500, Review=1500.

5. **ALWAYS read the system prompt from a file** (prompts/ folder), not inline. This makes prompt tuning possible without code changes.

6. **NEVER run Ollama and the writer agent simultaneously** on an 8GB system. Unload the Ollama model before the writer agent's parallel API calls:
   ```python
   # Before writer agent runs
   await local_llm.unload()  # Frees ~3.5GB RAM

   # After writer agent finishes
   await local_llm.reload()  # Reload for reviewer's extraction tasks
   ```

7. **ALWAYS validate .docx output before presenting to user.** Call the validator after every docx generation.

8. **ALWAYS use atomic writes for tracker JSON.** Never write directly. Temp file → validate → rename.

9. **Test on 8GB RAM first.** If it works on 8GB, it works everywhere. Don't develop on 16GB and discover memory issues in production.

10. **Log every API call with token count.** Build a simple logger that tracks: timestamp, agent, model (local/API), input_tokens, output_tokens, duration_ms. This is how you spot token waste.

---

## 16. Remote Development Setup — Develop in Cloud, Deploy to Surface Pro 4

### Strategy: Two-phase workflow

**Phase A — Develop remotely** (Claude Code does all the work in the cloud)
**Phase B — Deploy locally** (Surface Pro 4 runs the finished agent)

This keeps all development load off the Surface Pro 4. You only touch the device when deploying.

---

### Phase A: Remote Development with Claude Code

You have three options. Option 1 (Remote Session) is recommended for this project.

#### Option 1: Claude Code Desktop — Remote Session (RECOMMENDED)

Claude Code Desktop has a built-in "Remote" mode. Sessions run on Anthropic's cloud infrastructure and persist even if you close the app. Zero setup on the Surface Pro 4 during development.

**Setup (5 minutes):**

```
Step 1: Install Claude Code Desktop on any machine
        → Download from code.claude.com
        → Works on Windows, Mac, or Linux

Step 2: Open Claude Code Desktop

Step 3: Click "New Session"
        → Select "Remote" (not "Local")
        → Choose your model (Opus or Sonnet)

Step 4: You're in. Start building.
        → The session runs on Anthropic's cloud
        → Files are stored in the cloud environment
        → Push to GitHub when ready to deploy
```

**Working with your project:**

```bash
# Inside the remote session, initialize the project
git init job-search-agent
cd job-search-agent

# Add the spec files (paste content or upload)
# Claude Code can read them directly

# Tell Claude Code to start building:
# "Read claude_code_technical_instructions.md and
#  job_search_agent_spec_v5.md. Follow the build order
#  in Section 13, committing after each step."

# When ready, push to GitHub
git remote add origin https://github.com/YOUR_USER/job-search-agent.git
git push -u origin main
```

**Monitor from anywhere:**
- Browser: claude.ai/code
- Phone: Claude iOS/Android app
- Sessions survive disconnection

**Limitation:** Can't test Ollama locally during development. Solution: mock the local LLM responses during dev, test Ollama integration after deploying to Surface.

#### Option 2: Claude Code Desktop — SSH to a VPS

If you want full environment control (test Ollama, run full pipeline during dev):

**Setup (30 minutes):**

```bash
# 1. Rent a VPS (DigitalOcean $6/mo, Hetzner $4/mo)
#    Minimum: 4GB RAM, 2 vCPU, 40GB SSD (Ubuntu 24.04)
#    Better:  8GB RAM for Ollama testing

# 2. On the VPS — install prerequisites
sudo apt update && sudo apt install -y python3.11 python3-pip nodejs npm tmux

# 3. Install Claude Code on the VPS
npm install -g @anthropic-ai/claude-code

# 4. Install Ollama (optional, for local model testing)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull phi4-mini

# 5. Set up SSH key auth (on your local machine)
ssh-keygen -t ed25519 -C "claude-code-dev"
ssh-copy-id deploy@YOUR_VPS_IP

# 6. In Claude Code Desktop:
#    Click "New Session" → Select "SSH"
#    Enter: deploy@YOUR_VPS_IP
#    Working directory: /home/deploy/job-search-agent
```

**tmux for persistent sessions:**

```bash
# On the VPS — keep Claude Code running even if SSH drops
tmux new -s claude-dev
claude  # Start Claude Code inside tmux

# Detach: Ctrl+B, then D
# Reattach later: tmux attach -t claude-dev
```

#### Option 3: SSH directly into Surface Pro 4

Only if you want to develop ON the target hardware (not recommended for this project):

```powershell
# On Surface Pro 4 (PowerShell as Admin)

# 1. Enable OpenSSH Server
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'

# 2. Allow SSH through firewall
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' `
  -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22

# 3. Install Claude Code
npm install -g @anthropic-ai/claude-code

# 4. From Claude Code Desktop on another machine:
#    New Session → SSH → your_user@SURFACE_IP
```

**Warning:** This puts full development load on the Surface Pro 4. RAM will be tight.

---

### Phase B: Deploy to Surface Pro 4

Once development is complete in the cloud, deploy to the Surface:

```powershell
# On Surface Pro 4 (PowerShell)

# 1. Install prerequisites
# Python 3.11+
winget install Python.Python.3.11

# Node.js 18+
winget install OpenJS.NodeJS.LTS

# Git
winget install Git.Git

# Ollama
winget install Ollama.Ollama

# 2. Clone your project
cd C:\Users\YOUR_USER
git clone https://github.com/YOUR_USER/job-search-agent.git
cd job-search-agent

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Node dependencies (for docx generation)
npm install

# 5. Pull the local model
ollama pull phi4-mini

# 6. Set up environment variables
# Create .env file (never commit this)
echo ANTHROPIC_API_KEY=sk-ant-... > .env

# 7. Copy your input files
# master_resume.docx → Input_Files/
# technical_skills.docx → Skills/
# job_requirements.docx → Input_Files/

# 8. Test run
python run.py --dry-run

# 9. First real run
python run.py
```

---

### Phase C: Set Up Daily Automation on Surface Pro 4

```powershell
# Create a batch file for the daily run
@echo off
:: job_search_daily.bat
cd C:\Users\YOUR_USER\job-search-agent
call .env
python run.py >> logs\daily_run_%date:~-4%%date:~4,2%%date:~7,2%.log 2>&1
```

**Windows Task Scheduler setup:**

```
1. Open Task Scheduler (taskschd.msc)
2. Create Basic Task → "Job Search Agent Daily Run"
3. Trigger: Daily at 8:00 AM
4. Action: Start a Program
   Program: python
   Arguments: run.py
   Start in: C:\Users\YOUR_USER\job-search-agent
5. Settings:
   ✓ Run whether user is logged on or not
   ✓ Start the task only if the computer is on AC power (uncheck if needed)
   ✓ If the task is not scheduled to run again, delete it after: Never
   ✓ Stop the task if it runs longer than: 30 minutes
```

---

### Phase D: Remote Monitoring After Deployment

Once the agent is running daily on the Surface Pro 4, you'll want to monitor it remotely.

**Option D1: Tailscale (recommended — free for personal use)**

```powershell
# On Surface Pro 4
winget install Tailscale.Tailscale
# Sign in → Surface gets a stable IP like 100.x.y.z

# On your phone/laptop
# Install Tailscale → same account
# SSH in from anywhere:
ssh YOUR_USER@100.x.y.z
```

**Option D2: Check results via GitHub**

```python
# Add to end of run.py — auto-push results after each run
import subprocess

def push_results():
    subprocess.run(["git", "add", "data/", "Output/", "master_summary.md"])
    subprocess.run(["git", "commit", "-m", f"Daily run {datetime.now().isoformat()}"])
    subprocess.run(["git", "push"])
```

Then check GitHub from any device to see daily results.

**Option D3: Claude Code Remote Control**

```bash
# On Surface Pro 4 — start Claude Code with remote control
claude
# Inside Claude Code, type:
/remote-control

# This generates a link. Open it on your phone/browser.
# You can now interact with Claude Code on the Surface from anywhere.
# Note: Surface must be on and Claude Code must be running.
```

---

### Summary: Complete Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    DEVELOPMENT (Cloud)                       │
│                                                              │
│  Claude Code Desktop → Remote Session → Build all agents     │
│  Push to GitHub when each commit is ready                    │
│                                                              │
│  Duration: 1-2 days of development                           │
│  Surface Pro 4 load: ZERO                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ git clone
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                DEPLOYMENT (Surface Pro 4)                     │
│                                                              │
│  git clone → pip install → npm install → ollama pull         │
│  Copy input .docx files → Test with --dry-run                │
│                                                              │
│  Duration: ~15 minutes                                       │
└──────────────────────────┬──────────────────────────────────┘
                           │ Task Scheduler
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               DAILY OPERATION (Surface Pro 4)                │
│                                                              │
│  8:00 AM → Task Scheduler triggers run.py                    │
│  Agent runs (~8 min) → Results in Output/                    │
│  Dashboard available at localhost                             │
│                                                              │
│  Monitor via: Tailscale SSH / GitHub push / Remote Control   │
└─────────────────────────────────────────────────────────────┘
```
