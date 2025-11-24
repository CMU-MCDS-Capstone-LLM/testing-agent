#!/usr/bin/env python3
"""Test setup for just 5 repos"""
import subprocess
import sys
from pathlib import Path
import json

data_root = Path("full_data-success_only-all")
repos_dir = data_root / "repos"
envs_dir = data_root / "envs"

# Get first 5 repos
repos = sorted([d.name for d in repos_dir.iterdir() if d.is_dir()])[:5]

print(f"Testing setup for {len(repos)} repos: {repos}")
print()

for repo_id in repos:
    repo_path = repos_dir / repo_id
    decision_path = envs_dir / repo_id / "decision.json"
    
    if not decision_path.exists():
        print(f"❌ {repo_id}: no decision.json")
        continue
    
    # Check decision.json
    with open(decision_path) as f:
        decision = json.load(f)
        print(f"📦 {repo_id}:")
        pip_deps = decision.get("variables", {}).get("pip_deps", [])
        for dep in pip_deps:
            print(f"   - {dep}")
    
    print()
