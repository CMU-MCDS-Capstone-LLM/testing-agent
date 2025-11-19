#!/usr/bin/env python3
"""
Batch environment setup script for 59 repos.

Strategy:
1. Install all unique system APT packages (one-time, system-wide)
2. Create a shared conda environment with common Python packages
3. For each repo, install its specific pip dependencies into the repo's venv
4. Log progress and any failures for manual review

Usage:
    python setup_all_envs.py [--data-root DATA_ROOT] [--skip-apt] [--skip-conda] [--resume]
"""

import argparse
import json
import logging
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("setup_envs.log"),
    ],
)
logger = logging.getLogger(__name__)


def run_command(cmd: List[str], cwd: Path = None, check: bool = True) -> Tuple[int, str]:
    """Run shell command and return exit code and output."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout + result.stderr
    except Exception as e:
        logger.error(f"Failed to run {' '.join(cmd)}: {e}")
        return 1, str(e)


def collect_all_apt_packages(data_root: Path) -> Set[str]:
    """Collect all unique APT packages needed across all repos."""
    apt_packages = set()
    envs_dir = data_root / "envs"

    for decision_file in envs_dir.glob("*/decision.json"):
        try:
            with open(decision_file) as f:
                data = json.load(f)
                pkgs = data.get("variables", {}).get("project_apt_packages", [])
                apt_packages.update(pkgs)
        except Exception as e:
            logger.warning(f"Failed to load {decision_file}: {e}")

    return apt_packages


def install_system_packages(apt_packages: Set[str]) -> bool:
    """Install all required APT packages system-wide."""
    if not apt_packages:
        logger.info("No APT packages required")
        return True

    logger.info(f"Installing {len(apt_packages)} system packages...")
    packages_list = sorted(apt_packages)
    logger.info(f"Packages: {', '.join(packages_list)}")

    # Update package list
    code, output = run_command(["sudo", "apt-get", "update"])
    if code != 0:
        logger.error(f"apt-get update failed:\n{output}")
        return False

    # Install packages
    code, output = run_command(["sudo", "apt-get", "install", "-y"] + packages_list)
    if code != 0:
        logger.error(f"apt-get install failed:\n{output}")
        return False

    logger.info("System packages installed successfully")
    return True


def setup_conda_env(env_name: str = "testing-agent-env") -> bool:
    """Create or update conda environment for common dependencies."""
    logger.info(f"Setting up conda environment: {env_name}")

    # Check if conda is available
    code, _ = run_command(["conda", "--version"])
    if code != 0:
        logger.error("Conda is not installed or not in PATH")
        return False

    # Check if env already exists
    code, output = run_command(["conda", "env", "list"])
    if env_name in output:
        logger.info(f"Conda environment {env_name} already exists, skipping creation")
        return True

    # Create conda env (using the repo's yaml file if available)
    env_yml = Path("testing-agent-env.yml")
    if env_yml.exists():
        code, output = run_command(["conda", "env", "create", "-f", str(env_yml)])
        if code != 0:
            logger.error(f"Failed to create conda env from YAML:\n{output}")
            return False
        logger.info("Conda environment created from testing-agent-env.yml")
    else:
        logger.warning("testing-agent-env.yml not found, using basic Python setup")
        code, output = run_command(["conda", "create", "-n", env_name, "python=3.11", "-y"])
        if code != 0:
            logger.error(f"Failed to create conda env:\n{output}")
            return False

    return True


def collect_repo_info(data_root: Path) -> Dict[str, dict]:
    """Collect repo IDs, paths, and their decision.json data."""
    repo_info = {}
    envs_dir = data_root / "envs"
    repos_dir = data_root / "repos"

    for decision_file in sorted(envs_dir.glob("*/decision.json")):
        repo_id = decision_file.parent.name
        repo_path = repos_dir / repo_id

        if not repo_path.exists():
            logger.warning(f"Repo path not found: {repo_path}")
            continue

        try:
            with open(decision_file) as f:
                decision = json.load(f)
                variables = decision.get("variables", {})
                repo_info[repo_id] = {
                    "repo_path": repo_path,
                    "decision_path": decision_file,
                    "variables": variables,
                    "status": "pending",
                    "error": None,
                }
        except Exception as e:
            logger.error(f"Failed to load {decision_file}: {e}")
            repo_info[repo_id] = {
                "repo_path": repo_path,
                "decision_path": decision_file,
                "status": "error",
                "error": str(e),
            }

    return repo_info


def should_skip_repo(repo_info: dict, resume_mode: bool = False) -> bool:
    """Check if repo should be skipped.

    In resume mode, skip if already completed.
    In normal mode, never skip (always re-setup).
    """
    if not resume_mode:
        return False
    # Skip if already completed
    metadata_path = repo_info["repo_path"] / ".testing_agent" / "env_metadata.json"
    return metadata_path.exists()


def install_repo_env(repo_id: str, repo_info: dict) -> bool:
    """Install environment for a single repo using env_manager.py."""
    logger.info(f"Setting up environment for {repo_id}...")

    repo_path = repo_info["repo_path"]
    decision_path = repo_info["decision_path"]

    # Call env_manager directly as a script to avoid loading the full testing_agent package
    # which has heavyweight dependencies (litellm, dynaconf, etc.)
    env_manager_path = Path(__file__).parent / "testing_agent" / "env_manager.py"

    cmd = [
        sys.executable,
        str(env_manager_path),
        repo_id,
        str(repo_path),
        str(decision_path),
    ]

    code, output = run_command(cmd)

    if code != 0:
        logger.error(f"Failed to setup {repo_id}:\n{output}")
        repo_info["status"] = "error"
        repo_info["error"] = output
        return False

    logger.info(f"Successfully setup {repo_id}")
    repo_info["status"] = "completed"
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Batch environment setup for testing-agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full setup from scratch
  python setup_all_envs.py

  # Skip system packages (already installed)
  python setup_all_envs.py --skip-apt

  # Resume from a specific repo
  python setup_all_envs.py --resume myrepo__sha
        """,
    )
    parser.add_argument(
        "--data-root",
        default="full_data-success_only-all",
        help="Root folder containing repos/, envs/, repo-yamls/ (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-apt",
        action="store_true",
        help="Skip system APT package installation",
    )
    parser.add_argument(
        "--skip-conda",
        action="store_true",
        help="Skip conda environment setup",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip repos that already have env_metadata.json (resume mode)",
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

    logger.info(f"Starting batch environment setup for {data_root}")
    logger.info(f"Data root: {data_root}")

    # Phase 1: Collect APT packages
    apt_packages = collect_all_apt_packages(data_root)
    logger.info(f"Found {len(apt_packages)} unique APT packages across all repos")

    if args.dry_run:
        logger.info("[DRY RUN] Would install APT packages: " + ", ".join(sorted(apt_packages)))
        repo_info = collect_repo_info(data_root)
        logger.info(f"[DRY RUN] Would setup {len(repo_info)} repos")
        return 0

    # Phase 2: Install system packages
    if not args.skip_apt:
        if not install_system_packages(apt_packages):
            logger.error("Failed to install system packages. Continuing anyway...")
    else:
        logger.info("Skipping APT package installation")

    # Phase 3: Setup conda (optional)
    if not args.skip_conda:
        setup_conda_env()
    else:
        logger.info("Skipping conda environment setup")

    # Phase 4: Install repo environments
    repo_info = collect_repo_info(data_root)
    logger.info(f"Found {len(repo_info)} repos to setup")

    skipped = 0
    completed = 0
    failed = 0
    failed_repos = []

    for repo_id in sorted(repo_info.keys()):
        info = repo_info[repo_id]

        if should_skip_repo(info, args.resume):
            skipped += 1
            logger.debug(f"Skipping {repo_id} (already completed or before resume point)")
            continue

        if info["status"] == "error":
            failed += 1
            failed_repos.append((repo_id, info["error"]))
            logger.error(f"Skipping {repo_id} due to earlier error")
            continue

        if install_repo_env(repo_id, info):
            completed += 1
        else:
            failed += 1
            failed_repos.append((repo_id, info["error"]))

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("BATCH SETUP SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total repos: {len(repo_info)}")
    logger.info(f"Completed: {completed}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Skipped: {skipped}")

    if failed_repos:
        logger.warning("\nFailed repos:")
        for repo_id, error in failed_repos:
            logger.warning(f"  - {repo_id}: {error.split(chr(10))[0]}")  # First line of error

    logger.info("=" * 60)
    logger.info(f"Setup log saved to: setup_envs.log")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
