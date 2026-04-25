# Job Search Agent — Complete Design Specification

> **Version:** v5 (Multi-Agent Final)
> **Date:** April 24, 2026
> **Handoff target:** Claude Code
> **Status:** Design complete, ready for implementation

---

## 1. Project Overview

A multi-agent AI system that runs daily to find, score, and tailor job applications. Six specialized agents coordinate through a shared data layer, each with a focused system prompt and clear boundaries. The orchestrator manages gates, rate limits, retry logic, and error fallbacks.

### Core Principles
- **Multi-agent separation** — each agent has one job, one prompt, one responsibility
- **Writer never reviews its own work** — separate reviewer agent ensures honest quality checks
- **Don't spend tokens until the output is wanted** — gate every expensive operation
- **Parallel over sequential** — resume, cover letter, and prep generated simultaneously
- **Rate limit aware** — orchestrator controls concurrency and delays
- **Fix before shipping** — reviewer detects, writer fixes, orchestrator counts retries
- **Skills are modular** — isolated folder for future enhancements
- **Agents share data, not context** — JSON files are the communication protocol

---

## 2. Agent Definitions

### Agent 0: Orchestrator

```yaml
name: orchestrator
role: Workflow coordinator
system_prompt: |
  You are a workflow coordinator for a job search pipeline. You call specialized
  agents in sequence, manage decision gates, enforce rate limits, count retries,
  and handle errors. You NEVER generate content, score jobs, or write documents.
  You only route data between agents and present results to the user for approval.

owns:
  - config.json (reads)
  - Gate 1 (show scout results, ask user to approve)
  - Gate 2 (continue to next job?)
  - Rate limiter (max 3 concurrent API calls, 2s delay between jobs)
  - Retry counter (max 2 auto-fix attempts per job)
  - Error fallback matrix (see Section 10)

calls: [profile_agent, scout_agent, writer_agent, reviewer_agent, tracker_agent]

does_not_do:
  - Content generation of any kind
  - Job scoring or ranking
  - File creation (except logging)
  - Decisions about content quality (that's the reviewer's job)
```

### Agent 1: Profile Agent

```yaml
name: profile_agent
role: Resume and skills parser
system_prompt: |
  You are a resume parsing specialist. Extract structured data from .docx
  documents. Output a JSON profile containing: skills (categorized as technical,
  soft, certifications), years of experience per skill, job titles held,
  industries worked in, education, and ATS-relevant keywords. Be exhaustive —
  every skill mentioned should be captured. Output JSON only, no prose.

reads:
  - Input_Files/master_resume.docx
  - Skills/technical_skills.docx
  - Skills/soft_skills.docx (if exists)
  - Skills/certifications.docx (if exists)
  - Input_Files/job_requirements.docx

writes:
  - candidate_profile.json

does_not_do:
  - Job searching
  - Resume writing or tailoring
  - Scoring or ranking
  - Any file outside candidate_profile.json

when: Once per daily run, or when input files change
token_cost: ~2,000
```

### Agent 2: Scout Agent

```yaml
name: scout_agent
role: Job market analyst
system_prompt: |
  You are a job market analyst. Search for jobs matching a candidate profile,
  deduplicate against previously seen jobs, apply exclusion filters, score each
  job using weighted criteria, and rank results by match quality with freshness
  as a tiebreaker (jobs posted more recently rank higher within the same score
  band). Output a structured JSON list grouped by match tier. You do NOT write
  resumes or cover letters.

reads:
  - candidate_profile.json
  - config.json (scoring weights, exclusions, thresholds)
  - application_tracker.json (for dedup check)

writes:
  - job_matches.json

calls:
  - Dice MCP (search_jobs) — with retry logic: exponential backoff 1s/2s/4s, max 3 retries
  - Web search (for company context: tech stack, size, culture, recent news)

scoring_logic:
  weights:
    core_skills_match: 0.35
    title_seniority_alignment: 0.20
    industry_domain_fit: 0.15
    years_experience_fit: 0.15
    nice_to_have_skills: 0.10
    company_culture_signals: 0.05
  freshness_boost: |
    Within the same score band, jobs posted in the last 24h get +5 points,
    last 48h get +3, last 72h get +1. This is a tiebreaker, not a primary factor.
  exclusions:
    - Requires security clearance → auto-reject
    - Entry-level or junior roles → auto-reject
    - Jobs already in application_tracker.json → skip (dedup)
  grouping:
    best_match: score >= 75
    possible_match: score >= 50 and score < 75
    not_matching: score < 50

does_not_do:
  - Resume writing or tailoring
  - Quality review
  - Tracker updates
  - Any file writes outside job_matches.json

when: Once per daily run, after profile agent completes
token_cost: ~500
```

