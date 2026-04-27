#!/usr/bin/env python3
"""
GDPR Right to Erasure — Article 17

Permanently deletes all personal data processed by JobSearchAgent.
Run this when you want to stop using the tool and remove all stored data.

Usage: python scripts/gdpr_erasure.py
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Files containing personal data
_PERSONAL_DATA_FILES = [
    ROOT / "data" / "candidate_profile.json",
    ROOT / "data" / "application_tracker.json",
    ROOT / "data" / "application_tracker.backup.json",
    ROOT / "data" / "job_matches.json",
    ROOT / "data" / "run_history.json",
    ROOT / "data" / "scoring_feedback.json",
    ROOT / "data" / "fix_instructions.json",
    ROOT / "data" / "pending_approval.json",
    ROOT / "master_summary.md",
]

_PERSONAL_DIRS = [
    ROOT / "Output",       # Generated resumes, cover letters
    ROOT / "data" / "logs",
]

# Source files the user manages manually (we warn but don't delete)
_MANUAL_DELETION_REMINDER = [
    ROOT / "Input_Files",
    ROOT / "Skills",
    ROOT / "templates",
]


def main() -> None:
    print("=" * 60)
    print("JobSearchAgent — GDPR Right to Erasure (Article 17)")
    print("=" * 60)
    print()
    print("This will permanently delete:")
    print("  • All data files (candidate profile, tracker, run history)")
    print("  • All generated documents (resumes, cover letters)")
    print("  • All log files (API calls, audit trail)")
    print()
    print("This will NOT delete (delete manually if needed):")
    for d in _MANUAL_DELETION_REMINDER:
        print(f"  • {d.relative_to(ROOT)}/")
    print()

    confirm = input("Type 'ERASE' to confirm permanent deletion: ").strip()
    if confirm != "ERASE":
        print("Aborted — no data was deleted.")
        sys.exit(0)

    erased = []
    failed = []

    for filepath in _PERSONAL_DATA_FILES:
        if filepath.exists():
            try:
                filepath.unlink()
                erased.append(str(filepath.relative_to(ROOT)))
                print(f"  Deleted: {filepath.relative_to(ROOT)}")
            except OSError as exc:
                failed.append((str(filepath.relative_to(ROOT)), str(exc)))
                print(f"  FAILED:  {filepath.relative_to(ROOT)} — {exc}")

    for dirpath in _PERSONAL_DIRS:
        if dirpath.exists():
            try:
                shutil.rmtree(dirpath)
                erased.append(str(dirpath.relative_to(ROOT)) + "/")
                print(f"  Deleted: {dirpath.relative_to(ROOT)}/")
            except OSError as exc:
                failed.append((str(dirpath.relative_to(ROOT)), str(exc)))
                print(f"  FAILED:  {dirpath.relative_to(ROOT)}/ — {exc}")

    print()
    print(f"Erased {len(erased)} items, {len(failed)} failures.")

    # Write erasure certificate (non-personal, safe to keep)
    cert_dir = ROOT / "data"
    cert_dir.mkdir(exist_ok=True)
    cert = {
        "gdpr_article": "Article 17 — Right to Erasure",
        "erasure_timestamp": datetime.now(timezone.utc).isoformat(),
        "items_erased": erased,
        "items_failed": [{"path": p, "error": e} for p, e in failed],
        "note": "Source files in Input_Files/ and Skills/ were not deleted. Remove manually if needed.",
    }
    cert_path = cert_dir / "gdpr_erasure_certificate.json"
    with open(cert_path, "w", encoding="utf-8") as f:
        json.dump(cert, f, indent=2)
    print(f"Erasure certificate written to: {cert_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
