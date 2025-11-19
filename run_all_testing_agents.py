#!/usr/bin/env python3
"""
Batch testing-agent runner for 59 repos.

This script runs testing-agent on all prepared repos (after setup_all_envs.py).

Strategy:
1. Load all repo metadata from .testing_agent/env_metadata.json
2. For each repo, invoke python -m testing_agent.main
3. Optionally parallelize using subprocess pools
4. Track progress and failures

Usage:
    python run_all_testing_agents.py [--data-root DATA_ROOT] [--parallel N] [--resume]
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("run_testing_agents.log"),
    ],
)
logger = logging.getLogger(__name__)


def run_testing_agent(
    repo_id: str,
    repo_path: Path,
    timeout: int = 3600,
) -> Tuple[str, bool, str]:
    """
    Run testing-agent for a single repo.

    Returns:
        (repo_id, success: bool, output: str)
    """
    logger.info(f"[{repo_id}] Starting testing-agent...")
    start_time = time.time()

    config_dir = repo_path / ".testing_agent"
    config_path = config_dir / "testing-agent-config.yaml"

    if not config_path.exists():
        msg = f"Config not found at {config_path}"
        logger.error(f"[{repo_id}] {msg}")
        return repo_id, False, msg

    cmd = [
        sys.executable,
        "-m",
        "testing_agent.main",
        "--config",
        str(config_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        elapsed = time.time() - start_time
        output = result.stdout + result.stderr

        if result.returncode == 0:
            logger.info(f"[{repo_id}] ✓ Completed in {elapsed:.1f}s")
            return repo_id, True, output
        else:
            logger.warning(f"[{repo_id}] ✗ Failed with return code {result.returncode}")
            return repo_id, False, output

    except subprocess.TimeoutExpired:
        logger.error(f"[{repo_id}] ✗ Timeout after {timeout}s")
        return repo_id, False, f"Timeout after {timeout}s"
    except Exception as e:
        logger.error(f"[{repo_id}] ✗ Error: {e}")
        return repo_id, False, str(e)


def collect_repo_paths(data_root: Path) -> Dict[str, Path]:
    """Collect all repo paths that have been setup."""
    repo_paths = {}
    repos_dir = data_root / "repos"

    for repo_dir in sorted(repos_dir.iterdir()):
        if not repo_dir.is_dir():
            continue

        metadata_file = repo_dir / ".testing_agent" / "env_metadata.json"
        if metadata_file.exists():
            repo_paths[repo_dir.name] = repo_dir
        else:
            logger.warning(f"Repo {repo_dir.name} has no env_metadata.json, skipping")

    return repo_paths


def load_completion_status(status_file: Path) -> Dict[str, bool]:
    """Load previous completion status from file."""
    if not status_file.exists():
        return {}

    try:
        with open(status_file) as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load status file: {e}")
        return {}


def save_completion_status(status_file: Path, status: Dict[str, bool]) -> None:
    """Save completion status to file."""
    try:
        with open(status_file, "w") as f:
            json.dump(status, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save status file: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch run testing-agent on all prepared repos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all repos sequentially
  python run_all_testing_agents.py

  # Run up to 4 repos in parallel
  python run_all_testing_agents.py --parallel 4

  # Resume from where you left off
  python run_all_testing_agents.py --parallel 4 --resume
        """,
    )
    parser.add_argument(
        "--data-root",
        default="full_data-success_only-all",
        help="Root folder containing repos/ (default: %(default)s)",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Number of parallel processes (default: %(default)s, 0 = all CPUs)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="Timeout per repo in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip repos that have already completed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without doing it",
    )

    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()

    if not data_root.exists():
        logger.error(f"Data root not found: {data_root}")
        return 1

    logger.info(f"Starting batch testing-agent run for {data_root}")

    # Collect repos
    repo_paths = collect_repo_paths(data_root)
    logger.info(f"Found {len(repo_paths)} prepared repos")

    if not repo_paths:
        logger.error("No prepared repos found. Run setup_all_envs.py first.")
        return 1

    # Load previous status if resuming
    status_file = Path("testing_agent_status.json")
    completed_status = load_completion_status(status_file) if args.resume else {}

    repos_to_run = []
    for repo_id in sorted(repo_paths.keys()):
        if args.resume and completed_status.get(repo_id):
            logger.debug(f"Skipping {repo_id} (already completed)")
            continue
        repos_to_run.append(repo_id)

    if args.dry_run:
        logger.info(f"[DRY RUN] Would run testing-agent on {len(repos_to_run)} repos")
        for repo_id in repos_to_run[:5]:
            logger.info(f"  - {repo_id}")
        if len(repos_to_run) > 5:
            logger.info(f"  ... and {len(repos_to_run) - 5} more")
        return 0

    logger.info(f"Running testing-agent on {len(repos_to_run)} repos (timeout: {args.timeout}s)")

    # Determine parallelism
    num_workers = args.parallel if args.parallel > 0 else None

    # Run repos
    results = {}
    failed_repos = []
    completed_repos = []

    if num_workers == 1:
        # Sequential execution
        logger.info("Running sequentially...")
        for repo_id in repos_to_run:
            repo_path = repo_paths[repo_id]
            repo_id_result, success, output = run_testing_agent(
                repo_id, repo_path, timeout=args.timeout
            )
            results[repo_id_result] = (success, output)

            if success:
                completed_repos.append(repo_id)
                completed_status[repo_id] = True
            else:
                failed_repos.append(repo_id)
                # Save first line of error for reporting
                first_line = output.split("\n")[0] if output else "Unknown error"
                logger.error(f"  Error: {first_line}")

            # Save progress periodically
            if len(completed_repos) % 5 == 0:
                save_completion_status(status_file, completed_status)

    else:
        # Parallel execution
        logger.info(f"Running in parallel with {num_workers} workers...")
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(
                    run_testing_agent, repo_id, repo_paths[repo_id], args.timeout
                ): repo_id
                for repo_id in repos_to_run
            }

            for i, future in enumerate(as_completed(futures), 1):
                repo_id, success, output = future.result()
                results[repo_id] = (success, output)

                if success:
                    completed_repos.append(repo_id)
                    completed_status[repo_id] = True
                else:
                    failed_repos.append(repo_id)

                # Save progress periodically
                if i % 5 == 0:
                    save_completion_status(status_file, completed_status)
                    logger.info(f"Progress: {i}/{len(repos_to_run)} completed")

    # Final progress save
    save_completion_status(status_file, completed_status)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("BATCH TESTING-AGENT RUN SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Repos to run: {len(repos_to_run)}")
    logger.info(f"Completed: {len(completed_repos)}")
    logger.info(f"Failed: {len(failed_repos)}")

    if failed_repos:
        logger.warning("\nFailed repos:")
        for repo_id in failed_repos[:10]:
            _, output = results.get(repo_id, (False, ""))
            first_line = output.split("\n")[0] if output else "Unknown error"
            logger.warning(f"  - {repo_id}: {first_line}")
        if len(failed_repos) > 10:
            logger.warning(f"  ... and {len(failed_repos) - 10} more")

    logger.info("=" * 60)
    logger.info(f"Status saved to: {status_file}")
    logger.info(f"Run log saved to: run_testing_agents.log")

    return 1 if failed_repos else 0


if __name__ == "__main__":
    sys.exit(main())