### Agent 3: Writer Agent

```yaml
name: writer_agent
role: Resume writer and career content specialist
system_prompt: |
  You are an expert resume writer and career coach specializing in ATS
  optimization. Given a candidate profile and a specific job description, you:
  1. Tailor the resume by reordering experience, adjusting the summary, and
     injecting job-specific keywords into existing bullet points
  2. Write a personalized cover letter matching the company's culture and tone
  3. Generate interview prep (common questions + talking points)
  4. Compile job details and match analysis

  When you receive fix_instructions.json from the reviewer, apply ONLY the
  specified fixes — do not regenerate from scratch. Save the previous version
  as a backup before applying fixes.

  You NEVER review or grade your own output. That is the reviewer's job.

reads:
  - candidate_profile.json
  - Input_Files/master_resume.docx
  - Skills/*.docx (all files)
  - One job entry from job_matches.json (passed by orchestrator)
  - fix_instructions.json (when in fix loop, passed by orchestrator)

writes (per job folder):
  - tailored_resume.docx (Lane A)
  - cover_letter.docx (Lane B)
  - job_details.md (Lane C)
  - match_report.md (Lane C)
  - interview_prep.md (Lane C)
  - v{N}_resume.docx (backup before fixes)
  - v{N}_cover_letter.docx (backup before fixes)

internal_parallelism: |
  Lanes A, B, C run in parallel within a single job.
  Lane A: Resume tailoring
  Lane B: Cover letter + company research (uses web search)
  Lane C: Job details + match report + interview prep

validation: |
  After generating .docx files, validate format using docx validation.
  If malformed, retry generation once before reporting failure.

does_not_do:
  - Job searching or scoring
  - Quality review or ATS scoring (reviewer does that)
  - Tracker updates
  - Deciding whether output is good enough (reviewer decides)

when: Per approved job, after Gate 1
token_cost: ~8,000 per job (initial), ~1,000 per fix attempt
```

### Agent 4: Reviewer Agent

```yaml
name: reviewer_agent
role: ATS expert and quality auditor
system_prompt: |
  You are an ATS expert and former hiring manager. Your job is to ruthlessly
  critique resumes and cover letters. You NEVER wrote this content — you are
  an independent auditor. Be specific in your criticism.

  Step 1 — Mechanical checks (automated, no AI needed):
    - ATS keyword scan: extract required keywords from job description, check
      coverage in resume. Target: ≥85%. Report exact missing keywords.
    - Format validation: correct section headers, appropriate length (1-2 pages),
      no spelling errors, consistent formatting
    - Skills cross-reference: every skill claimed in resume must exist in Skills/
      files. Flag any unverified claims.

  Step 2 — Quality review (AI judgment):
    - Story alignment: does the resume tell a narrative that fits THIS specific role?
    - Cover letter tone: does it match the company culture (startup vs enterprise)?
    - Claim verification: any achievements that seem inflated vs master resume?
    - Quantification check: are impact statements backed by numbers?

  Output: review_notes.md with quality score (1-10) and specific suggestions.
  If mechanical checks fail: output fix_instructions.json with targeted fixes.

reads:
  - Writer's output files (resume, cover letter)
  - Original job description (from job_matches.json)
  - candidate_profile.json (to verify claims)
  - Skills/*.docx (to cross-reference claimed skills)

writes:
  - review_notes.md (quality assessment + score)
  - fix_instructions.json (if fixes needed — see schema below)
  - fix_history.md (appended with each review pass)

does_not_do:
  - Write or rewrite any resume/cover letter content
  - Job searching or scoring
  - Tracker updates
  - Applying fixes (writer does that based on fix_instructions.json)

when: After writer completes, called by orchestrator
token_cost: ~2,000 per review pass
```

