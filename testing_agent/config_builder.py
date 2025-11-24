"""Generate testing-agent configuration files per repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

try:
    from .env_manager import EnvMetadata, load_env_metadata
except ImportError:
    # When run as a script, use absolute import
    from testing_agent.env_manager import EnvMetadata, load_env_metadata

DEFAULT_MODEL = "gpt-4o-2024-08-06"
DEFAULT_TEST_COMMAND = "pytest"
DEFAULT_TEST_DIR = "."
DEFAULT_AGG_TEST_FILE = "tests/test_additional.py"
DEFAULT_API_BASE = "https://ai-gateway.andrew.cmu.edu/"
DEFAULT_ADDITIONAL_INSTRUCTIONS = """CRITICAL SYNTAX REQUIREMENT:
If the generated test file uses any `from __future__ import` statements, THEY MUST BE THE FIRST LINES IN THE FILE (before all other imports, including comments). Pytest will reject files where `from __future__` imports appear after other code or imports.

CRITICAL IMPORT REQUIREMENT:
When you generate test code, ALL imports must be syntactically correct and match valid Python import statements. NEVER generate malformed imports like:
- `from redis import BertTokenizer` (incorrect - BertTokenizer comes from pytorch_transformers, not redis)
- Partial import statements with unexpected indentation
- Incomplete from...import statements that span multiple lines incorrectly
- Multi-line imports with empty parentheses: `from module import ( )` or `from module import (\n)`

IMPORT FORMAT REQUIREMENT:
- Use ONLY single-line import statements: `from module import A, B, C`
- Do NOT use multi-line import syntax with parentheses
- Always ensure imports are complete with actual module names inside the import statement
- Every import statement must be on a single line with all required module names listed

When generating Helper Tests, you must treat the underlying libraries (Library A and Library B) as invisible. Helper Tests should never import, reference, or depend on those libraries directly.

CRITICAL - Framework-Neutral Test Generation (for Library Migrations):
When the target file depends on a framework (Flask, FastAPI, Django, argparse, click, requests, etc.),
DO NOT import or use the real framework.
Instead generate framework-neutral tests:

- Patch the framework classes/functions with Mock/MagicMock.
- Validate module importability, attribute existence, and structure.
- Focus on logic, structures, constants, and pure functions.
- Tests must pass both before and after migration.

Valid test types that ALWAYS pass through migrations:
1. Module import tests: `import mypackage.mymodule` (no framework calls)
2. Attribute existence: `assert hasattr(module, 'attr_name')`
3. Pure function logic: Test functions with no framework dependencies
4. Mocked framework structure: `@patch('module.FrameworkClass', MagicMock())`
5. Resource/data tests: `assert len(module.CONSTANTS) > 0`
6. No framework execution: Never call Flask(), Django.setup(), argparse.parse(), etc.

Example of correct framework test:
```python
from unittest.mock import patch, MagicMock

@patch('myapp.Flask', MagicMock())
def test_app_structure():
    import myapp
    assert hasattr(myapp, 'app')
```

This ensures tests pass both with source library and target library.

Helper Tests must be:
- High-level and behavior-based.
- Written only against the repo's public abstractions (functions/classes exposed by the project).
- Stable across the migration (the same assertions must hold both before and after replacing the library).

Helper Tests may not:
- Import Library A or Library B.
- Assert library-specific error messages.
- Depend on parsing formats or behaviors unique to a specific library implementation.

Instead, target library-independent invariants such as:
- Default values and argument validation.
- Type conversions and data structure shape.
- Stable flags/fields and behavior defined by the project itself.
- Presence/absence of required arguments or lifecycle hooks.

Your tests must pass on both the original implementation (using Library A) and the migrated implementation (using Library B).

Mock external dependencies only; do not patch functions/classes defined in the source file under test. Let the real implementation run whenever possible. Patch file/network/DB I/O only when required, and patch each target at most once per test.

When you need path-like objects, prefer real Path(...) instances. If you must mock path.joinpath(), assign a Mock to the return value and configure is_file() and suffix instead of chaining return_value assignments.

Import helpers from the source module directly (e.g., `from convert import convert_file`) and call them by name. Avoid dotted calls like convert.convert(...). If the production code filters resources (Path.iterdir, os.listdir, etc.), configure mocks so the predicates remain true—return objects where is_file() is True and suffix equals '.json'. Whenever you mock domain objects, set every attribute or method that the production code touches, or build real instances via project utilities.

