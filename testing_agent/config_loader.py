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
    log_level: str
    cover_agent_log_db_path: Path
    config_path: Path

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TestingAgentConfig":
        def maybe_concat(rel_or_abs_path: Path, parent_folder: Path):
            if rel_or_abs_path.is_absolute():
                return rel_or_abs_path.resolve()
            return (parent_folder / rel_or_abs_path).resolve()

        config_path = Path(path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        repo_name = raw["repo_name"]

        project_root_candidates = [Path(p).resolve() for p in raw["project_root_candidates"]]
        for p in project_root_candidates:
            if not p.is_absolute():
                raise RuntimeError(f"Project root must be an absolute path. Instead, we got {p}");
        project_root = _first_existing_path(project_root_candidates, Path("/"))
        if project_root is None:
            raise FileNotFoundError(
                "None of the configured project_root_candidates exist: "
                + ", ".join(str(p) for p in project_root_candidates or ["<missing>"])
            )

        metadata_folder = Path(raw['metadata_folder'])
        if not metadata_folder.is_absolute():
            raise ValueError("metadata_folder must be an absolute path!")

        test_command = raw["test_command"]

        # TODO: May need to move to input-tests folder instead
        # For now, we save test directly under repo root
        test_command_dir = maybe_concat(
            Path(raw["test_command_dir"]),
            project_root
        )

        code_coverage_report_path = maybe_concat(
            Path(raw["code_coverage_report_path"]),
            metadata_folder
        )

        coverage_type = raw.get("coverage_type", "cobertura")
        desired_coverage = int(raw.get("desired_coverage", 90))
        max_iterations = int(raw.get("max_iterations", 8))
        model = raw.get("model", "gpt-4o")
        api_base = raw.get("api_base")
        max_run_time = int(raw.get("max_run_time", 180))
        additional_instructions = raw.get("additional_instructions", "")

        aggregate_test_file = maybe_concat(
            Path(raw["aggregate_test_file"]),
            test_command_dir
        )

        html_report_path = maybe_concat(
            Path(raw["html_report_path"]),
            metadata_folder
        )

        migration_data = raw["migration"]
        if not isinstance(migration_data, dict):
            raise ValueError("`migration` section must be provided as a mapping")

        repo_venv_python_candidates: List[str] = raw.get(
            "repo_venv_python_candidates", []
        )
        # TODO: The logic of _first_executable_path need fixes
        repo_venv_python = _first_executable_path(
            repo_venv_python_candidates, Path("/")
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
            raise RuntimeError(
                "None of the configured repo_venv_python_candidates are executable: "
                + ", ".join(repo_venv_python_candidates or ["<missing>"])
            )

        pytest_cov_target = raw.get("pytest_cov_target", "")
        pytest_include_expr = raw.get("pytest_include_expr", "")
        pytest_exclude_expr = raw.get("pytest_exclude_expr", "")

        selector_output_path = maybe_concat(
            Path(raw['selector_output_path']), 
            metadata_folder
        )

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

        log_file = maybe_concat(
            Path(raw['log_file']), 
            metadata_folder
        )
        log_level = raw.get("log_level", "INFO").upper()

        cover_agent_log_db_path = maybe_concat(
            Path(raw['cover_agent_log_db_path']), 
            metadata_folder
        )

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
            log_level=log_level,
            cover_agent_log_db_path=cover_agent_log_db_path,
            config_path=config_path,
        )
