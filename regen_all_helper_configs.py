#!/usr/bin/env python3
"""
Regenerate helper testing-agent configs for all envs under full_data-success_only-all.

- Pulls test_command / workdir heuristics from envs/<repo>/decision.json.
- Loads env_metadata (venv/python/activate/env vars) from repo .testing_agent/env_metadata.json.
- Uses repo-yamls + name_map.json to provide migration info to config_builder.
- Writes testing-agent-config.yaml into each repo directory.
"""

from pathlib import Path
import json
from testing_agent.config_builder import build_config
from testing_agent.env_manager import load_env_metadata

DATA_ROOT = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
ENV_DIR = DATA_ROOT / "envs"
REPO_DIR = DATA_ROOT / "repos"
REPO_YAML_DIR = DATA_ROOT / "repo-yamls"


def load_name_map() -> dict:
    """Load name_map.json from data root, falling back to repo root copy if needed."""
    candidates = [
        DATA_ROOT / "name_map.json",
        Path(__file__).resolve().parent / "name_map.json",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text())
    return {}


NAME_MAP = load_name_map()

# Repos explicitly marked as untestable/broken by user
SKIP = {
    "cyberbotics_urdf2webots__723168dbfff6132aa5591837d43c960679a0a2c4",
    "himkt_pyner__76106a9a4202497de9719b5a5563cadd697bd3d0",
    "alice-biometrics_petisco__9abf7b1f6ef8c55bdddcb9a5c2eff513f6a93130",
    "apryor6_flaskerize__59d8319355bf95f26949fe13ac3d6be5b5282fb6",
    "bcgov_theorgbook__728f86e941dfb6bdbee27628d28425757af5f22d",
}


def normalize_test_cmd(raw_cmd) -> str:
    """Handle list or string test_cmd; default to pytest."""
    if isinstance(raw_cmd, list):
        return " ".join(raw_cmd)
    if isinstance(raw_cmd, str):
        return raw_cmd.strip()
    return "pytest"


def build_test_command(decision: dict, env_meta) -> str:
    vars_block = decision.get("variables", {}) if isinstance(decision, dict) else {}
    raw = vars_block.get("test_cmd")
    if raw is None and env_meta:
        raw = getattr(env_meta, "test_cmd", None)
    if raw is None:
        raw = "pytest"
    return normalize_test_cmd(raw)


def build_workdir(repo_path: Path, decision: dict) -> str:
    worksubdir = decision.get("variables", {}).get("test_worksubdir") if isinstance(decision, dict) else None
    if not worksubdir:
        worksubdir = "."
    return str((repo_path / worksubdir).resolve())


def repo_yaml_path(repo_id: str):
    key = NAME_MAP.get(repo_id)
    if not key:
        return None
    path = REPO_YAML_DIR / f"{key}.yaml"
    return path if path.exists() else None


def main():
    for env_dir in sorted(ENV_DIR.iterdir()):
        repo_id = env_dir.name

        if repo_id in SKIP:
            print(f"[{repo_id}] skip (known bad)")
            continue

        repo_path = REPO_DIR / repo_id
        if not repo_path.exists():
            print(f"[{repo_id}] missing repo folder, skip")
            continue

        decision_path = env_dir / "decision.json"
        if not decision_path.exists():
            print(f"[{repo_id}] missing decision.json, skip")
            continue

        decision = json.loads(decision_path.read_text())

        # Try to load env metadata from repo; if absent, optionally try env_dir for safety.
        env_meta = load_env_metadata(repo_path)
        if env_meta is None:
            env_meta = load_env_metadata(env_dir)

        test_command = build_test_command(decision, env_meta)
        test_command_dir = build_workdir(repo_path, decision)
        repo_yaml = repo_yaml_path(repo_id)

        base_cfg = {
            "test_command": test_command,
            "test_command_dir": test_command_dir,
        }

        output = build_config(
            repo_id=repo_id,
            repo_path=repo_path,
            repo_yaml=repo_yaml,
            env_metadata=env_meta,
            base_config=base_cfg,
            mode="helper",
            output_path=repo_path / "testing-agent-config.yaml",
        )

        print(f"[{repo_id}] wrote {output}")


if __name__ == "__main__":
    main()
