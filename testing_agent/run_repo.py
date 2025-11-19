"""CLI helper to install env, build config, and invoke testing-agent for a repo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

from .config_builder import build_config, _load_yaml
from .env_manager import install_env, load_env_metadata
from .name_map_utils import load_name_map


def _default_repo_path(data_root: Path, repo_id: str) -> Path:
    return (data_root / "repos" / repo_id).resolve()


def _default_decision_path(data_root: Path, repo_id: str) -> Path:
    return (data_root / "envs" / repo_id / "decision.json").resolve()


def _find_repo_yaml(data_root: Path, repo_id: str) -> Path:
    repo_yaml_dir = (data_root / "repo-yamls").resolve()
    if not repo_yaml_dir.exists():
        raise FileNotFoundError(f"repo-yamls folder not found: {repo_yaml_dir}")
    commit_sha = repo_id.rsplit("__", 1)[-1]
    sha_prefix = commit_sha[:8]

    matches = [path for path in repo_yaml_dir.glob("*.yaml") if sha_prefix in path.name]
    if not matches:
        raise FileNotFoundError(
            f"Could not locate repo yaml containing '{sha_prefix}' under {repo_yaml_dir}"
        )
    if len(matches) > 1:
        owner_token = repo_id.split("_", 1)[0]
        owner_matches = [path for path in matches if owner_token in path.name]
        if len(owner_matches) == 1:
            matches = owner_matches
    if len(matches) != 1:
        raise RuntimeError(
            "Multiple candidate repo-yaml files found. Please specify --repo-yaml explicitly."
        )
    return matches[0]


def _load_optional_name_map(data_root: Path) -> dict[str, str]:
    """Load name_map.json from data_root or repository root if present."""
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        data_root / "name_map.json",
        repo_root / "name_map.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return load_name_map(base_dir=repo_root, name_map_path=candidate)
    return {}


def _resolve_repo_and_yaml(
    repo_key: str,
    data_root: Path,
    explicit_repo_yaml: Optional[str],
    *,
    require_repo_yaml: bool,
) -> tuple[str, Optional[Path]]:
    """
    Resolve user-provided repo key to (repo_id, repo_yaml_path).

    Accepts:
    - repo folder name (full commit) directly
    - yaml stem (short sha) if present in name_map.json
    - repo folder name present as key in name_map.json
    """
    mapping = _load_optional_name_map(data_root)
    repo_yaml_dir = (data_root / "repo-yamls").resolve()

    repo_id = None
    yaml_stem = None

    # If key is a repo folder listed in mapping.
    if repo_key in mapping:
        repo_id = repo_key
        yaml_stem = mapping[repo_key]
    else:
        # Try key as yaml stem (value side).
        for folder, stem in mapping.items():
            if stem == repo_key:
                repo_id = folder
                yaml_stem = stem
                break

    # Fallback: use as-is if repo folder exists.
    if repo_id is None:
        candidate_repo = data_root / "repos" / repo_key
        if candidate_repo.exists():
            repo_id = repo_key
        else:
            raise FileNotFoundError(
                f"Cannot resolve repo key '{repo_key}'. "
                "Provide full repo folder name or ensure name_map.json contains a mapping."
            )

    # Resolve repo_yaml
    repo_yaml_path: Optional[Path] = None
    if explicit_repo_yaml:
        repo_yaml_path = Path(explicit_repo_yaml).resolve()
    elif require_repo_yaml:
        if yaml_stem and (repo_yaml_dir / f"{yaml_stem}.yaml").exists():
            repo_yaml_path = (repo_yaml_dir / f"{yaml_stem}.yaml").resolve()
        else:
            repo_yaml_path = _find_repo_yaml(data_root, repo_id)

    return repo_id, repo_yaml_path


def install_environment(
    *,
    repo_id: str,
    repo_path: Path,
    decision_path: Path,
    python_executable: Optional[str],
    force: bool,
    skip_editable: bool,
    env_mode: str,
) -> EnvMetadata:
    metadata = load_env_metadata(repo_path)
    return install_env(
        repo_id=repo_id,
        repo_path=repo_path,
        decision_path=decision_path,
        python_executable=python_executable,
        force_recreate=force,
        skip_editable=skip_editable,
        env_mode=env_mode,
    )


def run_testing_agent(config_path: Path, *, cwd: Path) -> None:
    cmd = [sys.executable, "-m", "testing_agent.main", "--config", str(config_path)]
    subprocess.run(cmd, check=True, cwd=str(cwd))


def _load_repo_yaml(repo_yaml_path: Path) -> dict:
    with repo_yaml_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run testing-agent on a repo")
    parser.add_argument("repo_id", help="Repository identifier (folder under repos/)")
    parser.add_argument(
        "--data-root",
        default="full_data-success_only-all",
        help="Root folder containing repos/, envs/, repo-yamls/",
    )
    parser.add_argument("--repo-path", default=None, help="Override repo path (default derived from data-root)")
    parser.add_argument(
        "--decision-path",
        default=None,
        help="Override decision.json path (default derived from data-root)",
    )
    parser.add_argument("--repo-yaml", default=None, help="Path to commit yaml (auto-detected if omitted)")
    parser.add_argument("--config-output", default=None, help="Where to write the testing-agent config")
    parser.add_argument("--base-config", default=None, help="Optional base YAML to merge")
    parser.add_argument("--mode", choices=["helper", "eval"], default="helper")
    parser.add_argument("--extra-instructions", default="", help="Additional helper/eval instructions")
    parser.add_argument("--python", default=None, help="Python binary for virtualenv creation")
    parser.add_argument("--force-env", action="store_true", help="Recreate the virtualenv even if cached")
    parser.add_argument(
        "--env-mode",
        choices=["helper", "eval"],
        default="helper",
        help="Select which repository environment to use (default: helper).",
    )
    parser.add_argument("--skip-run", action="store_true", help="Only install env + config; skip running the agent")
    parser.add_argument("--skip-editable", action="store_true", help="Skip pip install -e . even if decision.json requests it")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = Path(args.data_root).resolve()

    resolved_repo_id, repo_yaml_path = _resolve_repo_and_yaml(
        args.repo_id,
        data_root,
        args.repo_yaml,
        require_repo_yaml=True,
    )

    repo_path = Path(args.repo_path).resolve() if args.repo_path else _default_repo_path(data_root, resolved_repo_id)
    decision_path = (
        Path(args.decision_path).resolve()
        if args.decision_path
        else _default_decision_path(data_root, resolved_repo_id)
    )

    env_metadata = install_environment(
        repo_id=resolved_repo_id,
        repo_path=repo_path,
        decision_path=decision_path,
        python_executable=args.python,
        force=args.force_env,
        skip_editable=args.skip_editable,
        env_mode=args.env_mode,
    )

    if args.env_mode == "eval" and repo_yaml_path:
        # For eval mode, create a new Docker image based on helper image
        # with source library uninstalled and target library installed
        yaml_data = _load_repo_yaml(repo_yaml_path)
        source_pkg = (yaml_data or {}).get("source")
        target_pkg = (yaml_data or {}).get("target")

        if source_pkg or target_pkg:
            print(f"Creating eval Docker image: {env_metadata.eval_image_name}")

            # Build pip commands for library migration
            pip_commands = []
            if source_pkg:
                pip_commands.append(f"pip uninstall -y {source_pkg}")
            if target_pkg:
                pip_commands.append(f"pip install {target_pkg}")

            # Combine commands
            command = " && ".join(pip_commands)

            # Run command in helper container and commit as eval image
            subprocess.run(
                [
                    "sudo", "docker", "run",
                    "--name", f"temp_{resolved_repo_id}_eval",
                    env_metadata.helper_image_name,
                    "bash", "-c", command
                ],
                check=True
            )

            # Commit the container as eval image
            subprocess.run(
                [
                    "sudo", "docker", "commit",
                    f"temp_{resolved_repo_id}_eval",
                    env_metadata.eval_image_name
                ],
                check=True
            )

            # Remove temporary container
            subprocess.run(
                ["sudo", "docker", "rm", f"temp_{resolved_repo_id}_eval"],
                check=False
            )

            print(f"✓ Created {env_metadata.eval_image_name}")

    base_config = _load_yaml(Path(args.base_config)) if args.base_config else None

    config_path = build_config(
        repo_id=resolved_repo_id,
        repo_path=repo_path,
        repo_yaml=repo_yaml_path,
        env_metadata=env_metadata,
        base_config=base_config,
        mode=args.mode,
        extra_instructions=args.extra_instructions,
        output_path=Path(args.config_output) if args.config_output else None,
    )

    result = {
        "repo_id": resolved_repo_id,
        "repo_path": str(repo_path),
        "config": str(config_path),
        "env_metadata": str(repo_path / ".testing_agent" / "env_metadata.json"),
        "mode": args.mode,
        "repo_yaml": str(repo_yaml_path) if repo_yaml_path else "",
        "env_mode": args.env_mode,
    }

    if args.skip_run:
        print(json.dumps(result, indent=2))
        return

    run_testing_agent(config_path, cwd=repo_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
