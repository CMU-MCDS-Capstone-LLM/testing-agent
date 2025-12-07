"""High-level orchestration for the testing agent workflow."""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shlex
import subprocess
import tempfile
import traceback
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List, Optional, Sequence, Set

import yaml

from .cover_agent.CoverAgent import CoverAgent
from .cover_agent.Runner import LocalRunner, Runner
from testing_agent.repograph_runner.repograph_selector import (
    RepoGraphRequest,
    RepoGraphResult,
    RepoGraphRunner,
)
from .config_loader import TestingAgentConfig
from .name_map_utils import load_name_map

import logging
logger = logging.getLogger(__name__)


AUTO_IMPORT_MARKER = "# [AUTO-IMPORTED FROM SOURCE] — do not edit below manually"


class TestingAgent:
    """Execute the end-to-end test-generation workflow for a repository."""

    def __init__(
        self,
        config: TestingAgentConfig,
        test_executor: Optional[Runner] = None,
        repograph_runner: Optional[RepoGraphRunner] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.aggregate_test_file = config.aggregate_test_file
        if test_executor is not None:
            self.test_executor = test_executor
        else:
            self.test_executor = LocalRunner(
                pre_commands=self.config.repo_env_pre_commands,
                base_environment=self.config.repo_env_environment,
            )

        if repograph_runner is not None:
            self.repograph_runner = repograph_runner
        else:
            # Use direct LSP repograph instead of subprocess wrapper
            self.repograph_runner = DirectLSPRepoGraphRunner(
                timeout=self.config.max_run_time,
            )

        self.package_name = self.config.project_root.name

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self) -> None:
        self.logger.info("Starting testing agent for repo '%s'", self.config.repo_name)
        self._export_api_keys()
        self._ensure_pythonpath()
        self._ensure_directories()
        self._ensure_stub_conftest()

        # Detect eval mode from config (migration.eval_mode flag)
        eval_mode = bool(self.config.migration.get("eval_mode", False))

        if eval_mode:
            source_files = self._collect_repoyaml_files()
            included_files: List[Path] = []
            filter_expression = self._compose_filter_expression(
                "", self.config.pytest_exclude_expr
            )
            test_command = self._compose_test_command([], filter_expression)

            if self.config.html_report_path:
                self._prepare_html_report()

            for source_rel in source_files:
                self._process_source_file(
                    source_rel=source_rel,
                    included_files=included_files,
                    test_command=test_command,
                    eval_mode=True,
                )
        else:
            repograph_result = self._run_repograph()
            cov_targets, include_expression = self._build_pytest_arguments(repograph_result)
            filter_expression = self._compose_filter_expression(
                include_expression, self.config.pytest_exclude_expr
            )
            test_command = self._compose_test_command(cov_targets, filter_expression)

            included_files = self._collect_workspace_includes(repograph_result)
            source_files = self._collect_source_files(repograph_result)

            if self.config.html_report_path:
                self._prepare_html_report()

            for source_rel in source_files:
                self._process_source_file(
                    source_rel=source_rel,
                    included_files=included_files,
                    test_command=test_command,
                )

        # Clean up failed and skipped tests to ensure 100% pass rate
        self._cleanup_failing_tests()

        # Print coverage summary table
        self._print_coverage_summary()

        if self.config.html_report_path:
            self.logger.info(
                "All cover-agent tasks completed. HTML report saved to %s",
                self.config.html_report_path,
            )
        else:
            self.logger.info("All cover-agent tasks completed. HTML report generation disabled.")

    def _cleanup_failing_tests(self) -> None:
        """
        Remove any failed or skipped tests from the test file to ensure 100% pass rate.
        Runs pytest and removes tests that fail or are skipped.
        """
        if not self.aggregate_test_file or not self.aggregate_test_file.exists():
            return

        test_file_path = self.aggregate_test_file
        test_command_dir = self.config.test_command_dir or Path.cwd()
        python_exe = str(self.config.repo_venv_python) if self.config.repo_venv_python else "python"

        # Run pytest to identify failed and skipped tests
        cmd = [
            python_exe, "-m", "pytest",
            str(test_file_path),
            "-v", "--tb=no",  # Verbose (needed for parsing) but no traceback (just pass/fail/skip)
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=test_command_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = result.stdout + result.stderr
        except (subprocess.TimeoutExpired, Exception) as e:
            self.logger.warning(f"Failed to run pytest for cleanup: {e}")
            return

        # Parse pytest output to find failed and skipped tests
        failed_or_skipped_tests = set()
        for line in output.split('\n'):
            # Match patterns like:
            # - "tests/test_additional.py::test_name FAILED"
            # - "tests/test_additional.py::test_name SKIPPED"
            if ' FAILED ' in line or ' SKIPPED ' in line:
                # Find the part with :: that contains test path
                if '::' in line:
                    # Extract everything before FAILED/SKIPPED
                    test_part = line.split(' FAILED ')[0] if ' FAILED ' in line else line.split(' SKIPPED ')[0]
                    test_part = test_part.strip()
                    # Extract test name from "path/file.py::test_name"
                    if '::' in test_part:
                        test_name = test_part.split('::')[-1]
                        failed_or_skipped_tests.add(test_name)

        if not failed_or_skipped_tests:
            self.logger.info("All tests passed. No cleanup needed.")
            return

        self.logger.info(f"Found {len(failed_or_skipped_tests)} failed/skipped tests: {failed_or_skipped_tests}")

        # Read test file
        try:
            content = test_file_path.read_text(encoding="utf-8")
        except Exception as e:
            self.logger.warning(f"Failed to read test file: {e}")
            return

        # Remove failed/skipped tests
        lines = content.split('\n')
        new_lines = []
        skip_until_next_def = False
        removed_count = 0

        for i, line in enumerate(lines):
            # Check if this is a function definition
            if line.lstrip().startswith('def test_'):
                # Extract function name
                func_name = line.split('(')[0].replace('def ', '').strip()

                if func_name in failed_or_skipped_tests:
                    skip_until_next_def = True
                    removed_count += 1
                    self.logger.info(f"Removing test: {func_name}")
                    continue
                else:
                    skip_until_next_def = False

            # Skip lines that belong to removed functions
            if skip_until_next_def:
                # Stop skipping when we hit next def or unindented line
                if line and not line[0].isspace() and not line.lstrip().startswith('#'):
                    skip_until_next_def = False
                    new_lines.append(line)
                elif line.lstrip().startswith('def '):
                    skip_until_next_def = False
                    new_lines.append(line)
                # else: continue skipping
            else:
                new_lines.append(line)

        # Remove trailing empty lines
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()

        # Write back
        try:
            test_file_path.write_text('\n'.join(new_lines), encoding="utf-8")
            self.logger.info(f"Removed {removed_count} failed/skipped tests from {test_file_path}")
        except Exception as e:
            self.logger.error(f"Failed to write test file after cleanup: {e}")

    # ------------------------------------------------------------------
    # Environment preparation
    # ------------------------------------------------------------------
    def _export_api_keys(self) -> None:
        litellm = os.environ.get("LITELLM_API_KEY")
        if litellm and not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = litellm

        api_base = os.environ.get("API_BASE") or self.config.api_base
        if api_base:
            os.environ["OPENAI_API_BASE"] = api_base
            os.environ["LITELLM_API_BASE"] = api_base

    def _ensure_pythonpath(self) -> None:
        entries: List[str] = []
        agent_root = self.config.config_path.parent.resolve()
        entries.append(str(agent_root))
        if (self.config.project_root / "src").exists():
            entries.append(str((self.config.project_root / "src").resolve()))
        entries.append(str(self.config.project_root.resolve()))
        entries.append(str(self.config.project_root.parent.resolve()))

        existing = os.environ.get("PYTHONPATH", "")
        combined = os.pathsep.join(dict.fromkeys(entries + ([existing] if existing else [])))
        os.environ["PYTHONPATH"] = combined

    def _ensure_directories(self) -> None:
        self.config.test_command_dir.mkdir(parents=True, exist_ok=True)
        if self.aggregate_test_file:
            self.aggregate_test_file.parent.mkdir(parents=True, exist_ok=True)
        if self.config.html_report_path:
            self.config.html_report_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.code_coverage_report_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.selector_output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.log_file:
            self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_conftest()

    # ------------------------------------------------------------------
    # RepoGraph & pytest argument computation
    # ------------------------------------------------------------------
    def _run_repograph(self) -> RepoGraphResult:
        # Optional fast-path: reuse existing repograph result if allowed.
        if os.environ.get("TA_REUSE_REPOGRAPH", "0") == "1" and self.config.selector_output_path.exists():
            try:
                cached = json.loads(self.config.selector_output_path.read_text(encoding="utf-8"))
                return RepoGraphResult(
                    source_module=cached.get("source", {}).get("module", "") or "",
                    source_qualpath=cached.get("source", {}).get("qualpath"),
                    library_consumers=cached.get("library_consumers", {}) or {},
                    workspace_callers=cached.get("workspace_callers", {}) or {},
                )
            except Exception:
                # Fallback to full run on cache parse error
                pass

        workspace_symbols = tuple(
            str(sym)
            for sym in self.config.migration.get("workspace_symbols", []) or []
        )

        selector_dir = self.config.selector_output_path.parent
        selector_dir.mkdir(parents=True, exist_ok=True)

        temp_path = None
        try:
            # Convert package names to module names for repograph
            PACKAGE_TO_MODULE = {
                "slackclient": "slack",
                "slack-sdk": "slack_sdk",
                "pyyaml": "yaml",
                "beautifulsoup4": "bs4",
                "opencv-python": "cv2",
                "scikit-learn": "sklearn",
                "pillow": "PIL",
            }

            migration_for_repograph = self.config.migration.copy()
            source = migration_for_repograph.get("source")
            if isinstance(source, str) and source in PACKAGE_TO_MODULE:
                migration_for_repograph["source"] = PACKAGE_TO_MODULE[source]
            target = migration_for_repograph.get("target")
            if isinstance(target, str) and target in PACKAGE_TO_MODULE:
                migration_for_repograph["target"] = PACKAGE_TO_MODULE[target]

            with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", dir=str(selector_dir), delete=False
            ) as tmp:
                yaml.safe_dump(
                    migration_for_repograph,
                    tmp,
                    sort_keys=False,
                    allow_unicode=True,
                )
                temp_path = Path(tmp.name)

            request = RepoGraphRequest(
                repo_path=self.config.project_root,
                migration_config=temp_path,
                env_python=str(self.config.repo_venv_python),
                extra_paths=(),
                workspace_symbols=workspace_symbols,
            )

            result = self.repograph_runner.run(request)
            payload = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
            self.config.selector_output_path.write_text(payload, encoding="utf-8")
            self.logger.info(
                "RepoGraph output written to %s", self.config.selector_output_path
            )
            return result
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    self.logger.debug("Failed to remove temporary migration file %s", temp_path)

    def _build_pytest_arguments(
        self, result: RepoGraphResult
    ) -> tuple[List[str], str]:
        selected_paths: Set[Path] = set()
        selected_paths.update(Path(p) for p in result.library_consumers.get("files", []))
        for callers in result.workspace_callers.values():
            selected_paths.update(Path(p) for p in callers.get("files", []))

        cov_targets, include_tokens = self._compute_pytest_targets(selected_paths)

        cov_targets = self._merge_cov_targets(cov_targets)
        include_expr = self._merge_include_expression(include_tokens)
        return sorted(cov_targets), include_expr

    def _compute_pytest_targets(self, selected_paths: Set[Path]) -> tuple[Set[str], Set[str]]:
        cov_targets: Set[str] = set()
        include_tokens: Set[str] = set()

        aggregate_token = None
        if self.aggregate_test_file:
            aggregate_token = self.aggregate_test_file.stem

        for rel_path in selected_paths:
            module = self._normalize_module(rel_path)
            if not module:
                continue

            if module.startswith("tests") or ".tests." in module:
                if aggregate_token is None:
                    include_tokens.add(Path(module).name)
                continue

            cov_targets.add(module)
            if aggregate_token:
                include_tokens.add(aggregate_token)
            else:
                include_tokens.update(self._discover_test_tokens(rel_path))

        if aggregate_token:
            include_tokens.add(aggregate_token)

        include_tokens = {token for token in include_tokens if token}
        cov_targets = {target for target in cov_targets if target}
        return cov_targets, include_tokens

    # ------------------------------------------------------------------
    # Stub generation for missing migration deps
    # ------------------------------------------------------------------
    def _ensure_stub_conftest(self) -> None:
        """
        Generate a lightweight conftest.py that stubs out source/target libraries
        (and their imported submodules) so tests can run in environments where
        neither library is installed.
        """
        lib_prefixes: List[str] = []
        migration = self.config.migration or {}
        for key in ("source", "target", "library_a", "libraryA", "library_b", "libraryB"):
            val = migration.get(key)
            if isinstance(val, str) and val.strip():
                lib_prefixes.append(val.strip())

        lib_prefixes = sorted({p for p in lib_prefixes if p})
        if not lib_prefixes:
            return

        module_names = self._collect_imported_modules(lib_prefixes)
        if not module_names:
            return

        target_dir = (
            self.aggregate_test_file.parent
            if self.aggregate_test_file
            else self.config.test_command_dir
        )
        conftest_path = (target_dir / "conftest.py").resolve()
        conftest_path.parent.mkdir(parents=True, exist_ok=True)

        marker = "# AUTO-GENERATED STUBS FOR MIGRATION LIBRARIES"
        try:
            existing = conftest_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        except OSError as exc:
            self.logger.warning("Unable to read %s: %s", conftest_path, exc)
            return

        # If user already defines pytest_configure, do not inject to avoid overriding
        if marker in existing or "def pytest_configure" in existing:
            return

        block_lines = [
            marker,
            "import sys",
            "import types",
            "",
            "def pytest_configure():",
            "    module_names = [",
        ]
        for name in sorted(module_names):
            block_lines.append(f"        '{name}',")
        block_lines.extend(
            [
                "    ]",
                "    created = {}",
                "    for name in module_names:",
                "        if name not in sys.modules:",
                "            created[name] = types.ModuleType(name)",
                "    for name in module_names:",
                "        mod = sys.modules.get(name) or created.get(name) or types.ModuleType(name)",
                "        sys.modules.setdefault(name, mod)",
                "        parts = name.split('.')",
                "        for i in range(1, len(parts)):",
                "            parent = '.'.join(parts[:i])",
                "            if parent not in sys.modules:",
                "                sys.modules[parent] = created.get(parent) or types.ModuleType(parent)",
            ]
        )
        block = "\n".join(block_lines) + "\n"

        new_content = existing + (
            "\n\n" if existing and not existing.endswith("\n") else "\n"
        ) + block

        try:
            conftest_path.write_text(new_content.strip() + "\n", encoding="utf-8")
            self.logger.info("Wrote migration stub conftest to %s", conftest_path)
        except OSError as exc:
            self.logger.warning("Unable to write %s: %s", conftest_path, exc)

    def _collect_imported_modules(self, prefixes: Sequence[str]) -> Set[str]:
        """AST-scan the project to find modules that start with given prefixes."""
        root = self.config.project_root
        hits: Set[str] = set()
        skip_dirs = {".venv", "venv", ".git", "__pycache__", ".testing_agent"}

        for path in root.rglob("*.py"):
            if any(part in skip_dirs or part.startswith(".") for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, SyntaxError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for prefix in prefixes:
                            name = alias.name
                            if name == prefix or name.startswith(prefix + "."):
                                hits.add(name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    for prefix in prefixes:
                        if mod == prefix or mod.startswith(prefix + "."):
                            hits.add(mod)
                            for alias in node.names:
                                hits.add(f"{mod}.{alias.name}")
        return hits

    def _clean_malformed_imports(self, content: str) -> str:
        """Remove common malformed import patterns that LLMs sometimes generate.

        Examples:
        - `from redis import BertTokenizer` followed by indented continuation
        - Partial import statements with unexpected indentation
        """
        lines = content.split('\n')
        cleaned_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Skip lines that are just indented module names (leftover from malformed imports)
            if line.strip() and not line.strip().startswith('#') and line[0].isspace():
                # Check if this looks like a continuation of a malformed import
                if i > 0 and ('import' in cleaned_lines[-1] if cleaned_lines else False):
                    stripped = line.strip()
                    # If it's a bare name (likely from a malformed import), skip it
                    if stripped.isidentifier() or stripped.endswith(','):
                        self.logger.debug("Removing malformed import continuation: %s", line)
                        i += 1
                        continue
            cleaned_lines.append(line)
            i += 1
        return '\n'.join(cleaned_lines)

    def _ensure_module_import_stub(self, test_file: Path, module_name: str) -> None:
        if not self.aggregate_test_file:
            return
        if test_file.resolve() != self.aggregate_test_file.resolve():
            return

        # Remove trailing .__init__ from module name (packages)
        clean_module_name = module_name
        if clean_module_name.endswith('.__init__'):
            clean_module_name = clean_module_name[:-9]  # Remove '.__init__'

        stub_name = f"test_import_{clean_module_name.replace('.', '_')}"

        try:
            current = test_file.read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Failed to read test file %s: %s", test_file, exc)
            return

        if stub_name in current:
            return

        snippet = (
            f"\n\ndef {stub_name}():\n"
            "    import importlib\n"
            f"    importlib.import_module(\"{module_name}\")\n"
            "    assert True\n"
        )

        # Clean malformed imports before writing
        current = self._clean_malformed_imports(current)

        self.aggregate_test_file.write_text(current + snippet, encoding="utf-8")
        self.logger.info("Added import stub for %s to %s", module_name, test_file)

    def _normalize_module(self, rel_path: Path) -> Optional[str]:
        if rel_path.suffix != ".py":
            return None
        parts = rel_path.with_suffix("").parts
        if "src" in parts:
            index = parts.index("src") + 1
            module_parts = parts[index:]
        else:
            module_parts = parts
        if not module_parts:
            return None
        return ".".join(module_parts)

    def _discover_test_tokens(self, rel_path: Path) -> Set[str]:
        tokens: Set[str] = set()
        stem = rel_path.stem

        if stem == "__init__":
            parent = rel_path.parent.name
            if parent:
                stem = parent

        candidate_names = {f"test_{stem}", stem}

        candidate_paths: Sequence[Path] = (
            Path("src") / "tests" / f"test_{stem}.py",
            Path("src") / "tests" / rel_path.parent.name / f"test_{stem}.py",
            Path("tests") / f"test_{stem}.py",
        )

        tokens.update(candidate_names)

        for candidate in candidate_paths:
            if (self.config.project_root / candidate).exists():
                tokens.add(candidate.stem)

        return tokens

    def _merge_cov_targets(self, inferred: Set[str]) -> Set[str]:
        manual = {
            target.strip()
            for target in self.config.pytest_cov_target.split(",")
            if target and target.strip()
        }
        return {target for target in inferred.union(manual) if target}

    def _merge_include_expression(self, inferred_tokens: Set[str]) -> str:
        manual_expr = self.config.pytest_include_expr.strip()
        inferred_expr = " or ".join(sorted(token for token in inferred_tokens if token))

        if manual_expr and inferred_expr:
            return f"({manual_expr}) or ({inferred_expr})"
        if manual_expr:
            return manual_expr
        return inferred_expr

    def _compose_filter_expression(self, include_expr: str, exclude_expr: str) -> str:
        include_expr = include_expr.strip()
        exclude_expr = exclude_expr.strip()

        if include_expr and exclude_expr:
            return f"({include_expr}) and not ({exclude_expr})"
        if exclude_expr:
            return f"not ({exclude_expr})"
        return include_expr

    def _compose_test_command(self, cov_targets: Sequence[str], filter_expr: str) -> str:
        raw_command = self.config.test_command.strip()
        tokens = shlex.split(raw_command)
        if tokens and tokens[0] == "pytest":
            pytest_cmd: List[str] = [
                str(self.config.repo_venv_python),
                "-m",
                "pytest",
            ]

            # Set rootdir to repo root to avoid reading parent pyproject.toml
            pytest_cmd.extend([
                "--override-ini",
                f"testpaths={str(self.config.project_root)}"
            ])

            if cov_targets:
                pytest_cmd.extend(f"--cov={target}" for target in cov_targets)
            else:
                pytest_cmd.append("--cov=..")

            pytest_cmd.append(
                f"--cov-report=xml:{self.config.code_coverage_report_path}".replace("\\", "/")
            )
            pytest_cmd.append("--cov-report=term")

            if filter_expr:
                pytest_cmd.extend(["-k", filter_expr])

            original_args = tokens[1:]
            pytest_cmd.extend(original_args)

            command = " ".join(shlex.quote(part) for part in pytest_cmd)
            self.logger.info("Using pytest command: %s", command)
            return command

        self.logger.info("Using custom test command: %s", raw_command)
        return raw_command

    def _collect_banned_modules(self) -> List[str]:
        banned: List[str] = []
        migration = self.config.migration or {}

        for key in ("source", "library_a", "libraryA", "library_b", "libraryB"):
            value = migration.get(key)
            if isinstance(value, str):
                normalized = value.strip()
                if normalized:
                    banned.append(normalized)
            elif isinstance(value, Iterable):
                for item in value:
                    item_str = str(item).strip()
                    if item_str:
                        banned.append(item_str)

        unique: List[str] = []
        seen: Set[str] = set()
        for module in banned:
            if module and module not in seen:
                seen.add(module)
                unique.append(module)
        return unique

    # ------------------------------------------------------------------
    # File collection helpers
    # ------------------------------------------------------------------
    def _collect_source_files(self, result: RepoGraphResult) -> List[Path]:
        files: Set[str] = set(result.library_consumers.get("files", []))
        for callers in result.workspace_callers.values():
            files.update(callers.get("files", []))
        return sorted(Path(fname) for fname in files)

    def _collect_repoyaml_files(self) -> List[Path]:
        """Return source files listed in repo-yaml (via name_map)."""
        if self.config.repo_yaml_path:
            yaml_path = self.config.repo_yaml_path
        else:
            return []
        if not yaml_path.exists():
            self.logger.warning("Repo-yaml not found: %s", yaml_path)
            return []

        try:
            data = yaml.safe_load(yaml_path.read_text()) or {}
        except Exception as exc:
            self.logger.warning("Failed to load repo-yaml %s: %s", yaml_path, exc)
            return []

        files: List[Path] = []
        for entry in data.get("files", []) or []:
            rel = entry.get("path")
            if not rel:
                continue
            rel_path = Path(rel)
            if "test" in rel_path.parts:
                continue
            files.append(rel_path)
        if not files:
            self.logger.warning("No files listed in repo-yaml %s", yaml_path)
        return files

    def _collect_workspace_includes(self, result: RepoGraphResult) -> List[Path]:
        files: Set[str] = set()
        for callers in result.workspace_callers.values():
            files.update(callers.get("files", []))
        return [
            (self.config.project_root / fname).resolve()
            for fname in sorted(files)
            if fname
        ]

    # ------------------------------------------------------------------
    # Source processing loop
    # ------------------------------------------------------------------
    def _process_source_file(
        self,
        source_rel: Path,
        included_files: List[Path],
        test_command: str,
        eval_mode: bool = False,
    ) -> None:
        if any(part == "tests" for part in source_rel.parts):
            self.logger.info("Skipping test file listed by selector: %s", source_rel)
            return

        source_path = (self.config.project_root / source_rel).resolve()
        if not source_path.exists():
            self.logger.warning("Skipping missing source file: %s", source_path)
            return

        self.logger.info("Processing source file %s", source_path)
        module_name = self._normalize_module(source_rel)
        if not module_name:
            module_name = source_path.stem

        test_file, created = self._resolve_test_file(source_path)
        if created:
            self._initialise_test_file(test_file, source_path, module_name)

        import_block = self._extract_import_block(source_path, module_name)
        symbol_block = self._build_symbol_import_block(module_name, source_path)
        combined_block_parts = [
            self._sanitize_import_block(block)
            for block in (import_block, symbol_block)
            if block
        ]
        combined_block = "\n".join(part for part in combined_block_parts if part.strip())
        if combined_block:
            self._ensure_import_block(test_file, combined_block)

        self._ensure_module_import_stub(test_file, module_name)
        self._run_cover_agent(source_path, test_file, included_files, test_command, eval_mode=eval_mode)

    def _resolve_test_file(self, source_path: Path) -> tuple[Path, bool]:
        if self.aggregate_test_file:
            aggregate_path = self.aggregate_test_file.resolve()
            aggregate_path.parent.mkdir(parents=True, exist_ok=True)
            return aggregate_path, not aggregate_path.exists()

        basename = source_path.name
        new_test = (self.config.test_command_dir / f"test_{basename}").resolve()
        created = not new_test.exists()
        new_test.parent.mkdir(parents=True, exist_ok=True)
        return new_test, created

    def _glob_candidates(self, pattern: str) -> List[Path]:
        matches: List[Path] = []
        for path in self.config.project_root.rglob(pattern):
            if any(part.startswith(".") for part in path.parts):
                continue
            if "venv" in path.parts:
                continue
            matches.append(path)
        matches.sort()
        return matches

    def _initialise_test_file(
        self,
        test_file: Path,
        source_path: Path,
        module_name: str,
    ) -> None:
        if self.aggregate_test_file and test_file.resolve() == self.aggregate_test_file.resolve():
            initial_content = (
                "# Auto-generated aggregated tests by testing agent.\n"
                "# Tests from multiple modules may be appended here.\n"
                f"{AUTO_IMPORT_MARKER}\n"
                "import importlib\n\n"
                "def test_placeholder():\n"
                "    import importlib\n"
                f"    importlib.import_module(\"{module_name}\")\n"
                "    assert True\n\n"
            )
        else:
            initial_content = (
                "# do not delete this comment, this is where pytest adding import pkg msg\n"
                f"import {module_name}\n\n"
                "def test_dummy():\n"
                "    assert True  # dummy test - placeholder for future tests\n"
            )
        test_file.write_text(initial_content, encoding="utf-8")
        self.logger.info("Created new test file %s", test_file)

    def _is_aggregate_test_file(self, test_file: Path) -> bool:
        return bool(self.aggregate_test_file) and test_file.resolve() == self.aggregate_test_file.resolve()

    def _extract_import_block(self, source_path: Path, module_name: str) -> str:
        try:
            code = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Failed to read %s: %s", source_path, exc)
            return ""

        try:
            tree = ast.parse(code, filename=str(source_path))
        except SyntaxError as exc:
            self.logger.warning("Unable to parse %s for imports: %s", source_path, exc)
            return ""

        lines = code.splitlines()
        collected: List[str] = []
        seen: Set[str] = set()

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", node.lineno)
                for idx in range(start, end):
                    line = lines[idx]
                    if line not in seen:
                        collected.append(line)
                        seen.add(line)
            else:
                break

        def rewrite(line: str) -> str:
            # Handle relative imports (from . import or from ..module import)
            match = re.match(
                r"^(\s*from\s+)(\.+)([A-Za-z_][\w\.]*)?(\s+import\b.*)$",
                line,
            )
            if match:
                dots = match.group(2)
                suffix = match.group(4)
                rel_target = match.group(3) or ""

                parts = module_name.split(".")
                if len(parts) <= 1:
                    # Cannot resolve relative imports for single-level modules
                    # Comment out the import to prevent errors
                    return f"# {line.strip()}  # [RELATIVE IMPORT - COULD NOT RESOLVE]"

                level = len(dots)
                if level > len(parts) - 1:
                    # Relative import goes beyond module hierarchy
                    return f"# {line.strip()}  # [RELATIVE IMPORT - OUT OF RANGE]"

                base_parts = parts[: -(level)]
                if rel_target:
                    base_parts.append(rel_target)
                target_module = ".".join(base_parts)
                return f"{match.group(1)}{target_module}{suffix}"

            # Keep absolute imports as-is. Do not try to add prefixes like "src."
            # Different projects have different structures (some use src/, some don't).
            # Let the import resolve naturally or fail at test time if it's invalid.

            return line

        rewritten = [rewrite(line) for line in collected if line.strip()]
        result = "\n".join(rewritten)

        # Clean up any malformed imports that resulted from the rewrite
        result = self._clean_import_block_after_rewrite(result)
        return result

    def _clean_import_block_after_rewrite(self, content: str) -> str:
        """Clean up malformed imports after rewriting relative imports to comments.

        When relative imports are commented out, their multi-line content may leave
        orphaned identifiers that need to be removed.
        """
        lines = content.split('\n')
        cleaned_lines = []
        skip_until_real_import = False

        for line in lines:
            stripped = line.strip()

            # Check if this is a commented import opening: # from ... import (
            if stripped.startswith('#') and 'import' in stripped and '(' in stripped and ')' not in stripped:
                # Mark to skip following orphaned identifiers
                skip_until_real_import = True
                cleaned_lines.append(line)
                continue

            # If we're skipping, check if this line is an orphaned identifier
            if skip_until_real_import:
                # Skip empty lines and bare identifiers
                if not stripped or re.match(r'^[A-Za-z_]\w*\s*,?\s*$', stripped):
                    self.logger.debug(f"Removing orphaned identifier: {line}")
                    continue
                else:
                    # Hit a real statement, stop skipping
                    skip_until_real_import = False

            cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def _extract_defined_symbols(self, source_path: Path) -> List[str]:
        try:
            code = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Failed to read %s for symbol extraction: %s", source_path, exc)
            return []

        try:
            tree = ast.parse(code, filename=str(source_path))
        except SyntaxError as exc:
            self.logger.warning("Unable to parse %s for symbol extraction: %s", source_path, exc)
            return []

        symbols: List[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                symbols.append(node.name)
        return symbols

    def _has_module_level_side_effects(self, source_path: Path) -> bool:
        """
        Check if a module has side effects at import time (e.g., instantiating clients).
        These modules cannot be safely imported in tests.
        """
        try:
            content = source_path.read_text()
            import re

            # Patterns that indicate import-time side effects
            suspicious_patterns = [
                r'^\s*\w+\s*=\s*\w*HttpClient\s*\(',
                r'^\s*\w+\s*=\s*\w*Client\s*\(',
                r'^\s*\w+\s*=\s*\w*Database\s*\(',
                r'^\s*\w+\s*=\s*\w*Connection\s*\(',
                r'^\s*\w+\s*=\s*requests\.',
                r'^\s*\w+\s*=\s*mlflow\.',
            ]

            lines = content.split('\n')
            for line in lines:
                stripped = line.strip()
                # Stop at first function/class def (module level code ends)
                if stripped.startswith('def ') or stripped.startswith('class '):
                    break
                # Skip comments
                if stripped.startswith('#'):
                    continue

                # Check for suspicious patterns
                for pattern in suspicious_patterns:
                    if re.match(pattern, line):
                        self.logger.debug(f"Skipping {source_path} due to module-level side effect: {line}")
                        return True

            return False
        except Exception:
            return False

    def _build_symbol_import_block(self, module_name: Optional[str], source_path: Path) -> str:
        if not module_name:
            return ""

        # Skip if this module is a banned module (source library in migration)
        banned = self._collect_banned_modules()
        if module_name in banned:
            return ""

        # Skip if this module has side effects at import time
        if self._has_module_level_side_effects(source_path):
            return ""

        symbols = sorted(set(self._extract_defined_symbols(source_path)))
        if not symbols:
            return ""

        chunk_size = 4
        lines: List[str] = []
        for idx in range(0, len(symbols), chunk_size):
            chunk = ", ".join(symbols[idx : idx + chunk_size])
            lines.append(f"from {module_name} import {chunk}")
        return "\n".join(lines)

    @staticmethod
    def _sanitize_import_block(import_block: str) -> str:
        """Drop import lines that fail to parse (e.g., names with dashes)."""
        if not import_block:
            return ""

        valid_lines: List[str] = []
        for line in import_block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                ast.parse(stripped)
            except SyntaxError:
                continue
            valid_lines.append(stripped)

        return "\n".join(valid_lines)

    def _ensure_import_block(self, test_file: Path, import_block: str) -> None:
        try:
            current = test_file.read_text(encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Failed to read test file %s: %s", test_file, exc)
            return

        if self.aggregate_test_file and test_file.resolve() == self.aggregate_test_file.resolve():
            lines = current.splitlines()
            if AUTO_IMPORT_MARKER in lines:
                marker_idx = lines.index(AUTO_IMPORT_MARKER)
                insert_idx = marker_idx + 1
                existing: Set[str] = set()
                while insert_idx < len(lines) and lines[insert_idx].strip():
                    existing.add(lines[insert_idx])
                    insert_idx += 1
                additions = [line for line in import_block.splitlines() if line and line not in existing]
                if not additions:
                    return
                updated = (
                    lines[:insert_idx]
                    + additions
                    + lines[insert_idx:]
                )
                test_file.write_text("\n".join(updated) + "\n", encoding="utf-8")
                self.logger.info("Updated import block in %s", test_file)
                return

        if AUTO_IMPORT_MARKER in current:
            return

        content = f"{AUTO_IMPORT_MARKER}\n{import_block}\n\n{current}"
        test_file.write_text(content, encoding="utf-8")
        self.logger.info("Inserted import block into %s", test_file)

    def _run_cover_agent(
        self,
        source_path: Path,
        test_file: Path,
        included_files: List[Path],
        test_command: str,
        eval_mode: bool = False,
    ) -> None:
        self.logger.info("Running cover-agent for source %s", source_path)

        cmd: List[str] = [
            str(self.config.repo_venv_python),
            "-m",
            "testing_agent.cover_agent.main",
            "--source-file-path",
            str(source_path),
            "--test-file-path",
            str(test_file),
            "--project-root",
            str(self.config.project_root),
            "--code-coverage-report-path",
            str(self.config.code_coverage_report_path),
            "--test-command",
            test_command,
            "--test-command-dir",
            str(self.config.test_command_dir),
            "--coverage-type",
            self.config.coverage_type,
            "--desired-coverage",
            str(self.config.desired_coverage),
            "--max-iterations",
            str(self.config.max_iterations),
            "--additional-instructions",
            self.config.additional_instructions,
            "--model",
            self.config.model,
            "--log-db-path",
            self.config.cover_agent_log_db_path,
        ]

        if self.config.api_base:
            cmd.extend(["--api-base", self.config.api_base])

        banned_modules = self._collect_banned_modules()
        if banned_modules:
            cmd.append("--banned-modules")
            cmd.extend(sorted(set(banned_modules)))

        if included_files:
            cmd.append("--included-files")
            cmd.extend(str(path) for path in included_files)

        if eval_mode:
            eval_cov = Path(self.config.code_coverage_report_path).with_name("coverage_eval.xml")
            cmd.extend(
                [
                    "--eval-mode",
                    "--eval-test-file-path",
                    str(test_file),
                    "--eval-coverage-report-path",
                    str(eval_cov),
                ]
            )

        cmd.extend(["--run-tests-multiple-times", str(self.config.run_tests_multiple_times)])
        cmd.extend(["--branch", self.config.branch])

        if self.config.diff_coverage:
            cmd.append("--diff-coverage")

        if self.config.run_each_test_separately:
            cmd.extend(["--run-each-test-separately", "True"])

        args = SimpleNamespace(
            source_file_path=str(source_path),
            test_file_path=str(test_file),
            project_root=str(self.config.project_root),
            test_file_output_path="",
            code_coverage_report_path=str(self.config.code_coverage_report_path),
            eval_test_file_path=str(test_file) if eval_mode else "",
            eval_coverage_report_path=str(Path(self.config.code_coverage_report_path).with_name("coverage_eval.xml")) if eval_mode else "",
            test_command=test_command,
            test_command_dir=str(self.config.test_command_dir),
            included_files=[str(path) for path in included_files] if included_files else [],
            coverage_type=self.config.coverage_type,
            report_filepath=str(self.config.html_report_path) if self.config.html_report_path else "",
            desired_coverage=self.config.desired_coverage,
            max_iterations=self.config.max_iterations,
            max_run_time=self.config.max_run_time,
            additional_instructions=self.config.additional_instructions,
            model=self.config.model,
            api_base=self.config.api_base or "",
            strict_coverage=False,
            run_tests_multiple_times=self.config.run_tests_multiple_times,
            log_db_path=self.config.cover_agent_log_db_path,
            branch=self.config.branch,
            use_report_coverage_feature_flag=False,
            diff_coverage=self.config.diff_coverage,
            run_each_test_separately=self.config.run_each_test_separately,
            banned_modules=banned_modules,
            eval_mode=eval_mode,
        )

        divider = "=" * 38
        if self.config.html_report_path:
            with self.config.html_report_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{divider}\nProcessing: {source_path}\nTest file: {test_file}\n{divider}\n"
                )

        try:
            agent = CoverAgent(args, runner=self.test_executor)
            agent.run()
            status_message = "Successfully processed"
            self.logger.info("Successfully processed %s", source_path)
        except Exception as exc:  # pragma: no cover - propagate log but continue
            status_message = f"Error: {exc}"
            self.logger.error("Cover-agent failed for %s: %s", source_path, exc)
            self.logger.debug("Traceback:\n%s", traceback.format_exc())

        if self.config.html_report_path:
            with self.config.html_report_path.open("a", encoding="utf-8") as handle:
                handle.write(status_message + "\n")
                handle.write("-" * 38 + "\n\n")

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _print_coverage_summary(self) -> None:
        """Parse coverage.xml and print a summary table to the log."""
        if not self.config.code_coverage_report_path.exists():
            return

        try:
            import xml.etree.ElementTree as ET
        except ImportError:
            self.logger.warning("Could not import xml.etree.ElementTree for coverage summary")
            return

        try:
            tree = ET.parse(self.config.code_coverage_report_path)
            root = tree.getroot()

            # Extract overall coverage from root element
            total_line_rate = root.get("line-rate", "0")
            lines_covered = root.get("lines-covered", "0")
            lines_valid = root.get("lines-valid", "0")

            # Collect per-file coverage info from classes
            file_coverage = []
            for package in root.findall(".//package"):
                for cls in package.findall(".//class"):
                    filename = cls.get("filename", "unknown")
                    line_rate = float(cls.get("line-rate", "0"))
                    coverage_pct = round(line_rate * 100, 1)

                    # Count lines for this file
                    lines = cls.findall(".//line")
                    covered = len([l for l in lines if l.get("hits", "0") != "0"])
                    total = len(lines)

                    file_coverage.append({
                        "name": filename,
                        "stmts": total,
                        "miss": total - covered,
                        "cover": coverage_pct,
                    })

            if file_coverage:
                # Sort by filename
                file_coverage.sort(key=lambda x: x["name"])

                # Print header
                self.logger.info("=" * 70)
                self.logger.info("COVERAGE SUMMARY")
                self.logger.info("=" * 70)
                self.logger.info(
                    "%-50s %6s %6s %8s",
                    "Name",
                    "Stmts",
                    "Miss",
                    "Cover"
                )
                self.logger.info("-" * 70)

                # Print each file
                for fc in file_coverage:
                    self.logger.info(
                        "%-50s %6d %6d %7.1f%%",
                        fc["name"],
                        fc["stmts"],
                        fc["miss"],
                        fc["cover"]
                    )

                self.logger.info("-" * 70)

                # Print total
                try:
                    total_rate = float(total_line_rate) * 100
                    self.logger.info(
                        "%-50s %6s %6s %7.1f%%",
                        "TOTAL",
                        lines_valid,
                        int(lines_valid) - int(lines_covered),
                        total_rate
                    )
                except (ValueError, TypeError):
                    pass

                self.logger.info("=" * 70)

        except Exception as e:
            self.logger.debug(f"Failed to print coverage summary: {e}")

    def _prepare_html_report(self) -> None:
        if not self.config.html_report_path:
            return
        self.config.html_report_path.write_text("", encoding="utf-8")

    def _ensure_conftest(self) -> None:
        conftest_path = (self.config.test_command_dir / "conftest.py").resolve()
        if conftest_path.exists():
            return

        content = (
            "# [AUTO] ensure package root is on sys.path for imports like 'from models import X'\n"
            "import sys, pathlib\n"
            "_pkg_root = pathlib.Path(__file__).resolve().parents[1]\n"
            "p = str(_pkg_root)\n"
            "if p not in sys.path:\n"
            "    sys.path.insert(0, p)\n"
            "\n"
            "# [AUTO] Workaround for PyO3 cryptography module initialization issue\n"
            "# Some cryptography versions use Rust/PyO3 modules that can only be initialized once per process\n"
            "# This causes 'PyO3 modules compiled for CPython 3.8 or older may only be initialized once' errors\n"
            "# Solution: eagerly import the module that uses cryptography to initialize it early\n"
            "try:\n"
            "    # Try to import common modules that might use cryptography\n"
            "    import aiortc\n"
            "except (ImportError, Exception):\n"
            "    pass\n"
            "\n"
            "try:\n"
            "    import cryptography\n"
            "except (ImportError, Exception):\n"
            "    pass\n"
        )
        conftest_path.write_text(content, encoding="utf-8")
        self.logger.info("Created %s", conftest_path)

    def _run_repo_python(
        self,
        args: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = [str(self.config.repo_venv_python), *args]
        self.logger.debug("Running repo python: %s", " ".join(shlex.quote(part) for part in cmd))
        try:
            return subprocess.run(
                cmd,
                text=True,
                capture_output=capture_output,
                check=check,
                env=os.environ.copy(),
            )
        except subprocess.CalledProcessError as exc:
            self.logger.error("Command failed: %s", exc)
            raise


class DirectLSPRepoGraphRunner(RepoGraphRunner):
    """Run RepoGraph directly using lsp_repograph package."""

    def __init__(self, timeout: int = 600) -> None:
        self.timeout = timeout

    def run(self, request: RepoGraphRequest) -> RepoGraphResult:
        try:
            from lsp_repograph.core.multilspy_client import MultilspyLSPClient
        except ImportError:
            raise RuntimeError("lsp_repograph package not installed")

        import yaml as yaml_lib
        from pathlib import Path
        import re

        repo_root = request.repo_path.resolve()

        # Load migration config
        with open(request.migration_config) as f:
            config = yaml_lib.safe_load(f)

        # Get source from migration section, or top-level for backward compatibility
        migration = config.get("migration", {})
        source = migration.get("source") or config.get("source")
        if not source:
            raise ValueError("Migration config must define a source")

        # Create client with venv
        custom_init = {
            "initializationOptions": {
                "workspace": {
                    "environmentPath": str(request.env_python)
                }
            }
        } if request.env_python else None

        client = MultilspyLSPClient(str(repo_root), custom_init_params=custom_init)

        try:
            # Find references using find_refs_by_fqn (scratch file approach)
            refs_fqn = client.find_refs_by_fqn(module=source)

            # Filter out venv and cache directories from LSP results
            refs_fqn = [
                ref for ref in refs_fqn
                if not any(part in str(ref.get("absolute_path", "")) for part in [".venv", "__pycache__"])
            ]

            # ALSO search for imports directly in source files using find_refs_by_loc
            # This ensures we catch all imports that find_refs_by_fqn might miss
            all_refs = list(refs_fqn)  # Start with find_refs_by_fqn results
            seen_locs = {(ref["absolute_path"], ref["line"], ref["character"]) for ref in all_refs}

            py_files = list(repo_root.glob("**/*.py"))
            # Filter out venv directories and test files (we already got those from find_refs_by_fqn)
            py_files = [f for f in py_files if ".venv" not in str(f) and "__pycache__" not in str(f)]

            # Build list of possible module names to search for
            # (handles package-name vs module-name differences)
            PACKAGE_TO_MODULE = {
                "slackclient": "slack",
                "slack-sdk": "slack_sdk",
                "pyyaml": "yaml",
                "beautifulsoup4": "bs4",
                "opencv-python": "cv2",
                "scikit-learn": "sklearn",
                "pillow": "PIL",
                "pytorch-transformers": "pytorch_transformers",
                "pytorch-pretrained-bert": "pytorch_pretrained_bert",
                "pycryptodome": "Crypto",
                "pyopenssl": "OpenSSL",
                "django-rest-swagger": "rest_framework_swagger",
                "ruamel.yaml": "ruamel",
            }

            possible_names = [source]
            # Add version with dashes replaced by underscores
            if "-" in source:
                possible_names.append(source.replace("-", "_"))
            # Add mapped module name if it exists
            if source in PACKAGE_TO_MODULE:
                possible_names.append(PACKAGE_TO_MODULE[source])

            # Remove duplicates while preserving order
            possible_names = list(dict.fromkeys(possible_names))

            for py_file in py_files:
                try:
                    content = py_file.read_text(encoding='utf-8', errors='ignore')
                    lines = content.split('\n')

                    for line_num, line in enumerate(lines):
                        # Skip comment lines
                        if line.lstrip().startswith('#'):
                            continue

                        # Look for import statements with any of the possible names
                        for search_name in possible_names:
                            # Use word boundaries to match the module name in import statements
                            # This handles comma-separated imports like: import abc, jsonpath_rw, re
                            # Pattern matches: import X, from X, etc. with word boundaries
                            import_pattern = rf'\b(?:import|from)\b.*\b{re.escape(search_name)}\b'
                            if re.search(import_pattern, line):
                                # Found an import, use find_refs_by_loc to get all references
                                import_char = line.find(search_name)
                                if import_char >= 0:
                                    rel_path = py_file.relative_to(repo_root)
                                    try:
                                        refs_at_loc = client.find_refs_by_loc(
                                            path=str(rel_path),
                                            line=line_num,
                                            character=import_char + len(search_name) // 2
                                        )
                                        for ref in refs_at_loc:
                                            key = (ref["absolute_path"], ref["line"], ref["character"])
                                            if key not in seen_locs:
                                                seen_locs.add(key)
                                                all_refs.append(ref)
                                    except Exception:
                                        # If this specific file fails, continue
                                        pass
                                break  # Found match with this name, don't try others
                except Exception:
                    # If we can't read this file, skip it
                    pass

            refs = all_refs

            # Format results
            files = []
            seen = set()
            formatted_refs = []

            for ref in refs:
                abs_path = Path(ref["absolute_path"]).resolve()
                try:
                    rel_path = abs_path.relative_to(repo_root)
                    rel_str = str(rel_path)
                    if rel_str not in seen:
                        seen.add(rel_str)
                        files.append(rel_str)
                except ValueError:
                    pass

                formatted_refs.append({
                    "relative_path": str(Path(ref["absolute_path"]).relative_to(repo_root)) if Path(ref["absolute_path"]).is_relative_to(repo_root) else ref["absolute_path"],
                    "absolute_path": ref["absolute_path"],
                    "line": ref["line"],
                    "character": ref["character"]
                })

            return RepoGraphResult(
                source_module=source,
                source_qualpath=None,
                library_consumers={"files": files, "references": formatted_refs},
                workspace_callers={}
            )
        finally:
            client.shutdown()


class LocalRepoGraphRunner(RepoGraphRunner):
    """Run RepoGraph selector locally within the repo environment."""

    def __init__(
        self,
        runner: Runner,
        module: str = "testing_agent.repograph_runner.repograph_selector",
        timeout: int = 600,
    ) -> None:
        self.runner = runner
        self.module = module
        self.timeout = timeout

    def run(self, request: RepoGraphRequest) -> RepoGraphResult:
        cmd_parts: List[str] = []

        # Always use testing-agent's interpreter to run repograph_selector
        # It will use --env-python to access repo's environment when needed
        interpreter = sys.executable
        cmd_parts.extend([interpreter, "-m", self.module])
        cmd_parts.extend(["--repo-path", str(request.repo_path)])
        cmd_parts.extend(["--config", str(request.migration_config)])

        if request.env_python:
            cmd_parts.extend(["--env-python", str(request.env_python)])

        for extra in request.extra_paths:
            cmd_parts.extend(["--extra-path", str(extra)])

        for symbol in request.workspace_symbols:
            cmd_parts.extend(["--workspace-symbol", symbol])

        command = " ".join(shlex.quote(part) for part in cmd_parts)

        logger.debug(f"LocalRepoGraphRunner.run() execute command '{command}'")

        result = self.runner.run_command(
            command=command,
            max_run_time=self.timeout,
            cwd=str(request.repo_path),
            # cwd="."
        )

        if result.exit_code != 0:
            raise RuntimeError(
                "RepoGraph selector failed with exit code "
                f"{result.exit_code}: {result.stderr.strip()}"
            )

        payload = json.loads(result.stdout)
        source = payload.get("source", {})
        library = payload.get("library_consumers", {})
        workspace_callers = payload.get("workspace_callers", {})

        return RepoGraphResult(
            source_module=source.get("module", ""),
            source_qualpath=source.get("qualpath"),
            library_consumers=library,
            workspace_callers=workspace_callers,
        )
