#!/usr/bin/env python3
"""
Generate testing-agent config files for all successfully setup repos.

This script uses config_builder.py to generate testing-agent-config.yaml
files for repos that have been prepared with environment setup.

Usage:
    python generate_agent_configs.py [--data-root DATA_ROOT] [--repo-yamls-dir REPO_YAMLS_DIR]
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("generate_agent_configs.log"),
    ],
)
logger = logging.getLogger(__name__)


def generate_config(
    repo_id: str,
    repo_path: Path,
    repo_yamls_dir: Path,
) -> Tuple[str, bool, str]:
    """
    Generate testing-agent config for a single repo using config_builder.py.

    Returns:
        (repo_id, success: bool, message: str)
    """
    logger.info(f"[{repo_id}] Generating config...")

    # Find the repo yaml file
    repo_yaml = None
    for yaml_file in repo_yamls_dir.glob("*.yaml"):
        if repo_id in yaml_file.stem:
            repo_yaml = yaml_file
            break

    if not repo_yaml:
        logger.warning(f"[{repo_id}] No repo.yaml found, will generate minimal config")

    cmd = [
        sys.executable,
        str(Path(__file__).parent / "testing_agent" / "config_builder.py"),
        repo_id,
        str(repo_path),
        str(repo_yaml) if repo_yaml else "",
        "--mode", "helper",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        if result.returncode == 0:
            logger.info(f"[{repo_id}] ✓ Config generated")
            return repo_id, True, "Config generated successfully"
        else:
            error_msg = result.stderr or result.stdout
            logger.error(f"[{repo_id}] ✗ Failed to generate config")
            logger.error(f"  Error: {error_msg[:200]}")
            return repo_id, False, error_msg

    except subprocess.TimeoutExpired:
        msg = "Timeout generating config"
        logger.error(f"[{repo_id}] ✗ {msg}")
        return repo_id, False, msg
    except Exception as e:
        msg = str(e)
        logger.error(f"[{repo_id}] ✗ Error: {msg}")
        return repo_id, False, msg


def collect_repo_paths(data_root: Path) -> Dict[str, Path]:
    """Collect all repo paths that have been setup (have env_metadata.json)."""
    repo_paths = {}
    repos_dir = data_root / "repos"

    if not repos_dir.exists():
        logger.error(f"Repos directory not found: {repos_dir}")
        return repo_paths

    for repo_dir in sorted(repos_dir.iterdir()):
        if not repo_dir.is_dir():
            continue

        metadata_file = repo_dir / ".testing_agent" / "env_metadata.json"
        config_file = repo_dir / ".testing_agent" / "testing-agent-config.yaml"

        if metadata_file.exists():
            if config_file.exists():
                logger.debug(f"Config already exists for {repo_dir.name}, skipping")
                continue
            repo_paths[repo_dir.name] = repo_dir
        else:
            logger.debug(f"Repo {repo_dir.name} has no env_metadata.json, skipping")

    return repo_paths


def main():
    parser = argparse.ArgumentParser(
        description="Generate testing-agent config files for all prepared repos"
    )
    parser.add_argument(
        "--data-root",
        default="full_data-success_only-all",
        help="Root folder containing repos/ (default: %(default)s)",
    )
    parser.add_argument(
        "--repo-yamls-dir",
        default="full_data-success_only-all/repo-yamls",
        help="Directory containing repo YAML files (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without doing it",
    )

    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()
    repo_yamls_dir = Path(args.repo_yamls_dir).resolve()

    if not data_root.exists():
        logger.error(f"Data root not found: {data_root}")
        return 1

    if not repo_yamls_dir.exists():
        logger.warning(f"Repo YAML directory not found: {repo_yamls_dir}")
        logger.warning("Will generate configs without repo yaml files")
        repo_yamls_dir = None

    logger.info(f"Starting config generation for {data_root}")

    # Collect repos that need config files
    repo_paths = collect_repo_paths(data_root)
    logger.info(f"Found {len(repo_paths)} repos needing config files")

    if not repo_paths:
        logger.info("No repos need config files (all already have them or no envs setup)")
        return 0

    if args.dry_run:
        logger.info(f"[DRY RUN] Would generate configs for {len(repo_paths)} repos:")
        for repo_id in sorted(repo_paths.keys())[:5]:
            logger.info(f"  - {repo_id}")
        if len(repo_paths) > 5:
            logger.info(f"  ... and {len(repo_paths) - 5} more")
        return 0

    # Generate configs
    results = {}
    failed_repos = []
    completed_repos = []

    logger.info(f"Generating configs for {len(repo_paths)} repos...")

    for repo_id in sorted(repo_paths.keys()):
        repo_path = repo_paths[repo_id]
        _, success, message = generate_config(repo_id, repo_path, repo_yamls_dir or Path())
        results[repo_id] = (success, message)

        if success:
            completed_repos.append(repo_id)
        else:
            failed_repos.append(repo_id)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("CONFIG GENERATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Generated: {len(completed_repos)}")
    logger.info(f"Failed: {len(failed_repos)}")

    if failed_repos:
        logger.warning("\nFailed repos:")
        for repo_id in failed_repos[:10]:
            _, message = results.get(repo_id, (False, ""))
            first_line = message.split("\n")[0] if message else "Unknown error"
            logger.warning(f"  - {repo_id}: {first_line}")
        if len(failed_repos) > 10:
            logger.warning(f"  ... and {len(failed_repos) - 10} more")

    logger.info("=" * 60)
    logger.info(f"Log saved to: generate_agent_configs.log")

    return 1 if failed_repos else 0


if __name__ == "__main__":
    sys.exit(main())
