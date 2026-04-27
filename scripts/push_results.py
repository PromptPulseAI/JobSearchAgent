#!/usr/bin/env python3
"""
Optional: push Output/ and data/ to a private GitHub results repo after each run.
Keeps a searchable history of all tailored documents without cluttering the main repo.

Usage: python scripts/push_results.py [--repo https://github.com/YOU/job-results]
Configure RESULTS_REPO_URL in .env or pass --repo flag.

Requires git to be installed. Only pushes non-sensitive files (no .env, no logs).
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SAFE_DIRS = ["Output", "data/master_summary.md", "data/run_history.json"]


def run(cmd: list, cwd: str = ".") -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def push_results(repo_url: str, results_dir: Path) -> None:
    if not results_dir.exists():
        print(f"Results dir not found: {results_dir}")
        sys.exit(1)

    git_dir = results_dir / ".git"
    if not git_dir.exists():
        print("Initialising results repo...")
        run(["git", "init"], cwd=str(results_dir))
        run(["git", "remote", "add", "origin", repo_url], cwd=str(results_dir))

    # Write .gitignore if absent
    gitignore = results_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.env\nlogs/\n*.log\n__pycache__/\n", encoding="utf-8")

    # Stage safe files only
    for safe in SAFE_DIRS:
        src = Path(safe)
        if src.exists():
            dest = results_dir / safe
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                dest.write_bytes(src.read_bytes())
            elif src.is_dir():
                import shutil
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)

    run(["git", "add", "-A"], cwd=str(results_dir))

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    msg = f"Run results {ts}"
    result = run(["git", "commit", "-m", msg], cwd=str(results_dir))
    if "nothing to commit" in result.stdout + result.stderr:
        print("No new results to push.")
        return

    push = run(["git", "push", "-u", "origin", "main", "--force"], cwd=str(results_dir))
    if push.returncode == 0:
        print(f"Results pushed to {repo_url}")
    else:
        print(f"Push failed: {push.stderr[:300]}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Push job search results to private GitHub repo")
    parser.add_argument("--repo", default=os.environ.get("RESULTS_REPO_URL", ""), help="Target GitHub repo URL")
    parser.add_argument("--results-dir", default=".job_results", help="Local staging directory for results")
    args = parser.parse_args()

    if not args.repo:
        print("ERROR: set RESULTS_REPO_URL in .env or pass --repo")
        sys.exit(1)

    push_results(args.repo, Path(args.results_dir))


if __name__ == "__main__":
    main()
