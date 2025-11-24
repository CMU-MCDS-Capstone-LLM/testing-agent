#!/usr/bin/env python3
"""
Verify that name_map.json is correct by:
1. Checking that each repo folder exists
2. Checking that each YAML file exists
3. Checking that repo folder's commit matches YAML file's commit
4. Checking that source/target in YAML match what's expected
"""

import json
import yaml
from pathlib import Path

def main():
    base_dir = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
    name_map_path = base_dir / "name_map.json"
    repo_yamls_dir = base_dir / "repo-yamls"
    repos_dir = base_dir / "repos"

    with open(name_map_path) as f:
        name_map = json.load(f)

    print(f"Verifying {len(name_map)} entries in name_map.json\n")

    errors = []
    warnings = []
    success = 0

    for folder_name, yaml_name in sorted(name_map.items()):
        repo_folder = repos_dir / folder_name
        yaml_file = repo_yamls_dir / f"{yaml_name}.yaml"

        # Check 1: repo folder exists
        if not repo_folder.exists():
            errors.append(f"❌ {folder_name}: repo folder does not exist")
            continue

        # Check 2: YAML file exists
        if not yaml_file.exists():
            errors.append(f"❌ {folder_name}: YAML file not found at {yaml_file}")
            continue

        # Check 3: commit matches
        try:
            with open(yaml_file) as f:
                yaml_data = yaml.safe_load(f)

            yaml_repo = yaml_data.get("repo")
            yaml_commit = yaml_data.get("commit")
            yaml_source = yaml_data.get("source")
            yaml_target = yaml_data.get("target")

            # Extract commit from folder_name (format: owner_repo__commit)
            parts = folder_name.rsplit("__", 1)
            if len(parts) != 2:
                errors.append(f"❌ {folder_name}: invalid folder name format")
                continue

            _, folder_commit = parts

            if yaml_commit != folder_commit:
                errors.append(f"❌ {folder_name}: commit mismatch (folder: {folder_commit}, yaml: {yaml_commit})")
                continue

            # Check 4: repo name matches (owner_repo from yaml should match folder)
            expected_repo_part = yaml_repo.replace("/", "_")
            if not folder_name.startswith(expected_repo_part + "__"):
                errors.append(f"❌ {folder_name}: repo name mismatch (expected {expected_repo_part}, got from folder)")
                continue

            print(f"✓ {folder_name}")
            print(f"  └─ {yaml_name}.yaml ({yaml_source} → {yaml_target})")
            success += 1

        except Exception as e:
            errors.append(f"❌ {folder_name}: Error reading YAML - {e}")

    print(f"\n{'='*80}")
    print(f"Results: {success} ✓, {len(errors)} ❌, {len(warnings)} ⚠️")

    if errors:
        print(f"\nErrors:")
        for error in errors[:20]:
            print(f"  {error}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")

    if warnings:
        print(f"\nWarnings:")
        for warning in warnings[:10]:
            print(f"  {warning}")

    if not errors:
        print("\n✅ name_map.json is VALID!")
        return 0
    else:
        print(f"\n❌ Found {len(errors)} errors in name_map.json")
        return 1

if __name__ == "__main__":
    exit(main())
