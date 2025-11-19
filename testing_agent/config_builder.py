"""Generate testing-agent configuration files per repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .env_manager import EnvMetadata, load_env_metadata

DEFAULT_MODEL = "gpt-4o-2024-08-06"
DEFAULT_TEST_COMMAND = "pytest"
DEFAULT_TEST_DIR = "."
DEFAULT_AGG_TEST_FILE = "tests/test_additional.py"
DEFAULT_API_BASE = "https://ai-gateway.andrew.cmu.edu/"
DEFAULT_ADDITIONAL_INSTRUCTIONS = """When generating Helper Tests, you must treat the underlying libraries (Library A and Library B) as invisible. Helper Tests should never import, reference, or depend on those libraries directly.\n\nHelper Tests must be:\n- High-level and behavior-based.\n- Written only against the repo's public abstractions (functions/classes exposed by the project).\n- Stable across the migration (the same assertions must hold both before and after replacing the library).\n\nHelper Tests may not:\n- Import Library A or Library B.\n- Assert library-specific error messages.\n- Depend on parsing formats or behaviors unique to a specific library implementation.\n\nInstead, target library-independent invariants such as:\n- Default values and argument validation.\n- Type conversions and data structure shape.\n- Stable flags/fields and behavior defined by the project itself.\n- Presence/absence of required arguments or lifecycle hooks.\n\nYour tests must pass on both the original implementation (using Library A) and the migrated implementation (using Library B).\n\nMock external dependencies only; do not patch functions/classes defined in the source file under test. Let the real implementation run whenever possible. Patch file/network/DB I/O only when required, and patch each target at most once per test.\n\nWhen you need path-like objects, prefer real Path(...) instances. If you must mock path.joinpath(), assign a Mock to the return value and configure is_file() and suffix instead of chaining return_value assignments.\n\nImport helpers from the source module directly (e.g., `from convert import convert_file`) and call them by name. Avoid dotted calls like convert.convert(...). If the production code filters resources (Path.iterdir, os.listdir, etc.), configure mocks so the predicates remain true—return objects where is_file() is True and suffix equals '.json'. Whenever you mock domain objects, set every attribute or method that the production code touches, or build real instances via project utilities.\n\nCRITICAL - External Service Handling:\nFor services requiring HTTP servers, databases, message queues, or other external infrastructure that cannot be reliably mocked or are not critical to unit testing:\n1. Wrap imports of such services in try/except blocks and skip the test if the import fails.\n2. Alternatively, completely skip tests that require running unavailable external services.\n3. Example: If a function requires a live HTTP server, either mock the HTTP client/requests library, or skip the test.\n4. Never let tests hang or fail due to missing external services; always provide graceful skip mechanisms using pytest.skip().\n\nFocus on uncovered lines in the latest coverage report and skip tests that only hit lines with existing coverage. Generate normal (happy-path) scenarios first, but include at least one exception-path test when those lines remain uncovered. Every proposed test must add new line or branch coverage; skip any test that duplicates prior behavior.\n\nWhen a module depends on mlflow or other external services, mock mlflow clients and helper utilities (e.g., `mlflow_tools.common.mlflow_utils.get_mlflow_host_token`, `mlflow_tools.export_import.utils.create_client`) so tests never require real credentials or network access. Assert that key client methods are invoked with expected arguments.\n\nAlways identify the specific module and function under test from the repograph output. For each target file, provide at least one success-path test and one failure-path test that prove the project's own behavior (copy/import/export, CLI commands, etc.).\n\nAvoid trivial "import" tests; each test should verify state changes, outputs, or error handling in the target module.\n"""


def _load_yaml(path: Optional[Path]) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Base config must be a mapping: {path}")
    return data


def _load_migration(repo_yaml: Optional[Path]) -> Dict[str, Any]:
    if not repo_yaml or not repo_yaml.exists():
        return {}
    with repo_yaml.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Repo yaml must be a mapping: {repo_yaml}")
    migration = {
        "source": raw.get("source"),
        "target": raw.get("target"),
        "files": raw.get("files", []),
        "commit": raw.get("commit"),
        "repo": raw.get("repo"),
    }
    migration["workspace_symbols"] = raw.get("workspace_symbols", []) or []
    return migration


def _metadata_dir(repo_path: Path) -> Path:
    meta = repo_path / ".testing_agent"
    meta.mkdir(parents=True, exist_ok=True)
    return meta.resolve()


def _default_env_metadata(repo_path: Path) -> EnvMetadata:
    metadata = load_env_metadata(repo_path)
    if metadata is None:
        raise FileNotFoundError(
            f"Environment metadata not found. Please run env_manager.install_env for {repo_path}."
        )
    return metadata


def build_config(
    *,
    repo_id: str,
    repo_path: Path,
    repo_yaml: Optional[Path],
    env_metadata: Optional[EnvMetadata] = None,
    base_config: Optional[Dict[str, Any]] = None,
    mode: str = "helper",
    extra_instructions: str = "",
    output_path: Optional[Path] = None,
) -> Path:
    repo_path = repo_path.resolve()
    metadata_dir = _metadata_dir(repo_path)

    base_cfg = dict(base_config or {})

    env_meta = env_metadata or _default_env_metadata(repo_path)

    config: Dict[str, Any] = {}
    config.update(base_cfg)

    config["repo_name"] = repo_id
    config["project_root_candidates"] = [str(repo_path)]
    config["metadata_folder"] = str(metadata_dir)
    config["code_coverage_report_path"] = str(metadata_dir / "coverage.xml")
    config["selector_output_path"] = str(metadata_dir / "repograph_result.json")
    config["aggregate_test_file"] = config.get("aggregate_test_file", DEFAULT_AGG_TEST_FILE)
    # Always use pytest with coverage, ignore decision.json test_cmd
    # This ensures consistent test running and coverage generation
    config["test_command"] = config.get("test_command", "pytest --cov --cov-report=xml")
    config["test_command_dir"] = config.get("test_command_dir", DEFAULT_TEST_DIR)
    config["coverage_type"] = config.get("coverage_type", "cobertura")
    config["desired_coverage"] = config.get("desired_coverage", 80)
    config["max_iterations"] = config.get("max_iterations", 2)
    config["model"] = config.get("model", DEFAULT_MODEL)
    config["api_base"] = config.get("api_base") or DEFAULT_API_BASE
    config["max_run_time"] = config.get("max_run_time", 180)

    helper_instructions = config.get("additional_instructions", DEFAULT_ADDITIONAL_INSTRUCTIONS)
    combined_instructions = "\n\n".join(
        [instr for instr in [helper_instructions.strip(), extra_instructions.strip()] if instr]
    )
    config["additional_instructions"] = combined_instructions

    html_report = metadata_dir / "testing_agent_report.html"
    log_file = metadata_dir / "testing_agent.log"
    db_file = metadata_dir / "cover_agent_unit_test_runs.db"
    config["html_report_path"] = str(html_report)
    config["log_file"] = str(log_file)
    config["log_level"] = config.get("log_level", "INFO")
    config["cover_agent_log_db_path"] = str(db_file)

    migration_block = _load_migration(repo_yaml)
    if migration_block:
        if mode != "eval":
            migration_block.pop("files", None)
        config["migration"] = migration_block
    else:
        config.setdefault(
            "migration",
            {
                "source": config.get("repo_name", ""),
                "workspace_symbols": [],
            },
        )

    helper_cmds = env_meta.activate_commands.get("helper")
    eval_cmds = env_meta.activate_commands.get("eval")
    config["repo_venv_python_candidates"] = [str(env_meta.python_path)]
    if mode == "eval" and eval_cmds:
        config["repo_env_pre_commands"] = eval_cmds
    else:
        config["repo_env_pre_commands"] = helper_cmds or []
    config["repo_env_environment"] = env_meta.environment

    config.setdefault("pytest_cov_target", "")
    config.setdefault("pytest_include_expr", "")
    config.setdefault("pytest_exclude_expr", "")
    config.setdefault("run_tests_multiple_times", 1)
    config.setdefault("branch", "main")
    config["diff_coverage"] = mode == "eval"
    config.setdefault("run_each_test_separately", False)

    if output_path is None:
        output_path = repo_path / "testing-agent-config.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a testing-agent config for a repo")
    parser.add_argument("repo_id", help="Repository identifier")
    parser.add_argument("repo_path", help="Path to the repository root")
    parser.add_argument(
        "repo_yaml",
        nargs="?",
        default=None,
        help="Path to the commit YAML file (required for eval mode)",
    )
    parser.add_argument(
        "--env-metadata",
        default=None,
        help="Path to env_metadata.json (defaults to <repo>/.testing_agent/env_metadata.json)",
    )
    parser.add_argument("--base-config", default=None, help="Optional base YAML config to merge")
    parser.add_argument("--mode", choices=["helper", "eval"], default="helper")
    parser.add_argument("--output", default=None, help="Destination config path")
    parser.add_argument("--extra-instructions", default="", help="Additional prompt text appended to the config")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_path = Path(args.repo_path)
    env_metadata_path = Path(args.env_metadata) if args.env_metadata else None
    env_meta = None
    if env_metadata_path:
        if not env_metadata_path.exists():
            raise FileNotFoundError(f"env metadata not found: {env_metadata_path}")
        env_meta = EnvMetadata.from_json(env_metadata_path)

    base_config = _load_yaml(Path(args.base_config)) if args.base_config else None

    output = build_config(
        repo_id=args.repo_id,
        repo_path=repo_path,
        repo_yaml=Path(args.repo_yaml) if args.repo_yaml else None,
        env_metadata=env_meta,
        base_config=base_config,
        mode=args.mode,
        extra_instructions=args.extra_instructions,
        output_path=Path(args.output) if args.output else None,
    )
    print(json.dumps({"config": str(output)}, indent=2))


if __name__ == "__main__":
    main()