### Agent 5: Tracker Agent

```yaml
name: tracker_agent
role: Data clerk and metrics engine
system_prompt: |
  You are a meticulous data clerk. Record status changes, compute pipeline
  metrics, flag follow-ups, and maintain clean records. You NEVER generate
  creative content, score jobs, or make subjective judgments. You work with
  structured data only.

reads:
  - All agent outputs (to record what happened)
  - User status updates from dashboard
  - config.json (for follow-up days, archive policy)

writes:
  - application_tracker.json (atomic: write temp file, then rename)
  - run_history.json (append per run)
  - master_summary.md (regenerate each run)

responsibilities:
  dedup_check: |
    Before scout runs, provide current tracker state for dedup.
    Dedup key: job_id + title + company.

  status_lifecycle: |
    Discovered → Tailored → Applied → Interview → Rejected
    Only forward transitions allowed, except:
    - Any status can go to Rejected
    - Applied can go to Interview

  follow_up_reminders: |
    Flag any job in "Applied" status for 7+ consecutive days.
    Include in master_summary.md and expose via tracker JSON for dashboard.

  conversion_metrics: |
    Compute and store in run_history.json:
    - Discovered → Tailored rate
    - Tailored → Applied rate
    - Applied → Interview rate
    - Overall conversion: Discovered → Interview

  archival: |
    On each run, archive entries with status "Rejected" older than 30 days.
    Move to archived_jobs array in tracker. Keep counts for metrics.

  feedback_signal: |
    When user changes a "Possible Match" to "Applied" (manual promotion),
    or rejects a "Best Match" (scoring was wrong), log this in
    scoring_feedback.json for the scout agent to read on next run.

  backup: |
    Before each write to application_tracker.json, copy current file
    to application_tracker.backup.json.

atomic_write_protocol: |
  1. Write to application_tracker.tmp.json
  2. Validate JSON structure
  3. os.rename() to application_tracker.json
  If step 2 fails, abort and keep original file intact.

does_not_do:
  - Content generation
  - Job searching
  - Resume writing or review
  - Subjective quality judgments

when: After each job is approved/skipped, on user status updates, end of each run
token_cost: ~200 (mostly file I/O, minimal AI)
```

---

## 3. Inter-Agent Data Schemas

### candidate_profile.json (Profile Agent → Scout, Writer)

```json
{
  "name": "Jane Doe",
  "target_titles": ["Senior Software Engineer", "Lead Engineer", "Staff Engineer"],
  "years_experience": 12,
  "skills": {
    "technical": [
      {"name": "Python", "years": 8, "proficiency": "expert"},
      {"name": "AWS", "years": 5, "proficiency": "advanced"},
      {"name": "Kubernetes", "years": 3, "proficiency": "intermediate"}
    ],
    "soft": [
      {"name": "Team Leadership", "years": 6},
      {"name": "Cross-functional Collaboration", "years": 8}
    ],
    "certifications": [
      {"name": "AWS Solutions Architect", "status": "active", "date": "2025-03"}
    ]
  },
  "industries": ["fintech", "e-commerce", "saas"],
  "education": [
    {"degree": "BS Computer Science", "school": "UC Berkeley", "year": 2014}
  ],
  "keywords": ["microservices", "distributed systems", "CI/CD", "agile", "REST API"],
  "experience_summary": [
    {
      "title": "Senior Software Engineer",
      "company": "TechCo",
      "years": "2020-2026",
      "highlights": ["Led migration to Kubernetes", "Reduced deployment time 60%"]
    }
  ],
  "preferences": {
    "seniority": ["senior", "lead"],
    "employment_types": ["full-time", "contract"],
    "location": "anywhere_us",
    "arrangement": "all"
  }
}
```

### job_matches.json (Scout Agent → Orchestrator, Writer)

