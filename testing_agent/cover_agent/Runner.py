"""Execution runners for shell-based commands used by cover-agent."""

from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from testing_agent.cover_agent.LineCoverage import (
    load_coverage_hits as lc_load_coverage_hits,
    load_repograph_refs,
    load_repoyaml_refs,
    compute_hit_rate,
)


@dataclass
class CommandResult:
    """Structured outcome from executing a shell command."""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    command_start_time: int
    duration_ms: Optional[int] = None


class Runner(ABC):
    """Abstract runner that executes commands in an isolated environment."""

    def __init__(
        self,
        pre_commands: Optional[Sequence[str]] = None,
        base_environment: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._pre_commands = [
            cmd.strip() for cmd in (pre_commands or []) if cmd and cmd.strip()
        ]
        self._base_environment = dict(base_environment or {})

    def _compose_shell_command(self, command: str) -> str:
        parts = list(self._pre_commands)
        parts.append(command)
        return " && ".join(part for part in parts if part)

    def _build_env(self, extra: Optional[Mapping[str, str]]) -> Mapping[str, str]:
        env = os.environ.copy()
        env.update(self._base_environment)
        if extra:
            env.update(extra)
        return env

    @abstractmethod
    def run_command(
        self,
        command: str,
        max_run_time: int,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> CommandResult:
        """Execute *command* and return a structured result."""


class LocalRunner(Runner):
    """Run commands on the host machine, optionally switching environments first."""

    def __init__(
        self,
        pre_commands: Optional[Sequence[str]] = None,
        base_environment: Optional[Mapping[str, str]] = None,
        shell_path: str = "/bin/bash",
    ) -> None:
        super().__init__(pre_commands=pre_commands, base_environment=base_environment)
        self._shell_path = shell_path

    def run_command(
        self,
        command: str,
        max_run_time: int,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> CommandResult:
        composed_command = self._compose_shell_command(command)
        command_start_time = int(time.time() * 1000)
        start_time = time.perf_counter()

        try:
            completed = subprocess.run(
                composed_command,
                shell=True,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=max_run_time,
                env=self._build_env(env),
                executable=self._shell_path,
            )
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return CommandResult(
                command=composed_command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                command_start_time=command_start_time,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return CommandResult(
                command=composed_command,
                stdout=getattr(exc, "stdout", "") or "",
                stderr=getattr(exc, "stderr", "") or "Command timed out",
                exit_code=-1,
                command_start_time=command_start_time,
                duration_ms=duration_ms,
            )


class RemoteRunner(Runner):
    """Placeholder for commands executed via a remote orchestration service."""

    def __init__(
        self,
        endpoint: str,
        pre_commands: Optional[Sequence[str]] = None,
        base_environment: Optional[Mapping[str, str]] = None,
    ) -> None:
        super().__init__(pre_commands=pre_commands, base_environment=base_environment)
        self.endpoint = endpoint

    def run_command(
        self,
        command: str,
        max_run_time: int,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> CommandResult:
        raise NotImplementedError(
            "RemoteRunner should be implemented by the service integration team."
        )
