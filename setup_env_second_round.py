#!/usr/bin/env python3
"""
Second-round environment setup for failed repos.

This script:
- DOES NOT modify decision.json
- DOES NOT modify repo requirements files
- Automatically picks python version (with override for claf → py3.7)
- Automatically installs wheel, pytest, coverage
- After installation, attempts to import tables/sklearn; if import fails,
  installs fallback stable versions.
- Intended to “just get a usable runtime env” for remaining repos.
"""

import json
import subprocess
from pathlib import Path
import shlex

DATA_ROOT = Path("/home/ubuntu/testing-agent/full_data-success_only-all")

# Put ALL failed repos here ─ FULL NAMES + HASHES
FAILED_REPOS = [
    "ansible-community_molecule__b7d7740db482624182dd6c31600ca1c09669cfc5",
    "azure_aztk__19dde429a702c29bdcf86a69805053ecfd02edee",
    "ctlearn-project_ctlearn__2375af87fa36b7c93c5a3be5cab81784d4a2f64e",
    "educationaltestingservice_skll__f870a65904a449103d8f147e9746e548965f27d1",
    "google_capirca__eb768ea7e8cb33ab16786ddeb52b53122c740c65",
    "naver_claf__cffe4993564244545f085ede95eb848b94d07bde",
    "skoczen_will__437f8be397b864dc83c67af8942467907ccf1c21",
]


def run(cmd, cwd=None):
    print(f"[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
    return res.returncode == 0, res.stdout + res.stderr


# --------------------------------------------------------------------
# Python version detection (same rules as original script)
# --------------------------------------------------------------------
def detect_python_version(decision):
    variables = decision.get("variables", {})
    evidence = decision.get("evidence", {})
    tag = variables.get("python_version_tag", "")

    if tag.startswith("3.7"): return "/usr/bin/python3.7"
    if tag.startswith("3.8"): return "/usr/bin/python3.8"
    if tag.startswith("3.9"): return "/usr/bin/python3.9"
    if tag.startswith("3.6"): return "/usr/bin/python3.8"

    constraints = " ".join(evidence.get("python_version_constraints", []))
    if "3.7" in constraints: return "/usr/bin/python3.7"
    if "3.8" in constraints: return "/usr/bin/python3.8"
    if "3.9" in constraints: return "/usr/bin/python3.9"
    if "3.6" in constraints: return "/usr/bin/python3.8"

    return "/usr/bin/python3.10"


# --------------------------------------------------------------------
# venv creation
# --------------------------------------------------------------------
def create_venv(repo_path, python_bin):
    venv = repo_path / ".venv_helper"
    run(["rm", "-rf", str(venv)])
    ok, _ = run([python_bin, "-m", "venv", str(venv)])
    if not ok:
        raise RuntimeError("Venv creation failed.")
    return venv


def pip_install(venv, packages, cwd=None):
    pip = venv / "bin" / "pip"

    for p in packages:
        args = shlex.split(p)
        ok, out = run([str(pip), "install"] + args, cwd=cwd)
        if not ok:
            print(f"[WARN] pip failed for: {p}")
            print(out)


# --------------------------------------------------------------------
# Runtime import fix (tables & sklearn)
# --------------------------------------------------------------------
def ensure_runtime_libs(venv: Path, repo_path: Path):
    python = venv / "bin" / "python"

    def try_import(mod, fix_pkg):
        ok, _ = run([str(python), "-c", f"import {mod}"], cwd=repo_path)
        if not ok:
            print(f"[FIX] import {mod} failed → installing fallback: {fix_pkg}")
            pip_install(venv, [fix_pkg], cwd=repo_path)

    # PyTables fallback
    try_import("tables", "tables>=3.6.0 --only-binary=:all:")

    # scikit-learn fallback
    try_import("sklearn", "scikit-learn==0.24.2")


# --------------------------------------------------------------------
# Main per-repo setup
# --------------------------------------------------------------------
def setup_repo(repo_id):
    print(f"\n========== SECOND ROUND: Setting up {repo_id} ==========")

    repo_path = DATA_ROOT / "repos" / repo_id
    decision_path = DATA_ROOT / "envs" / repo_id / "decision.json"
    if not decision_path.exists():
        print("[ERROR] No decision.json")
        return

    decision = json.load(open(decision_path))

    # Pick python version
    python_bin = detect_python_version(decision)

    # Force TF old project to Py3.7
    if repo_id == "naver_claf__cffe4993564244545f085ede95eb848b94d07bde":
        python_bin = "/usr/bin/python3.7"
        print(f"[INFO] Overriding Python to 3.7 for {repo_id}")

    print(f"[INFO] Python selected: {python_bin}")

    # Create venv
    venv = create_venv(repo_path, python_bin)

    # pip bootstrap
    pip_install(venv, ["pip<24.1"], cwd=repo_path)
    pip_install(venv, ["wheel==0.38.4"], cwd=repo_path)

    # Install repo pip deps
    variables = decision.get("variables", {})
    pip_deps = variables.get("pip_deps", [])
    pip_install(venv, pip_deps, cwd=repo_path)

    # pytest deps
    pip_install(venv, ["pytest", "pytest-cov", "coverage"])

    # Fix runtime issues automatically
    ensure_runtime_libs(venv, repo_path)

    print(f"[DONE] {repo_id}")


# --------------------------------------------------------------------
# Run all failed repos
# --------------------------------------------------------------------
def main():
    for repo_id in FAILED_REPOS:
        setup_repo(repo_id)


if __name__ == "__main__":
    main()
