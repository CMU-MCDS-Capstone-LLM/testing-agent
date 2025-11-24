#!/usr/bin/env python3
"""
Third Round Environment Repair Script
-------------------------------------

Fixes the “requirements file missing” problems without modifying
decision.json or repo files.

For each repo:
- Reads pip_deps from decision.json.
- Extracts any "-r something.txt".
- Searches the *entire repo* to locate the real requirements file.
- Uses correct cwd for pip installation.
- Installs with fallback logic.
"""

import json
import subprocess
from pathlib import Path
import shlex

DATA_ROOT = Path("/home/ubuntu/testing-agent/full_data-success_only-all")

# These 4 repos you confirmed should be fixed:
TARGET_REPOS = [
    "bcgov_theorgbook__728f86e941dfb6bdbee27628d28425757af5f22d",
    "bretttolbert_verbecc-svc__24a848d285ae2c6f3e5b06d1a8ee718cb3f17133",
    "naver_claf__cffe4993564244545f085ede95eb848b94d07bde",
    "zalando_spilo__a83681c756fe8dfc8e5117c690bde16319e3e943",
]


def run(cmd, cwd=None):
    print(f"[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
    return res.returncode == 0, res.stdout + res.stderr


def pip_install(venv, package_args, cwd=None):
    pip = venv / "bin" / "pip"
    args = shlex.split(package_args)
    return run([str(pip), "install"] + args, cwd=cwd)


def find_file(repo_root: Path, filename: str):
    """Recursively search for the true location of a requirements file."""
    matches = list(repo_root.rglob(filename))
    return matches[0] if matches else None


def repair_requirements_import(venv: Path, repo_path: Path, req_file: str):
    """
    Fix pip -r requirements path by finding the correct location in repo.
    """
    print(f"[INFO] Looking for '{req_file}' in {repo_path}")

    # 1. Try direct path (decision.json relative path)
    direct = repo_path / req_file
    if direct.exists():
        print(f"[OK] Found via direct path: {direct}")
        pip_install(venv, f"-r {req_file}", cwd=repo_path)
        return

    # 2. Try recursive search for the filename anywhere in repo
    filename = Path(req_file).name
    found = find_file(repo_path, filename)

    if found:
        print(f"[FIX] Found actual location: {found}")
        # pip install with correct working directory
        pip_install(venv, f"-r {found.name}", cwd=found.parent)
    else:
        print(f"[WARN] Could not find file '{req_file}' anywhere inside repo. Skipping.")


def setup_single_repo(repo_id):
    print(f"\n========== THIRD ROUND: {repo_id} ==========")

    repo_path = DATA_ROOT / "repos" / repo_id
    decision_path = DATA_ROOT / "envs" / repo_id / "decision.json"

    if not decision_path.exists():
        print("[ERROR] No decision.json")
        return

    # load decision.json
    decision = json.load(open(decision_path))
    pip_deps = decision.get("variables", {}).get("pip_deps", [])

    # venv
    venv = repo_path / ".venv_helper"
    if not venv.exists():
        print("[ERROR] venv does not exist; run second_round first.")
        return

    # Process pip_deps
    for dep in pip_deps:
        args = shlex.split(dep)
        if len(args) >= 2 and args[0] == "-r":
            req_file = args[1]
            repair_requirements_import(venv, repo_path, req_file)

    print(f"[DONE] {repo_id}")


def main():
    for repo in TARGET_REPOS:
        setup_single_repo(repo)


if __name__ == "__main__":
    main()
