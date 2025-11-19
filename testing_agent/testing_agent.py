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
            self.repograph_runner = LocalRepoGraphRunner(
                runner=LocalRunner([], {}),
                timeout=self.config.max_run_time,
                docker_image=getattr(config, 'docker_image', None),
                repo_path=config.project_root,
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
            "    import pytest\n"
            "    try:\n"
            f"        importlib.import_module(\"{module_name}\")\n"
            "    except Exception as exc:\n"
            "        pytest.skip(f\"Skipping import for module with side effects: {exc}\")\n"
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
        if tokens and ("pytest" in tokens or (len(tokens) >= 3 and tokens[0] == "python" and tokens[1] == "-m" and tokens[2] == "pytest")):
            # Determine coverage path inside container if repo is mounted at /workspace
            cov_path = self.config.code_coverage_report_path
            try:
                rel = self.config.code_coverage_report_path.relative_to(self.config.project_root)
                cov_path = str(Path("/workspace") / rel)
            except Exception:
                cov_path = str(self.config.code_coverage_report_path)

            # If command already specifies pytest, just append coverage flags if missing
            if not any(tok.startswith("--cov") for tok in tokens):
                if cov_targets:
                    tokens.extend(f"--cov={target}" for target in cov_targets)
                else:
                    tokens.append("--cov=..")
            if not any(tok.startswith("--cov-report=") for tok in tokens):
                tokens.append(f"--cov-report=xml:{cov_path}".replace("\\", "/"))
                tokens.append("--cov-report=term")
            if filter_expr and "-k" not in tokens:
                tokens.extend(["-k", filter_expr])

            command = " ".join(shlex.quote(part) for part in tokens)
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

        has_side_effects = self._has_import_side_effects(source_path)
        if has_side_effects:
            self.logger.info("Detected potential import-time side effects in %s; guarding imports", source_path)

        import_block = self._extract_import_block(source_path, module_name)
        symbol_block = self._build_symbol_import_block(module_name, source_path)
        combined_block_parts = [block for block in (import_block, symbol_block) if block]
        combined_block = "\n".join(part for part in combined_block_parts if part.strip())
        if has_side_effects and combined_block:
            combined_block = self._wrap_import_block_with_skip(combined_block, module_name)
        if combined_block:
            self._ensure_import_block(test_file, combined_block)

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
                "import importlib\n"
                "import pytest\n\n"
                "def test_placeholder():\n"
                "    try:\n"
                f"        importlib.import_module(\"{module_name}\")\n"
                "    except Exception as exc:\n"
                "        pytest.skip(f\"Skipping placeholder import due to side effects: {exc}\")\n"
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
            match = re.match(
                r"^(\s*from\s+)(\.+)([A-Za-z_][\w\.]*)?(\s+import\b.*)$",
                line,
            )
            if not match:
                return line

            dots = match.group(2)
            suffix = match.group(4)
            rel_target = match.group(3) or ""

            parts = module_name.split(".")
            if len(parts) <= 1:
                return line

            level = len(dots)
            if level > len(parts) - 1:
                return line

            base_parts = parts[: -(level)]
            if rel_target:
                base_parts.append(rel_target)
            target_module = ".".join(base_parts)
            return f"{match.group(1)}{target_module}{suffix}"

        rewritten = [rewrite(line) for line in collected if line.strip()]
        return "\n".join(rewritten)

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

    def _build_symbol_import_block(self, module_name: Optional[str], source_path: Path) -> str:
        if not module_name:
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

    def _has_import_side_effects(self, source_path: Path) -> bool:
        """Detect likely import-time side effects based on simple AST heuristics."""
        try:
            code = source_path.read_text(encoding="utf-8")
        except OSError:
            return False

        try:
            tree = ast.parse(code, filename=str(source_path))
        except SyntaxError:
            return False

        dangerous_names = {"MlflowHttpClient", "HttpClient", "boto3", "requests", "subprocess", "os.system"}
        for node in tree.body:
            # direct expression calls or assigned calls at module level
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                return True
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                return True
            # from/import of known risky symbols
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in dangerous_names:
                        return True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in dangerous_names:
                        return True
        return False

    def _wrap_import_block_with_skip(self, import_block: str, module_name: str) -> str:
        """Convert import lines into top-level guarded stubs to avoid import-time side effects."""
        if not import_block.strip():
            return import_block

        def _parse_symbols_from_from(line: str) -> tuple[str, List[str]]:
            # line format: from foo.bar import a, b as c
            _, rest = line.split("from ", 1)
            module_part, symbols_part = rest.split(" import ", 1)
            module_part = module_part.strip()
            symbols: List[str] = []
            for raw in symbols_part.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                if " as " in raw:
                    raw = raw.split(" as ", 1)[1]
                symbols.append(raw.split(".")[-1])
            return module_part, symbols

        def _parse_symbols_from_import(line: str) -> List[str]:
            # line format: import a, b as c
            _, rest = line.split("import ", 1)
            names: List[str] = []
            for raw in rest.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                if " as " in raw:
                    raw = raw.split(" as ", 1)[1]
                names.append(raw.split(".")[-1])
            return names

        blocks: List[str] = []
        for line in import_block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            blocks.append("import pytest")
            if stripped.startswith("from "):
                module_part, symbols = _parse_symbols_from_from(stripped)
                blocks.append("try:")
                blocks.append(f"    {stripped}")
                blocks.append("except Exception:")
                if symbols:
                    for sym in symbols:
                        blocks.append(f"    {sym} = None")
                else:
                    blocks.append("    pass")
            elif stripped.startswith("import "):
                symbols = _parse_symbols_from_import(stripped)
                blocks.append("try:")
                blocks.append(f"    {stripped}")
                blocks.append("except Exception:")
                if symbols:
                    for sym in symbols:
                        blocks.append(f"    {sym} = None")
                else:
                    blocks.append("    pass")
            else:
                # Fallback: leave as-is but still guard
                blocks.append("try:")
                blocks.append(f"    {stripped}")
                blocks.append("except Exception:")
                blocks.append("    pass")
            blocks.append("")  # blank line between stubs

        return "\n".join(blocks).rstrip() + "\n"

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
            log_db_path=self.config.cover_agent_log_db_path,
            branch=self.config.branch,
            use_report_coverage_feature_flag=False,
            diff_coverage=self.config.diff_coverage,
            run_each_test_separately=self.config.run_each_test_separately,
            banned_modules=banned_modules,
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
        module: str = "testing_agent.repograph_runner.repograph_selector",
        timeout: int = 600,
        docker_image: Optional[str] = None,
        repo_path: Optional[Path] = None,
    ) -> None:
        self.runner = runner
        self.module = module
        self.timeout = timeout
        self.docker_image = docker_image
        self.repo_path = repo_path

    def run(self, request: RepoGraphRequest) -> RepoGraphResult:
        cmd_parts: List[str] = []

        if self.docker_image:
            # Run repograph in Docker container with repo environment
            # Mount the repograph_selector.py script into the container
            selector_script = Path(__file__).parent / "repograph_runner" / "repograph_selector.py"

            cmd_parts.extend([
                "sudo", "docker", "run", "--rm",
                "-v", f"{request.repo_path}:/workspace",
                "-v", f"{selector_script}:/tmp/repograph_selector.py:ro",
                "-w", "/workspace",
                self.docker_image,
                "python3.11", "/tmp/repograph_selector.py"
            ])
            repo_path_arg = "/workspace"
            config_path_arg = str(request.migration_config)
            # If config is inside repo, use container path
            if request.migration_config.is_relative_to(request.repo_path):
                rel_config = request.migration_config.relative_to(request.repo_path)
                config_path_arg = f"/workspace/{rel_config}"
        else:
            # Fallback: run on host (original behavior)
            interpreter = sys.executable
            cmd_parts.extend([interpreter, "-m", self.module])
            repo_path_arg = str(request.repo_path)
            config_path_arg = str(request.migration_config)

        cmd_parts.extend(["--repo-path", repo_path_arg])
        cmd_parts.extend(["--config", config_path_arg])

        # Only pass --env-python when running on host (not in Docker container)
        # Inside the container, the Python environment is already correctly configured
        if request.env_python and not self.docker_image:
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
