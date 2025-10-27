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
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, List, Optional, Sequence, Set

import yaml

from cover_agent.CoverAgent import CoverAgent
from cover_agent.Runner import LocalRunner, Runner
from repograph_runner.repograph_selector import (
    RepoGraphRequest,
    RepoGraphResult,
    RepoGraphRunner,
)

from testing_agent.config_loader import TestingAgentConfig


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
            self.repograph_runner = LocalRepoGraphRunner(
                runner=self.test_executor,
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
        self._install_dependencies()

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

        if self.config.html_report_path:
            self.logger.info(
                "All cover-agent tasks completed. HTML report saved to %s",
                self.config.html_report_path,
            )
        else:
            self.logger.info("All cover-agent tasks completed. HTML report generation disabled.")

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

    def _install_dependencies(self) -> None:
        pip_timeout = max(self.config.max_run_time, 300)

        def run_pip(args: Sequence[str], description: str) -> None:
            command = shlex.join(
                [str(self.config.repo_venv_python), "-m", "pip", *args]
            )
            self.logger.info("%s", description)
            result = self.test_executor.run_command(
                command=command,
                max_run_time=pip_timeout,
                cwd=str(self.config.project_root),
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"{description} failed with exit code {result.exit_code}: {result.stderr.strip()}"
                )

        try:
            run_pip(["install", "-U", "pip", "wheel", "setuptools"], "Upgrading pip tooling")
        except RuntimeError as exc:
            self.logger.warning(str(exc))

        if self.config.repo_requirements_file and self.config.repo_requirements_file.exists():
            repo_args: List[str] = ["install", "--no-cache-dir"]
            if self.config.install_repo_deps_without_deps:
                repo_args.append("--no-deps")
            repo_args.extend(["-r", str(self.config.repo_requirements_file)])
            run_pip(
                repo_args,
                f"Installing repo requirements from {self.config.repo_requirements_file}",
            )

        if self.config.test_requirements_file and self.config.test_requirements_file.exists():
            test_args: List[str] = [
                "install",
                "--no-cache-dir",
                "-r",
                str(self.config.test_requirements_file),
            ]
            run_pip(
                test_args,
                f"Installing test requirements from {self.config.test_requirements_file}",
            )

    # ------------------------------------------------------------------
    # RepoGraph & pytest argument computation
    # ------------------------------------------------------------------
    def _run_repograph(self) -> RepoGraphResult:
        workspace_symbols = tuple(
            str(sym)
            for sym in self.config.migration.get("workspace_symbols", []) or []
        )

        selector_dir = self.config.selector_output_path.parent
        selector_dir.mkdir(parents=True, exist_ok=True)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".yaml", dir=str(selector_dir), delete=False
            ) as tmp:
                yaml.safe_dump(
                    self.config.migration,
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

    def _ensure_module_import_stub(self, test_file: Path, module_name: str) -> None:
        if not self.aggregate_test_file:
            return
        if test_file.resolve() != self.aggregate_test_file.resolve():
            return

        stub_name = f"test_import_{module_name.replace('.', '_')}"

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

    # ------------------------------------------------------------------
    # File collection helpers
    # ------------------------------------------------------------------
    def _collect_source_files(self, result: RepoGraphResult) -> List[Path]:
        files: Set[str] = set(result.library_consumers.get("files", []))
        for callers in result.workspace_callers.values():
            files.update(callers.get("files", []))
        return sorted(Path(fname) for fname in files)

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
    ) -> None:
        if source_rel.parts and source_rel.parts[0] == "tests":
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

        import_block = self._extract_import_block(source_path)
        if import_block:
            self._ensure_import_block(test_file, import_block)

        self._ensure_module_import_stub(test_file, module_name)
        self._run_cover_agent(source_path, test_file, included_files, test_command)

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

    def _extract_import_block(self, source_path: Path) -> str:
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
            match = re.match(
                r"^(\s*from\s+)(\.+)([A-Za-z_][\w\.]*)(\s+import\b.*)$",
                line,
            )
            if match:
                return f"{match.group(1)}{self.package_name}.{match.group(3)}{match.group(4)}"
            return line

        rewritten = [rewrite(line) for line in collected if line.strip()]
        return "\n".join(rewritten)

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
                    lines[: marker_idx + 1]
                    + additions
                    + lines[marker_idx + 1 :]
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
    ) -> None:
        self.logger.info("Running cover-agent for source %s", source_path)

        cmd: List[str] = [
            str(self.config.repo_venv_python),
            "-m",
            "cover_agent.main",
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
        ]

        if self.config.api_base:
            cmd.extend(["--api-base", self.config.api_base])

        if included_files:
            cmd.append("--included-files")
            cmd.extend(str(path) for path in included_files)

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
            log_db_path="",
            branch=self.config.branch,
            use_report_coverage_feature_flag=False,
            diff_coverage=self.config.diff_coverage,
            run_each_test_separately=self.config.run_each_test_separately,
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


class LocalRepoGraphRunner(RepoGraphRunner):
    """Run RepoGraph selector locally within the repo environment."""

    def __init__(
        self,
        runner: Runner,
        module: str = "repograph_runner.repograph_selector",
        timeout: int = 600,
    ) -> None:
        self.runner = runner
        self.module = module
        self.timeout = timeout

    def run(self, request: RepoGraphRequest) -> RepoGraphResult:
        cmd_parts: List[str] = []

        interpreter = str(request.env_python) if request.env_python else "python"
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
        result = self.runner.run_command(
            command=command,
            max_run_time=self.timeout,
            cwd=str(request.repo_path),
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
