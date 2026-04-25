# Data Handling Policy — JobSearchAgent

> **Jurisdiction:** EU General Data Protection Regulation (GDPR) and equivalent.
> **Last updated:** April 2026

---

## 1. What Personal Data We Collect

| Data | Location | Purpose | Retention |
|------|----------|---------|-----------|
| Master resume + skills files | `Input_Files/`, `Skills/` | Source material for tailoring | Until you delete them |
| Candidate profile (extracted) | `data/candidate_profile.json` | Passed to agents per run | `gdpr.data_retention_days` (default 90d) |
| Generated resumes / cover letters | `Output/` | Your deliverables | Until you delete them |
| Application tracker | `data/application_tracker.json` | Status tracking | Active entries: 90d; rejected: 30d |
| Run history & metrics | `data/run_history.json` | Performance monitoring | 90d |
| API call logs | `data/logs/api_calls.jsonl` | Token cost tracking | `gdpr.log_retention_days` (default 30d) |
| Audit trail | `data/logs/audit.jsonl` | GDPR compliance | 30d |

---

## 2. Third-Party Data Processors

| Processor | What is shared | Legal basis | Privacy policy |
|-----------|---------------|-------------|----------------|
| **Anthropic Claude API** | Your resume text, job descriptions, skills | Legitimate interest (job search) | https://www.anthropic.com/legal/privacy |
| **Dice / Indeed / LinkedIn** | Search query keywords only (no PII) | Legitimate interest | Each platform's privacy policy |
| **Ollama (local)** | Same data as Claude API — runs entirely on your device | N/A (local processing) | — |

**No personal data is sold, rented, or shared with any other party.**

---

## 3. Data Minimization

The system is designed to send only what each API call needs:

- **Profile extraction**: Full resume text is sent once, then structured profile is used
- **Resume tailoring**: Sends relevant profile subset + job description only
- **Cover letter**: Sends skills + target titles + company context only
- **Logs**: All log entries are scrubbed of PII (emails, phone numbers, SSNs) via `utils/pii_scrubber.py`

---

## 4. Your Rights

### Right to Erasure (Article 17)

To permanently delete **all** personal data from this system:

```bash
python scripts/gdpr_erasure.py
```

This will:
1. Delete `data/candidate_profile.json`, `application_tracker.json`, all run data
2. Delete `Output/` (all generated resumes and cover letters)
3. Delete all log files
4. Write an erasure certificate to `data/gdpr_erasure_certificate.json`

> **Note:** Your source files in `Input_Files/` and `Skills/` are not deleted automatically — delete them manually if desired.

### Right to Access (Article 15)

All your data is stored in human-readable JSON and Markdown files in the `data/` and `Output/` directories. You have full access at all times.

### Right to Rectification (Article 16)

Edit your `Input_Files/master_resume.docx` or `Skills/*.docx` files and re-run the profile agent to update the extracted profile.

---

## 5. Security Measures

- **API keys** are stored in `.env` (excluded from git via `.gitignore`)
- **Input files** (resumes) are excluded from git
- **Output files** (generated resumes) are excluded from git
- **Logs** contain no PII (scrubbed before writing)
- All JSON writes use atomic rename to prevent data corruption

---

## 6. Consent

Before running the agent for the first time, set `gdpr.consent_acknowledged = true` in `config.json` to confirm you have read this policy.

The orchestrator will refuse to run until this is set.

---

## 7. Contact

This is a personal-use tool. If you share it with others, you are responsible for ensuring they receive a copy of this policy before using it.