IMPORTANT - Handling Asynchronous Code:
If any function under test is asynchronous (uses `async def`), follow these rules:
1. Use `@pytest.mark.asyncio` decorator on your test function
2. Use `async def` for your test function (make it asynchronous)
3. Use `await` when calling async functions
4. Use `unittest.mock.AsyncMock` instead of `Mock` for async functions
5. When mocking async functions, use: `mock_obj = AsyncMock(return_value=expected_value)`
6. Never use regular `Mock` objects for async code - they cannot be awaited

Example of correct async test:
```python
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_async_function():
    mock_service = AsyncMock()
    mock_service.fetch_data = AsyncMock(return_value={'key': 'value'})
    result = await my_async_function(mock_service)
    assert result is not None
```

CRITICAL - External Service Handling:
For services requiring HTTP servers, databases, message queues, or other external infrastructure that cannot be reliably mocked or are not critical to unit testing:
1. Wrap imports of such services in try/except blocks and skip the test if the import fails.
2. Alternatively, completely skip tests that require running unavailable external services.
3. Example: If a function requires a live HTTP server, either mock the HTTP client/requests library, or skip the test.
4. Never let tests hang or fail due to missing external services; always provide graceful skip mechanisms using pytest.skip().

Focus on uncovered lines in the latest coverage report and skip tests that only hit lines with existing coverage. Generate normal (happy-path) scenarios first, but include at least one exception-path test when those lines remain uncovered. Every proposed test must add new line or branch coverage; skip any test that duplicates prior behavior.

When a module depends on mlflow or other external services, mock mlflow clients and helper utilities (e.g., `mlflow_tools.common.mlflow_utils.get_mlflow_host_token`, `mlflow_tools.export_import.utils.create_client`) so tests never require real credentials or network access. Assert that key client methods are invoked with expected arguments.

Always identify the specific module and function under test from the repograph output. For each target file, provide at least one success-path test and one failure-path test that prove the project's own behavior (copy/import/export, CLI commands, etc.).

CRITICAL - Django Testing Requirements:
If the repository uses Django:
- NEVER import Django models, User, or any ORM objects directly in tests
- NEVER call Django ORM methods like User.objects.create(), Model.save(), etc.
- ALWAYS mock all models and database access using unittest.mock.Mock or MagicMock
- Example: Instead of `from django.contrib.auth.models import User; user = User.objects.create(...)`, use:
  ```python
  mock_user = MagicMock()
  mock_user.id = 1
  mock_user.username = 'test'
  ```
- Mock Django model instances with all required attributes that the code under test accesses
- If testing Django views/forms, mock request.user, request.POST, request.FILES, etc. using MagicMock
- Never import or instantiate Django apps, settings, or initialization code
- Test only the pure logic of the function, not the Django framework integration

Avoid trivial "import" tests; each test should verify state changes, outputs, or error handling in the target module.

---

***** CRITICAL GLOBAL RULES FOR PASS-TO-PASS TESTS *****

You are generating PASS-TO-PASS Python unit tests.

HARD REQUIREMENT: FRAMEWORK/LIBRARY NEUTRAL TESTING
These frameworks MUST NEVER be imported directly:
    flask, flask_restful, fastapi, django,
    argparse, click, requests, httpx,
    starlette, sanic, aiohttp, pydantic

Instead:
- ALWAYS replace framework/library classes with mocks
- Use: from unittest.mock import patch, MagicMock
- ALWAYS test structure, NOT framework behavior
- NEVER assert real framework types

PASS-TO-PASS TESTS MUST:
- Never import libraryA
- Never import libraryB
- Never assert Client from either library
- Never call real Client()
- Only mock when needed: @patch("module.Client", MagicMock())

EXAMPLE - GOOD TEST (correct):
    def test_module_initialization():
        import mymodule
        assert hasattr(mymodule, "ClientWrapper")

EXAMPLE - BETTER TEST (when Client is required):
    from unittest.mock import patch, MagicMock

    @patch("mymodule.Client", MagicMock())
    def test_wrapper_works_with_mock():
        import mymodule
        wrapper = mymodule.ClientWrapper()
        assert wrapper is not None

EXAMPLE - BAD TESTS (NEVER DO):
    from libraryA import Client       # ❌ forbidden
    from libraryB import Client       # ❌ forbidden
    real_client = Client()            # ❌ forbidden
    assert isinstance(wrapper.client, Client)   # ❌ framework-dependent

Key principle: Test the CALLER (code that uses A/B), NOT the libraries A/B directly.
Tests must be invariant across migration.