```json
{
  "run_date": "2026-04-24",
  "total_found": 12,
  "new_jobs": 4,
  "duplicates_skipped": 8,
  "matches": {
    "best_match": [
      {
        "job_id": "dice_12345",
        "title": "Senior Software Engineer",
        "company": "Acme Corp",
        "url": "https://dice.com/job/12345",
        "date_posted": "2026-04-23",
        "location": "Remote",
        "employment_type": "full-time",
        "score": 87,
        "score_breakdown": {
          "core_skills_match": 32,
          "title_seniority_alignment": 18,
          "industry_domain_fit": 13,
          "years_experience_fit": 14,
          "nice_to_have_skills": 7,
          "company_culture_signals": 3
        },
        "freshness_boost": 5,
        "matched_keywords": ["Python", "AWS", "Kubernetes", "microservices"],
        "missing_keywords": ["Terraform", "Go"],
        "job_description": "Full job description text...",
        "company_context": {
          "size": "500-1000",
          "industry": "fintech",
          "tech_stack": ["Python", "AWS", "Kubernetes", "PostgreSQL"],
          "culture_notes": "Fast-paced startup, recently Series C",
          "recent_news": "Raised $50M in Jan 2026"
        }
      }
    ],
    "possible_match": [],
    "not_matching": []
  }
}
```

### fix_instructions.json (Reviewer Agent → Writer Agent)

```json
{
  "job_id": "dice_12345",
  "review_pass": 1,
  "ats_coverage_current": 72,
  "ats_coverage_target": 85,
  "fixes_required": {
    "resume": [
      {
        "type": "inject_keyword",
        "keyword": "Terraform",
        "target_section": "experience",
        "suggestion": "Add to infrastructure bullet point in TechCo role"
      },
      {
        "type": "inject_keyword",
        "keyword": "CI/CD pipeline",
        "target_section": "achievements",
        "suggestion": "Reword deployment achievement to include CI/CD pipeline"
      },
      {
        "type": "format_fix",
        "issue": "summary_too_long",
        "detail": "Summary is 8 lines, target is 4 lines. Trim redundant sentences."
      }
    ],
    "cover_letter": [
      {
        "type": "tone_adjustment",
        "issue": "too_formal_for_startup",
        "suggestion": "Soften language, remove 'I am writing to express my interest', lead with impact"
      }
    ]
  },
  "skills_warnings": [
    {
      "type": "unverified_claim",
      "skill": "GraphQL",
      "detail": "Claimed in resume but not found in Skills/ files. Remove or soften."
    }
  ],
  "user_instruction": null
}
```

Note: when user provides an edit instruction (e.g., "emphasize more cloud experience"), the orchestrator sets `user_instruction` to that string and passes it to the writer alongside fix_instructions.json.

### scoring_feedback.json (Tracker Agent → Scout Agent)

```json
{
  "feedback_entries": [
    {
      "job_id": "dice_67890",
      "original_group": "possible_match",
      "original_score": 62,
      "user_action": "promoted_to_applied",
      "date": "2026-04-22",
      "signal": "Score was too low — user found this job highly relevant"
    },
    {
      "job_id": "dice_11111",
      "original_group": "best_match",
      "original_score": 81,
      "user_action": "rejected",
      "date": "2026-04-21",
      "signal": "Score was too high — user found this job irrelevant"
    }
  ]
}
```

Scout agent reads this on each run and can adjust scoring heuristics over time. Initially, it's logged for manual weight tuning. Future: automated weight adjustment.

---

## 4. User Configuration (Locked In)

```json
{
  "employment_types": ["full-time", "contract", "c2c"],
  "work_arrangement": "all",
  "location": "anywhere_us",
  "seniority": ["senior", "lead"],
  "salary_threshold": null,
  "exclusions": {
    "security_clearance": true,
    "entry_level_junior": true,
    "companies_blacklist": [],
    "technologies_avoid": []
  },
  "scoring_weights": {
    "core_skills_match": 0.35,
    "title_seniority_alignment": 0.20,
    "industry_domain_fit": 0.15,
    "years_experience_fit": 0.15,
    "nice_to_have_skills": 0.10,
    "company_culture_signals": 0.05
  },
  "match_thresholds": {
    "best_match": 75,
    "possible_match": 50,
    "not_matching": 0
  },
  "dedup_key": ["job_id", "title", "company"],
  "application_statuses": ["Discovered", "Tailored", "Applied", "Interview", "Rejected"],
  "ats_target_coverage": 85,
  "max_auto_fix_retries": 2,
  "rate_limit": {
    "max_concurrent_api_calls": 3,
    "delay_between_jobs_ms": 2000
  },
  "follow_up_reminder_days": 7,
  "archive_rejected_after_days": 30,
  "input_format": "docx",
  "output_format": "docx",
  "job_source": "dice_mcp"
}
```

