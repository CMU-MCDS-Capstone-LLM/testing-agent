#!/usr/bin/env python3
"""Verify that each repo's environment matches decision.json requirements"""

import json
import subprocess
from pathlib import Path

BASE_PATH = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
ENVS_DIR = BASE_PATH / "envs"
REPOS_DIR = BASE_PATH / "repos"

def check_repo_env(repo_name):
    """Check if repo environment matches decision.json"""
    decision_json = ENVS_DIR / repo_name / "decision.json"
    repo_path = REPOS_DIR / repo_name
    venv_path = repo_path / ".venv_helper"
    pip_exe = venv_path / "bin" / "pip"

    if not decision_json.exists():
        return repo_name, "SKIP", "no decision.json"

    if not venv_path.exists():
        return repo_name, "FAIL", "no .venv_helper"

    if not pip_exe.exists():
        return repo_name, "FAIL", "no pip executable"

    try:
        with open(decision_json) as f:
            decision = json.load(f)

        required_deps = decision.get("variables", {}).get("pip_deps", [])

        if not required_deps:
            return repo_name, "OK", "no deps required"

        # Get list of installed packages
        result = subprocess.run(
            [str(pip_exe), "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return repo_name, "WARN", "pip list failed"

        installed = json.loads(result.stdout)
        installed_names = {pkg["name"].lower() for pkg in installed}

        # Check each required dep
        missing = []
        for dep in required_deps:
            # Parse dep (e.g., "-r requirements.txt" or "pytest" or "package>=1.0")
            dep_name = dep.split()[0].split("==")[0].split(">=")[0].split("<")[0].lower()

            # Skip special cases
            if dep.startswith("-r "):
                # We can't easily verify file-based installs
                continue

            if dep_name not in installed_names:
                missing.append(dep_name)

        if missing:
            return repo_name, "WARN", f"missing: {', '.join(missing[:3])}"
        else:
            return repo_name, "OK", f"all {len(required_deps)} deps found"

    except Exception as e:
        return repo_name, "ERROR", str(e)[:50]

def main():
    print("Verifying environment setup for all repos...\n")

    results = {"OK": [], "WARN": [], "FAIL": [], "SKIP": [], "ERROR": []}

    for repo_dir in sorted(REPOS_DIR.iterdir()):
        if not repo_dir.is_dir():
            continue

        repo_name = repo_dir.name
        repo_name_short, status, message = check_repo_env(repo_name)
        results[status].append((repo_name_short, message))

        status_symbol = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "⏭️ ", "ERROR": "🔥"}
        print(f"{status_symbol.get(status, '?')} {repo_name_short}: {message}")

    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"✅ OK: {len(results['OK'])}")
    print(f"⚠️  WARN (env exists but missing some deps): {len(results['WARN'])}")
    for repo, msg in results['WARN'][:10]:
        print(f"  - {repo}: {msg}")
    if len(results['WARN']) > 10:
        print(f"  ... and {len(results['WARN']) - 10} more")

    print(f"\n❌ FAIL: {len(results['FAIL'])}")
    for repo, msg in results['FAIL']:
        print(f"  - {repo}: {msg}")

    print(f"\n🔥 ERROR: {len(results['ERROR'])}")
    for repo, msg in results['ERROR']:
        print(f"  - {repo}: {msg}")

if __name__ == "__main__":
    main()
