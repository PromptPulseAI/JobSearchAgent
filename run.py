#!/usr/bin/env python3
"""
JobSearchAgent — Daily Run Entry Point
Target: Surface Pro 4 (8GB RAM, no GPU, Windows 10)

Usage:
  python run.py                          # Standard daily run
  python run.py --dry-run                # No API calls, no file writes
  python run.py --skip-search            # Process existing un-tailored jobs
  python run.py --job-id dice_12345      # Process a single specific job
  python run.py --no-local-model         # Skip Ollama (for 4GB RAM systems)
  python run.py --skip-gate1-if-no-new   # Skip Gate 1 if no new jobs (automated runs)
"""
import argparse
import asyncio

from dotenv import load_dotenv

# Load .env before anything else so ANTHROPIC_API_KEY etc. are available
load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JobSearchAgent daily run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline without API calls or file writes",
    )
    parser.add_argument(
        "--skip-search",
        action="store_true",
        help="Skip job search; process existing un-tailored jobs from tracker",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        default=None,
        metavar="DICE_ID",
        help="Process a single specific job ID only",
    )
    parser.add_argument(
        "--no-local-model",
        action="store_true",
        help="Skip Ollama; use Claude API for all AI tasks (required for 4GB RAM systems)",
    )
    parser.add_argument(
        "--skip-gate1-if-no-new",
        action="store_true",
        help="Skip Gate 1 if no new jobs found — for unattended Task Scheduler runs",
    )
    return parser.parse_args()


async def main() -> None:
    from agents.orchestrator import Orchestrator
    args = parse_args()
    orc = Orchestrator(
        config_path="config.json",
        dry_run=args.dry_run,
        skip_search=args.skip_search,
        target_job_id=args.job_id,
        no_local_model=args.no_local_model,
        skip_gate1_if_no_new=args.skip_gate1_if_no_new,
    )
    await orc.run()


if __name__ == "__main__":
    asyncio.run(main())