---

## 5. Folder Structure

```
Job_Search_Agent/
├── config.json                        # User settings (Section 4)
├── candidate_profile.json             # Profile agent output
├── job_matches.json                   # Scout agent output
├── fix_instructions.json              # Reviewer → Writer handoff (temp, per job)
├── scoring_feedback.json              # Tracker → Scout feedback loop
├── application_tracker.json           # Master dedup + status log
├── application_tracker.backup.json    # Auto-backup before each write
├── run_history.json                   # Daily run summaries
├── master_summary.md                  # Updated each run
│
├── Skills/                            # ISOLATED for future enhancements
│   ├── technical_skills.docx
│   ├── soft_skills.docx
│   └── certifications.docx
│
├── Input_Files/
│   ├── master_resume.docx
│   └── job_requirements.docx
│
├── Output/
│   ├── Best_Match/
│   │   └── {Company} - {Title}/
│   │       ├── tailored_resume.docx       # Final approved (writer)
│   │       ├── cover_letter.docx          # Final approved (writer)
│   │       ├── job_details.md             # Writer, Lane C
│   │       ├── match_report.md            # Writer, Lane C
│   │       ├── interview_prep.md          # Writer, Lane C
│   │       ├── review_notes.md            # Reviewer
│   │       ├── fix_history.md             # Reviewer (appended per pass)
│   │       ├── v1_resume.docx             # Writer backup
│   │       └── v1_cover_letter.docx       # Writer backup
│   │
│   └── Possible_Match/
│       └── {Company} - {Title}/
│           └── ... (same structure)
│
├── Agents/                            # Agent definitions
│   ├── orchestrator.py
│   ├── profile_agent.py
│   ├── scout_agent.py
│   ├── writer_agent.py
│   ├── reviewer_agent.py
│   └── tracker_agent.py
│
└── dashboard.jsx                      # React dashboard

```

### Skills Folder — Future Enhancements
- Skill gap analysis per job
- Learning path recommendations
- Skill trending (market demand)
- Certification priority scoring
- Skills version history
- Cross-role transferability map

---

## 6. Orchestration Flow

