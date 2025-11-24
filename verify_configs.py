
#!/usr/bin/env python3
"""
Verify that testing-agent-config.yaml files have correct source/target
by comparing with the corresponding YAML files from PyMigBench.
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

    print(f"Verifying source/target in {len(name_map)} config files\n")

    correct = 0
    incorrect = 0
    missing = 0

    for folder_name, yaml_name in sorted(name_map.items()):
        repo_folder = repos_dir / folder_name
        config_file = repo_folder / "testing-agent-config.yaml"
        yaml_file = repo_yamls_dir / f"{yaml_name}.yaml"

        if not config_file.exists():
            print(f"⚠️  {folder_name}: config file not found")
            missing += 1
            continue

        try:
            # Read config
            with open(config_file) as f:
                config_data = yaml.safe_load(f)

            # Read yaml
            with open(yaml_file) as f:
                yaml_data = yaml.safe_load(f)

            config_source = config_data.get("migration", {}).get("source")
            config_target = config_data.get("migration", {}).get("target")

            yaml_source = yaml_data.get("source")
            yaml_target = yaml_data.get("target")

            if config_source == yaml_source and config_target == yaml_target:
                print(f"✓ {folder_name}")
                print(f"  └─ {config_source} → {config_target}")
                correct += 1
            else:
                print(f"❌ {folder_name}: MISMATCH")
                print(f"  Config: {config_source} → {config_target}")
                print(f"  YAML:   {yaml_source} → {yaml_target}")
                incorrect += 1

        except Exception as e:
            print(f"❌ {folder_name}: Error - {e}")
            incorrect += 1

    print(f"\n{'='*80}")
    print(f"Results: {correct} ✓, {incorrect} ❌, {missing} ⚠️")

    if incorrect == 0 and missing == 0:
        print("\n✅ All configs are CORRECT!")
        return 0
    else:
        print(f"\n❌ Found {incorrect + missing} issues")
        return 1

if __name__ == "__main__":
    exit(main())
