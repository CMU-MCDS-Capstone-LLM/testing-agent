#!/usr/bin/env python3
"""Fix test_command_dir in all config files to use full repo paths"""

import yaml
from pathlib import Path

BASE_PATH = Path("/home/ubuntu/testing-agent/full_data-success_only-all/repos")

for config_file in BASE_PATH.glob("*/testing-agent-config.yaml"):
    repo_path = config_file.parent

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)

        # Update test_command_dir to full repo path
        config["test_command_dir"] = str(repo_path)

        with open(config_file, "w") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)

        print(f"✅ {repo_path.name}")
    except Exception as e:
        print(f"❌ {repo_path.name}: {e}")

print("\n✅ Done!")
