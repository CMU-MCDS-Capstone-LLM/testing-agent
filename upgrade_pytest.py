#!/usr/bin/env python3
"""Upgrade pytest and pytest-cov in all repo venvs"""

import subprocess
from pathlib import Path

BASE_PATH = Path("/home/ubuntu/testing-agent/full_data-success_only-all/repos")

for repo_dir in sorted(BASE_PATH.iterdir()):
    if not repo_dir.is_dir():
        continue

    pip_exe = repo_dir / ".venv_helper" / "bin" / "pip"

    if not pip_exe.exists():
        continue

    repo_name = repo_dir.name
    print(f"Upgrading {repo_name}...", end=" ", flush=True)

    try:
        result = subprocess.run(
            [str(pip_exe), "install", "--upgrade", "pytest", "pytest-cov"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            print("✅")
        else:
            print(f"⚠️ (code {result.returncode})")
    except subprocess.TimeoutExpired:
        print("⏱️ timeout")
    except Exception as e:
        print(f"❌ {e}")

print("\n✅ Done!")
