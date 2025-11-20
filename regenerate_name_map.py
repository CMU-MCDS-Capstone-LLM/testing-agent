#!/usr/bin/env python3
"""
Regenerate name_map.json from PyMigBench database.
Maps repo folder names to their corresponding YAML filenames.
"""

import json
from pathlib import Path

from pymigbench.database import Database

def main():
    base_dir = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
    repo_yamls_dir = base_dir / "repo-yamls"
    repos_dir = base_dir / "repos"

    if not repo_yamls_dir.exists():
        print(f"Error: repo_yamls_dir not found: {repo_yamls_dir}")
        exit(1)

    print(f"Loading PyMigBench database from {repo_yamls_dir}...")
    db = Database.load_from_dir(repo_yamls_dir)

    migs = db.migs()
    print(f"Found {len(migs)} migrations\n")

    name_map = {}
    for mig in migs:
        # Get repo owner and name
        repo_parts = mig.repo.split("/")
        if len(repo_parts) != 2:
            print(f"⚠️  Skipping {mig.repo}: invalid repo format")
            continue

        owner, repo_name = repo_parts
        # Folder name format: owner_repo__commit_hash
        folder_name = f"{owner}_{repo_name}__{mig.commit}"

        # Check if corresponding repo folder exists
        repo_folder = repos_dir / folder_name
        if not repo_folder.exists():
            print(f"⚠️  {folder_name}: repo folder not found")
            continue

        # YAML filename format: source__target__owner@repo__commit_short
        commit_short = mig.commit[:8]
        yaml_name = f"{mig.source}__{mig.target}__{owner}@{repo_name}__{commit_short}"

        name_map[folder_name] = yaml_name
        print(f"✓ {folder_name} -> {yaml_name}")

    output_path = base_dir / "name_map.json"
    with open(output_path, "w") as f:
        json.dump(name_map, f, indent=2, sort_keys=True)

    print(f"\n✅ Generated name_map.json with {len(name_map)} entries")
    print(f"   Saved to: {output_path}")

if __name__ == "__main__":
    main()