```
DAILY RUN:

1. Orchestrator reads config.json
2. Orchestrator calls PROFILE AGENT
   → Reads input files + skills
   → Writes candidate_profile.json
   → If fail: ABORT RUN (no profile = nothing works)

3. Orchestrator calls SCOUT AGENT
   → Reads candidate_profile.json + config + tracker
   → Reads scoring_feedback.json (if exists, for weight adjustment)
   → Searches Dice MCP (with retry: 1s/2s/4s backoff, max 3 retries)
   → Dedup, filter, score, rank with freshness boost
   → Writes job_matches.json
   → If Dice MCP fails after retries: LOG ERROR, check if un-tailored
     jobs exist from previous runs, offer to process those instead

4. ═══ GATE 1 ═══
   Orchestrator presents job_matches.json to user
   Shows: grouped list with scores, company context, posted date
   User options: approve all / cherry-pick / skip entirely
   If skip: jump to step 10
   Result: approved_jobs[] list

5. FOR EACH approved job (sequential, 2s delay between jobs):

   5a. Orchestrator calls WRITER AGENT with one job
       → Runs Lanes A+B+C in parallel (max 3 concurrent API calls)
       → Writes: resume, cover letter, job details, match report, interview prep
       → Validates .docx output format
       → If .docx malformed: retry generation once
       → If retry fails: LOG ERROR, skip this job, continue to next

   5b. Orchestrator calls REVIEWER AGENT
       → Reads writer output + job description + profile + skills
       → Runs mechanical checks (ATS scan, format, skills cross-ref)
       → Runs quality review (story, tone, claims)
       → Writes review_notes.md + fix_history.md
       → If mechanical checks pass: go to 5d
       → If mechanical checks fail: writes fix_instructions.json, go to 5c

   5c. FIX LOOP (orchestrator manages retry count)
       → Orchestrator increments retry_count
       → If retry_count > 2: go to 5d with "fixes_incomplete" flag
       → Orchestrator passes fix_instructions.json to WRITER AGENT
       → Writer applies targeted fixes, saves backup as v{N}
       → Orchestrator calls REVIEWER AGENT again
       → If pass: go to 5d
       → If fail: repeat 5c (up to max retries)

   5d. ═══ USER APPROVAL ═══
       Orchestrator presents to user:
       - Resume preview + ATS coverage %
       - Review notes + quality score
       - Fix history (if fixes were applied)
       - Side-by-side with job description

       User options:
       - APPROVE → go to 5e
       - EDIT + REGENERATE → user provides instruction string,
         orchestrator sets fix_instructions.json.user_instruction,
         sends back to writer (step 5c, does NOT count against retry cap)
       - SKIP → mark as "Discovered" in tracker, go to 5f

   5e. Orchestrator calls TRACKER AGENT
       → Records job as "Tailored"
       → Updates application_tracker.json (atomic write with backup)
       → Appends to run_history.json

   5f. ═══ GATE 2 ═══
       Orchestrator asks: "Continue to next job?"
       If yes: next job in approved_jobs[]
       If no: jump to step 10

6-9. (reserved for future multi-board expansion)

10. END OF RUN
    Orchestrator calls TRACKER AGENT
    → Finalize run_history.json entry (total stats)
    → Regenerate master_summary.md
    → Run follow-up check: flag jobs in "Applied" for 7+ days
    → Run archival: move "Rejected" entries older than 30 days
    → Compute conversion metrics
    → Write scoring_feedback.json (if any user overrides happened)
```

---

## 7. Error Fallback Matrix

| Agent | Error | Severity | Orchestrator Action |
|-------|-------|----------|-------------------|
| Profile | Can't read .docx files | Critical | Abort run. Notify user: "Check input files." |
| Profile | Claude API timeout | Critical | Retry once. If fail, abort run. |
| Scout | Dice MCP rate limited | Retriable | Exponential backoff (1s/2s/4s), max 3 retries |
| Scout | Dice MCP down | Degraded | Log error. Offer to process previously discovered un-tailored jobs |
| Scout | No jobs found | Normal | Log. Show "0 new jobs" in daily digest. End run. |
| Writer | Claude API failure | Retriable | Retry once. If fail, skip this job, continue to next |
| Writer | Malformed .docx output | Retriable | Retry generation once. If fail, skip job |
| Writer | Lane B web search fails | Degraded | Generate cover letter without company research. Note in review. |
| Reviewer | Claude API failure | Degraded | Skip AI review, show only mechanical check results to user |
| Reviewer | ATS still failing after 2 fixes | Normal | Present to user with "fixes incomplete" flag |
| Tracker | JSON write failure | Critical | Restore from backup. Retry once. If fail, log and alert user |
| Tracker | Corrupted tracker file | Critical | Restore from backup. If backup also corrupt, start fresh with warning |
| Any | Unknown error | Varies | Log full error, skip current operation, continue pipeline if possible |

---

## 8. Dashboard Requirements (React .jsx)

### Panels

1. **Daily Digest** — last run timestamp, jobs found/new/skipped, resumes generated
2. **Conversion Funnel** — Discovered → Tailored → Applied → Interview with rates (from tracker)
3. **Pending Review** — jobs awaiting approval before generation (from Gate 1)
4. **Job Cards** — per-job card: title, company, score, ATS%, status, posted date, action buttons
5. **Follow-up Reminders** — applications in "Applied" status for 7+ days (from tracker)
6. **Run History Timeline** — last 30 days with stats

### Actions
- Bulk select + bulk status change
- One-click status updates (Applied, Interview, Rejected)
- "Follow up" flag button
- Preview resume/cover letter inline (read .docx from output folders)
- Filter/sort by: match group, status, date, score
- Edit + regenerate trigger (sends instruction back to orchestrator)

### Data Source
- Reads: application_tracker.json, run_history.json, job_matches.json
- Uses persistent storage API (window.storage) for live state
- Refreshes on page load
- Status changes write back to application_tracker.json → triggers tracker agent

