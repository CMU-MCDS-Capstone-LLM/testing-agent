#!/usr/bin/env python3
"""Setup environments for 10 new repos from decision.json"""

import json
import subprocess
import sys
from pathlib import Path

REPOS = [
    "google_capirca__eb768ea7e8cb33ab16786ddeb52b53122c740c65",
    "googlesamples_assistant-sdk-python__38e4e642cbfc2b0dd5ddf0151e87a867273f9a30",
    "grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f",
    "greenbone_python-gvm__75a11ed482b70b5ffceaac939294ebaad2d7fe58",
    "hbldh_pybankid__79e424cef579d6bffc1e40048e46febbd53aded5",
    "himkt_pyner__76106a9a4202497de9719b5a5563cadd697bd3d0",
    "htrc_htrc-feature-reader__7eae68aa368f3e1bc41b36a4f504f8bbe6ff46c8",
    "huggingface_transfer-learning-conv-ai__16074b209c8a94c887c2b869d773ea5f56d8593b",
    "hxlstandard_libhxl-python__0babff28e04c7da97cae91de78e86295bc42b118",
    "ictu_quality-time__d3a9a16a72348cece48c9788cf10db6cc043ec7c",
]

BASE_PATH = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
ENVS_DIR = BASE_PATH / "envs"
REPOS_DIR = BASE_PATH / "repos"

def find_available_python(requested_version):
    """Find available Python version - return requested or fallback to 3.10"""
    import shutil

    # Try requested version first
    python_exe = f"python{requested_version}"
    if shutil.which(python_exe):
        return python_exe

    # Try major.minor version (e.g., "3.8.18" -> "3.8")
    major_minor = ".".join(requested_version.split(".")[:2])
    python_exe = f"python{major_minor}"
    if shutil.which(python_exe):
        return python_exe

    # Fallback to 3.10
    print(f"⚠️  Python {requested_version} not found, using python3.10")
    return "python3.10"

def setup_repo_env(repo_name):
    """Setup environment for a single repo"""
    print(f"\n{'='*60}")
    print(f"Setting up: {repo_name}")
    print(f"{'='*60}")

    decision_json = ENVS_DIR / repo_name / "decision.json"
    repo_path = REPOS_DIR / repo_name

    if not decision_json.exists():
        print(f"❌ decision.json not found: {decision_json}")
        return False

    if not repo_path.exists():
        print(f"❌ repo path not found: {repo_path}")
        return False

    try:
        with open(decision_json) as f:
            decision = json.load(f)

        variables = decision.get("variables", {})
        python_version = variables.get("python_version_tag", "3.11").split("-")[0]  # e.g., "3.7.17-slim" -> "3.7"
        apt_packages = variables.get("project_apt_packages", [])
        pip_deps = variables.get("pip_deps", [])
        env_vars = variables.get("env_vars", {})

        print(f"Python version (requested): {python_version}")
        print(f"APT packages: {apt_packages}")
        print(f"PIP deps: {pip_deps}")

        # 1. Install apt packages (system-wide)
        if apt_packages:
            print(f"\n📦 Installing apt packages...")
            apt_cmd = ["sudo", "apt-get", "install", "-y"] + apt_packages
            result = subprocess.run(apt_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"⚠️  apt install failed (continuing anyway): {result.stderr[:200]}")
            else:
                print(f"✅ apt packages installed")

        # 2. Create venv in repo
        venv_path = repo_path / ".venv_helper"
        if venv_path.exists():
            print(f"✅ venv already exists: {venv_path}")
        else:
            # Find available Python version
            python_exe = find_available_python(python_version)
            print(f"\n🔧 Creating venv with {python_exe}...")
            create_cmd = [python_exe, "-m", "venv", str(venv_path)]
            result = subprocess.run(create_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"❌ Failed to create venv: {result.stderr}")
                return False
            print(f"✅ venv created")

        # 3. Install pip deps
        if pip_deps:
            print(f"\n📦 Installing pip dependencies...")
            pip_exe = venv_path / "bin" / "pip"

            # Upgrade pip first
            subprocess.run([str(pip_exe), "install", "--upgrade", "pip"],
                         capture_output=True)

            for dep in pip_deps:
                print(f"  Installing: {dep}")
                result = subprocess.run(
                    [str(pip_exe), "install"] + dep.split(),
                    capture_output=True,
                    text=True,
                    cwd=str(repo_path)
                )
                if result.returncode != 0:
                    print(f"  ⚠️  Failed: {result.stderr[:150]}")
                else:
                    print(f"  ✅ Installed")

        print(f"\n✅ {repo_name} setup completed")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print(f"Setting up environments for {len(REPOS)} repos...\n")

    success = []
    failed = []

    for repo_name in REPOS:
        if setup_repo_env(repo_name):
            success.append(repo_name)
        else:
            failed.append(repo_name)

    print(f"\n\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Success: {len(success)}/{len(REPOS)}")
    for repo in success:
        print(f"  - {repo}")

    if failed:
        print(f"\n❌ Failed: {len(failed)}/{len(REPOS)}")
        for repo in failed:
            print(f"  - {repo}")

    return 0 if not failed else 1

if __name__ == "__main__":
    sys.exit(main())