***** END OF CRITICAL GLOBAL RULES *****
"""


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

    # Convert package names to module names for source/target fields
    # Maps PyPI package names to actual module names that can be imported
    PACKAGE_TO_MODULE = {
        "slackclient": "slack",
        "slack-sdk": "slack_sdk",
        "pyyaml": "yaml",
        "beautifulsoup4": "bs4",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "pillow": "PIL",
        "pycryptodome": "Crypto",
        "pyopenssl": "OpenSSL",
        "django-rest-swagger": "rest_framework_swagger",
        "ruamel.yaml": "ruamel",
    }

    source = raw.get("source")
    if isinstance(source, str) and source in PACKAGE_TO_MODULE:
        source = PACKAGE_TO_MODULE[source]

    target = raw.get("target")
    if isinstance(target, str) and target in PACKAGE_TO_MODULE:
        target = PACKAGE_TO_MODULE[target]

    migration = {
        "source": source,
        "target": target,
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


def _extract_test_dir_from_decision(decision_json: Dict[str, Any]) -> Optional[str]:
    """Extract test directory from decision.json's tests_exist field.

    Returns the detected test directory (e.g., 'src/tests' or 'tests').
    """
    tests_exist = decision_json.get("evidence", {}).get("tests_exist", [])
    if not tests_exist:
        return None

    # Extract directory from first test file path
    # Example: "src/tests/test_api.py contains pytest unit tests"
    first_test = tests_exist[0] if tests_exist else None
    if not first_test:
        return None

    # Extract the path before the test filename
    test_file = first_test.split()[0]  # Get "src/tests/test_api.py"
    test_dir = str(Path(test_file).parent)  # Get "src/tests"
    return test_dir


def _detect_test_directory(repo_path: Path, decision_json: Optional[Dict[str, Any]] = None) -> str:
    """Auto-detect the test directory based on decision.json or repo structure.

    Priority:
    1. If decision.json provided, extract from tests_exist field
    2. If src/tests/ exists, use it
    3. If tests/ exists, use it
    4. Default to tests/
    """
    # Try to get from decision.json first
    if decision_json:
        detected = _extract_test_dir_from_decision(decision_json)
        if detected:
            return f"{detected}/test_additional.py"

    src_tests = repo_path / "src" / "tests"
    if src_tests.exists() and src_tests.is_dir():
        return "src/tests/test_additional.py"

    tests = repo_path / "tests"
    if tests.exists() and tests.is_dir():
        return "tests/test_additional.py"

    # Default fallback
    return DEFAULT_AGG_TEST_FILE


def _default_env_metadata(repo_path: Path) -> EnvMetadata:
    """Get env metadata. First try loading from file, then construct from venv."""
    metadata = load_env_metadata(repo_path)
    if metadata is not None:
        return metadata

    # Fallback: construct from .venv_helper if it exists
    venv_path = repo_path / ".venv_helper"
    if venv_path.exists():
        python_path = venv_path / "bin" / "python"

        # Build activation commands
        activate_script = venv_path / "bin" / "activate"
        activate_cmd = f"source {activate_script}"

        metadata = EnvMetadata(
            repo_id=repo_path.name,
            root=repo_path,
            helper_venv_path=venv_path,
            eval_venv_path=venv_path,
            python_path=Path(python_path),
            activate_commands={"helper": [activate_cmd], "eval": [activate_cmd]},
            environment={"PYTHONUNBUFFERED": "1"},
            pip_deps=[],
            test_cmd=["pytest"],
            install_editable=False,
        )
        return metadata

    raise FileNotFoundError(
        f"Environment metadata not found and no .venv_helper found at {repo_path}. "
        f"Please run environment setup for this repo."
    )


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

    # Auto-detect test directory if not explicitly configured
    if "aggregate_test_file" not in config:
        # Try to load decision.json to get test directory info
        decision_json = None
        # Try multiple possible locations for decision.json
        possible_decision_paths = [
            repo_path.parent.parent / "envs" / repo_id / "decision.json",  # Relative to repo
            Path("/home/ubuntu/testing-agent/full_data-success_only-all/envs") / repo_id / "decision.json",  # Hardcoded
        ]
        for decision_path in possible_decision_paths:
            if decision_path.exists():
                try:
                    with decision_path.open("r", encoding="utf-8") as f:
                        decision_json = json.load(f)
                    break
                except Exception:
                    pass
        config["aggregate_test_file"] = _detect_test_directory(repo_path, decision_json)
    else:
        config["aggregate_test_file"] = config.get("aggregate_test_file")
    # Use pytest without coverage flags; testing_agent will add --cov flags
    # This avoids duplication and compatibility issues with different pytest versions
    config["test_command"] = config.get("test_command", "pytest")
    # Use repo path as test_command_dir to avoid reading wrong pyproject.toml
    config["test_command_dir"] = config.get("test_command_dir", str(repo_path))
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