---

## 9. Token Budget Estimates

| Operation | Agent | Tokens | Frequency |
|-----------|-------|--------|-----------|
| Profile extraction | Profile | ~2,000 | Once per run |
| Job search + scoring | Scout | ~500 | Once per run |
| Resume tailoring | Writer (Lane A) | ~4,000 | Per approved job |
| Cover letter + research | Writer (Lane B) | ~3,000 | Per approved job |
| Interview prep + details | Writer (Lane C) | ~1,500 | Per approved job |
| Auto-fix attempt | Writer | ~1,000 | 0-2 per job |
| Quality review | Reviewer | ~2,000 | 1-3 per job |
| Tracker updates | Tracker | ~200 | Per job + end of run |
| **Total per run (3 approved, avg 1 fix each)** | | **~35,000** | |
| **Without gates (10 jobs blind)** | | **~105,000** | |
| **Savings from gating** | | **~67%** | |

---

## 10. Build Order (Suggested for Claude Code)

```
Phase 1: Foundation + Data Layer
  1. Project scaffolding + full folder structure
  2. config.json with all settings
  3. Define all JSON schemas (profile, matches, fix_instructions, feedback)
  4. Shared file I/O utilities (read .docx, atomic JSON write, backup)

Phase 2: Profile Agent
  5. Skills/ folder reader (parse all .docx files)
  6. Input file readers (master resume, job requirements)
  7. Profile agent (Claude API structured extraction → candidate_profile.json)
  8. Unit tests for profile agent

Phase 3: Scout Agent
  9. Dice MCP integration (search_jobs with retry logic)
  10. Dedup engine (read application_tracker.json)
  11. Scoring engine (weighted criteria + freshness boost)
  12. Exclusion filter
  13. Scout agent (→ job_matches.json)
  14. Unit tests for scout agent

Phase 4: Orchestrator + Gates
  15. Orchestrator skeleton (agent call sequence)
  16. Gate 1 (present results, get user approval)
  17. Rate limiter (3 concurrent, 2s delay)
  18. Gate 2 (continue to next job?)
  19. Error fallback matrix implementation

Phase 5: Writer Agent
  20. Resume tailoring (Lane A) — .docx output
  21. Cover letter generation (Lane B) — .docx with web search
  22. Job details + interview prep (Lane C) — .md output
  23. Parallel lane runner (within writer)
  24. Fix application logic (read fix_instructions.json, apply targeted changes)
  25. Version management (backup v{N} files)
  26. .docx validation
  27. Unit tests for writer agent

Phase 6: Reviewer Agent
  28. ATS keyword scanner
  29. Format validator
  30. Skills cross-reference checker
  31. AI quality review (story, tone, claims)
  32. fix_instructions.json generator
  33. fix_history.md logger
  34. review_notes.md generator
  35. Unit tests for reviewer agent

Phase 7: Tracker Agent
  36. application_tracker.json manager (CRUD + atomic writes + backup)
  37. run_history.json logger
  38. master_summary.md generator
  39. Follow-up reminder flagging (7+ days)
  40. Archival (30-day rejected cleanup)
  41. Conversion funnel metrics calculator
  42. scoring_feedback.json writer
  43. Unit tests for tracker agent

Phase 8: Dashboard
  44. React dashboard (.jsx) with all 6 panels
  45. Inline resume/cover letter preview
  46. Bulk actions + status updates
  47. Dashboard ↔ tracker agent data binding

Phase 9: Integration + E2E
  48. Full pipeline integration test
  49. End-to-end test with sample data
  50. Error scenario testing
```

---

## 11. MCP Connectors Required

- **Dice** (primary job source): `search_jobs` tool, authless
- **Indeed** (optional, future): `search_jobs` + `get_job_details`

---

## 12. Files to Upload Before First Run

1. `master_resume.docx` → Input_Files/
2. `job_requirements.docx` → Input_Files/
3. `technical_skills.docx` → Skills/
4. `soft_skills.docx` → Skills/ (optional)
5. `certifications.docx` → Skills/ (optional)

At minimum: master resume + one skills file + job requirements.
