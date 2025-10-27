"""Load testing-agent configuration from YAML files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from shutil import which
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import warnings

import yaml
import sys


def _as_path(candidate: str | Path, base: Path) -> Path:
    path = Path(candidate)
    if not path.is_absolute():
        path = (base / path).resolve()
    return path


def _first_existing_path(candidates: Iterable[str | Path], base: Path) -> Optional[Path]:
    for candidate in candidates:
        path = _as_path(candidate, base)
        if path.exists():
            return path
    return None


def _expand_repo_placeholder(value: str | Path | None, repo_name: str) -> str | Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        value = str(value)
    return value.replace("${repo_name}", repo_name)


def _first_executable_path(candidates: Iterable[str | Path], base: Path) -> Optional[Path]:
    for candidate in candidates:
        path = _as_path(candidate, base)
        if path.exists() and os.access(path, os.X_OK):
            return path
    return None


@dataclass
class TestingAgentConfig:
    repo_name: str
    project_root: Path
    code_coverage_report_path: Path
    test_command: str
    test_command_dir: Path
    aggregate_test_file: Path
    coverage_type: str
    desired_coverage: int
    max_iterations: int
    model: str
    api_base: Optional[str]
    max_run_time: int
    additional_instructions: str
    repo_requirements_file: Optional[Path]
    install_repo_deps_without_deps: bool
    test_requirements_file: Optional[Path]
    html_report_path: Optional[Path]
    migration: Dict[str, object]
    repo_venv_python: Path
    pytest_cov_target: str
    pytest_include_expr: str
    pytest_exclude_expr: str
    selector_output_path: Path
    run_tests_multiple_times: int
    branch: str
    diff_coverage: bool
    run_each_test_separately: bool
    repo_env_pre_commands: List[str]
    repo_env_environment: Dict[str, str]
    log_file: Path
    config_path: Path

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TestingAgentConfig":
        config_path = Path(path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        base_dir = config_path.parent

        repo_name = raw.get("repo_name")
        if not repo_name:
            raise ValueError("`repo_name` must be specified in the configuration")

        project_root_candidates: List[str] = raw.get("project_root_candidates", [])
        project_root = _first_existing_path(project_root_candidates, base_dir)
        if project_root is None:
            raise FileNotFoundError(
                "None of the configured project_root_candidates exist: "
                + ", ".join(project_root_candidates or ["<missing>"])
            )

        test_command = raw.get("test_command", "pytest")
        test_command_dir_rel = raw.get("test_command_dir", "tests")
        test_command_dir = (project_root / test_command_dir_rel).resolve()


        code_coverage_rel = raw.get("code_coverage_report_path")
        code_coverage_rel = _expand_repo_placeholder(code_coverage_rel, repo_name)
        if not code_coverage_rel:
            coverage_candidate = Path("artifacts") / repo_name / "coverage.xml"
        else:
            coverage_candidate = Path(code_coverage_rel)
        if not coverage_candidate.is_absolute():
            code_coverage_report_path = (base_dir / coverage_candidate).resolve()
        else:
            code_coverage_report_path = coverage_candidate.resolve()

        coverage_type = raw.get("coverage_type", "cobertura")
        desired_coverage = int(raw.get("desired_coverage", 90))
        max_iterations = int(raw.get("max_iterations", 8))
        model = raw.get("model", "gpt-4o")
        api_base = raw.get("api_base")
        max_run_time = int(raw.get("max_run_time", 180))
        additional_instructions = raw.get("additional_instructions", "")

        repo_requirements_rel = raw.get("repo_requirements_file")
        repo_requirements_file = (
            (project_root / repo_requirements_rel).resolve()
            if repo_requirements_rel
            else None
        )
        if repo_requirements_file and not repo_requirements_file.exists():
            repo_requirements_file = None

        install_repo_deps_without_deps = bool(
            raw.get("install_repo_deps_without_deps", False)
        )

        test_requirements_rel = raw.get("test_requirements_file")
        test_requirements_file = (
            (project_root / test_requirements_rel).resolve()
            if test_requirements_rel
            else None
        )
        if test_requirements_file and not test_requirements_file.exists():
            test_requirements_file = None

        aggregate_rel = raw.get("aggregate_test_file")
        aggregate_rel = _expand_repo_placeholder(aggregate_rel, repo_name)
        if aggregate_rel:
            aggregate_candidate = Path(aggregate_rel)
        else:
            aggregate_candidate = Path(test_command_dir_rel) / "test_additional.py"
        aggregate_test_file = (
            (project_root / aggregate_candidate).resolve()
            if not aggregate_candidate.is_absolute()
            else aggregate_candidate.resolve()
        )

        html_report_path: Optional[Path]
        if "html_report_path" in raw or "output_file" in raw:
            selected_rel = raw.get("html_report_path")
            if selected_rel is None and "output_file" in raw:
                legacy_rel = raw.get("output_file")
                if legacy_rel is not None:
                    warnings.warn(
                        "`output_file` is deprecated; use `html_report_path` instead.",
                        DeprecationWarning,
                    )
                selected_rel = legacy_rel
            selected_rel = _expand_repo_placeholder(selected_rel, repo_name)
            if selected_rel:
                selected_path = Path(selected_rel)
                if not selected_path.is_absolute():
                    html_report_path = (base_dir / selected_path).resolve()
                else:
                    html_report_path = selected_path.resolve()
            else:
                html_report_path = None
        else:
            default_output_rel = Path("artifacts") / repo_name / "testing_agent_report.html"
            html_report_path = (base_dir / default_output_rel).resolve()

        migration_data = raw.get("migration")
        if not isinstance(migration_data, dict):
            raise ValueError("`migration` section must be provided as a mapping")

        repo_venv_python_candidates: List[str] = raw.get(
            "repo_venv_python_candidates", []
        )
        repo_venv_python = _first_executable_path(
            repo_venv_python_candidates, base_dir
        )
        if repo_venv_python is None:
            fallback_candidates: List[str] = []
            if which("python3"):
                fallback_candidates.append(which("python3"))
            if which("python"):
                fallback_candidates.append(which("python"))
            fallback_candidates.append(sys.executable)

            for fallback in fallback_candidates:
                if not fallback:
                    continue
                fallback_path = Path(fallback).resolve()
                if fallback_path.exists() and os.access(fallback_path, os.X_OK):
                    repo_venv_python = fallback_path
                    break

        if repo_venv_python is None:
            raise FileNotFoundError(
                "None of the configured repo_venv_python_candidates are executable: "
                + ", ".join(repo_venv_python_candidates or ["<missing>"])
            )

        pytest_cov_target = raw.get("pytest_cov_target", "")
        pytest_include_expr = raw.get("pytest_include_expr", "")
        pytest_exclude_expr = raw.get("pytest_exclude_expr", "")

        selector_output_rel = raw.get("selector_output_path")
        if selector_output_rel is None:
            selector_output_rel = Path("repograph_runner/output/repograph_result.json")
        selector_output_rel = _expand_repo_placeholder(selector_output_rel, repo_name)
        selector_output_path = _as_path(selector_output_rel, base_dir)

        run_tests_multiple_times = int(raw.get("run_tests_multiple_times", 1))
        branch = raw.get("branch", "main")
        diff_coverage = bool(raw.get("diff_coverage", False))
        run_each_test_separately = bool(raw.get("run_each_test_separately", False))

        repo_env_pre_commands = [
            str(cmd) for cmd in (raw.get("repo_env_pre_commands") or [])
        ]
        repo_env_environment = {
            str(key): str(value)
            for key, value in (raw.get("repo_env_environment") or {}).items()
        }

        log_file_rel = _expand_repo_placeholder(raw.get("log_file"), repo_name)
        if log_file_rel:
            log_file = _as_path(log_file_rel, base_dir)
        else:
            log_file = (base_dir / "artifacts" / repo_name / "testing_agent.log").resolve()
        log_file = log_file.resolve()

        return cls(
            repo_name=repo_name,
            project_root=project_root,
            code_coverage_report_path=code_coverage_report_path,
            test_command=test_command,
            test_command_dir=test_command_dir,
            aggregate_test_file=aggregate_test_file,
            coverage_type=coverage_type,
            desired_coverage=desired_coverage,
            max_iterations=max_iterations,
            model=model,
            api_base=api_base,
            max_run_time=max_run_time,
            additional_instructions=additional_instructions,
            repo_requirements_file=repo_requirements_file,
            install_repo_deps_without_deps=install_repo_deps_without_deps,
            test_requirements_file=test_requirements_file,
            html_report_path=html_report_path,
            migration=migration_data,
            repo_venv_python=repo_venv_python,
            pytest_cov_target=pytest_cov_target or "",
            pytest_include_expr=pytest_include_expr or "",
            pytest_exclude_expr=pytest_exclude_expr or "",
            selector_output_path=selector_output_path,
            run_tests_multiple_times=run_tests_multiple_times,
            branch=branch,
            diff_coverage=diff_coverage,
            run_each_test_separately=run_each_test_separately,
            repo_env_pre_commands=repo_env_pre_commands,
            repo_env_environment=repo_env_environment,
            log_file=log_file,
            config_path=config_path,
        )
