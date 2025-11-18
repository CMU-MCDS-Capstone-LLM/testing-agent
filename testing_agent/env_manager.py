"""Utility helpers for installing per-repository virtual environments."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class EnvMetadata:
    """Metadata describing the repository execution environment."""

    repo_id: str
    root: Path
    helper_venv_path: Path
    eval_venv_path: Path
    python_path: Path
    activate_commands: Dict[str, List[str]]
    environment: Dict[str, str]
    pip_deps: List[str]
    test_cmd: List[str]
    install_editable: bool

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["root"] = str(self.root)
        payload["helper_venv_path"] = str(self.helper_venv_path)
        payload["eval_venv_path"] = str(self.eval_venv_path)
        payload["python_path"] = str(self.python_path)
        return payload

    @classmethod
    def from_json(cls, path: Path) -> "EnvMetadata":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["root"] = Path(data["root"])
        data["helper_venv_path"] = Path(data["helper_venv_path"])
        data["eval_venv_path"] = Path(data["eval_venv_path"])
        data["python_path"] = Path(data["python_path"])
        return cls(**data)


class EnvironmentError(RuntimeError):
    """Raised when the repository environment cannot be provisioned."""


def _run(
    cmd: List[str], *, cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None
) -> None:
    subprocess.run(cmd, check=True, cwd=str(cwd) if cwd else None, env=env)


def _detect_python_bin(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _activate_commands_for(venv_path: Path) -> List[str]:
    if os.name == "nt":
        activate = venv_path / "Scripts" / "activate"
        return [f"call {activate}"]
    activate = venv_path / "bin" / "activate"
    return [f"source {activate}"]


def _load_decision_json(decision_path: Path) -> Dict[str, object]:
    if not decision_path.exists():
        raise EnvironmentError(f"decision.json not found: {decision_path}")
    with decision_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _ensure_sqlite(
    python_path: Path,
    *,
    repo_id: str,
    repo_path: Path,
    command_env: Dict[str, str],
    auto_fix: bool,
) -> None:
    """Verify sqlite3 availability; optionally install a pysqlite shim if missing."""
    try:
        _run([str(python_path), "-c", "import sqlite3"], cwd=repo_path, env=command_env)
        return
    except subprocess.CalledProcessError:
        if not auto_fix:
            raise EnvironmentError(
                f"Python at {python_path} lacks sqlite3 needed by {repo_id}. "
                "Install system sqlite or set AUTO_FIX_SQLITE=1 to auto-install pysqlite3-binary."
            )
    # Try to install a shim to unblock environments (used by mlflow, etc.).
    _run(
        [str(python_path), "-m", "pip", "install", "pysqlite3-binary"],
        cwd=repo_path,
        env=command_env,
    )
    # Drop a sitecustomize to alias sqlite3 -> pysqlite3 if still missing.
    try:
        site_dir = subprocess.check_output(
            [str(python_path), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            text=True,
            env=command_env,
        ).strip()
        if site_dir:
            sitecustomize = Path(site_dir) / "sitecustomize.py"
            sitecustomize.parent.mkdir(parents=True, exist_ok=True)
            sitecustomize.write_text(
                "try:\n"
                "    import sqlite3  # noqa: F401\n"
                "except Exception:\n"
                "    try:\n"
                "        import pysqlite3 as sqlite3  # type: ignore\n"
                "        import sys\n"
                "        sys.modules['sqlite3'] = sqlite3\n"
                "    except Exception:\n"
                "        pass\n",
                encoding="utf-8",
            )
    except Exception:
        # Best-effort shim; continue even if we cannot write sitecustomize.
        pass


def _parse_version_tag(version_tag: str) -> Tuple[str, str]:
    clean = (version_tag or "").split("-")[0].strip()
    if not clean:
        return "", ""
    parts = clean.split(".")
    major = parts[0] if parts else ""
    minor = parts[1] if len(parts) > 1 else ""
    return major, minor


def _python_matches_version(python_bin: str, major: str, minor: str) -> bool:
    if not major:
        return True
    try:
        output = subprocess.check_output(
            [python_bin, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            text=True,
        ).strip()
    except Exception:
        return False
    parts = output.split(".")
    if not parts or parts[0] != major:
        return False
    if minor and (len(parts) < 2 or parts[1] != minor):
        return False
    return True


def _resolve_python_executable(
    *,
    version_tag: str,
    explicit_python: Optional[str],
) -> str:
    major, minor = _parse_version_tag(version_tag)

    def _resolve_path(candidate: str) -> Optional[str]:
        path = Path(candidate)
        if path.exists():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        return None

    if explicit_python:
        resolved = _resolve_path(explicit_python)
        if not resolved:
            raise EnvironmentError(
                f"Provided python executable '{explicit_python}' not found."
            )
        if not _python_matches_version(resolved, major, minor):
            raise EnvironmentError(
                f"Provided python '{resolved}' does not match required version tag '{version_tag}'."
            )
        return resolved

    if not major:
        # No specific version requested; return current interpreter
        return sys.executable

    candidates: List[str] = []
    if major and minor:
        candidates.append(f"python{major}.{minor}")
    if major:
        candidates.append(f"python{major}")
    candidates.extend([
        "python3.9",
        "python3.8",
        "python3.7",
        "python3",
        "python",
    ])
    candidates = [c for c in candidates if c]

    for candidate in candidates:
        resolved = _resolve_path(candidate)
        if not resolved:
            continue
        if _python_matches_version(resolved, major, minor):
            return resolved

    raise EnvironmentError(
        f"Unable to locate a python executable matching version tag '{version_tag}'."
    )


def install_env(
    *,
    repo_id: str,
    repo_path: Path,
    decision_path: Path,
    python_executable: Optional[str] = None,
    force_recreate: bool = False,
    skip_editable: bool = False,
    skip_editable_on_error: bool = True,
    auto_fix_sqlite: bool = True,
) -> EnvMetadata:
    """Create (or reuse) a virtual environment and install repo dependencies."""

    decision = _load_decision_json(decision_path)
    variables: Dict[str, object] = decision.get("variables", {}) if isinstance(decision, dict) else {}
    pip_deps: List[str] = list(variables.get("pip_deps", []) or [])
    pip_deps.extend(["pytest-cov", "pytest-mock"])
    install_editable = bool(variables.get("install_editable", False)) and not skip_editable
    test_cmd: List[str] = list(variables.get("test_cmd", []) or [])
    env_vars: Dict[str, str] = {str(k): str(v) for k, v in (variables.get("env_vars", {}) or {}).items()}

    repo_path = repo_path.resolve()
    helper_venv = (repo_path / ".venv_helper").resolve()
    eval_venv = (repo_path / ".venv_eval").resolve()

    python_version_tag = str(variables.get("python_version_tag", ""))
    python_bin = _resolve_python_executable(
        version_tag=python_version_tag,
        explicit_python=python_executable,
    )

    def _ensure_venv(path: Path) -> None:
        if force_recreate and path.exists():
            shutil.rmtree(path)
        if not path.exists():
            _run([python_bin, "-m", "venv", str(path)])

    _ensure_venv(helper_venv)
    if env_mode == "helper":
        target_venv = helper_venv
    else:
        _ensure_venv(eval_venv)
        if helper_venv.exists() and (force_recreate or not eval_venv.exists()):
            if eval_venv.exists():
                shutil.rmtree(eval_venv)
            shutil.copytree(helper_venv, eval_venv)
        target_venv = eval_venv

    python_path = _detect_python_bin(target_venv)
    if not python_path.exists():
        raise EnvironmentError(
            f"Unable to locate python binary in venv: {python_path}"
        )

    command_env = os.environ.copy()
    command_env.update(env_vars)

    if auto_fix_sqlite and os.environ.get("AUTO_FIX_SQLITE", "1") == "1":
        _ensure_sqlite(
            python_path=python_path,
            repo_id=repo_id,
            repo_path=repo_path,
            command_env=command_env,
            auto_fix=True,
        )

    _run(
        [str(python_path), "-m", "pip", "install", "--upgrade", "pip"],
        cwd=repo_path,
        env=command_env,
    )
    if pip_deps:
        _run(
            [str(python_path), "-m", "pip", "install", *pip_deps],
            cwd=repo_path,
            env=command_env,
        )
    if install_editable:
        try:
            _run(
                [str(python_path), "-m", "pip", "install", "-e", "."],
                cwd=repo_path,
                env=command_env,
            )
        except subprocess.CalledProcessError as exc:
            if skip_editable_on_error or os.environ.get("TA_SKIP_EDITABLE_ON_ERROR", "1") == "1":
                print(
                    f"[WARN] Editable install failed for {repo_id} ({repo_path}). "
                    f"Skipping -e . to unblock setup. Error: {exc}"
                )
            else:
                raise

    metadata = EnvMetadata(
        repo_id=repo_id,
        root=repo_path,
        helper_venv_path=helper_venv,
        eval_venv_path=eval_venv,
        python_path=python_path,
        activate_commands={
            "helper": _activate_commands_for(helper_venv),
            "eval": _activate_commands_for(eval_venv),
        },
        environment=env_vars,
        pip_deps=pip_deps,
        test_cmd=test_cmd,
        install_editable=install_editable,
    )

    metadata_dir = repo_path / ".testing_agent"
    _ensure_directory(metadata_dir)
    metadata_path = metadata_dir / "env_metadata.json"
    metadata_path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")

    return metadata


def load_env_metadata(repo_path: Path) -> Optional[EnvMetadata]:
    metadata_path = (repo_path / ".testing_agent" / "env_metadata.json").resolve()
    if not metadata_path.exists():
        return None
    return EnvMetadata.from_json(metadata_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install testing-agent virtual environment")
    parser.add_argument("repo_id", help="Repository identifier (folder name under repos/)")
    parser.add_argument("repo_path", help="Path to the repository root")
    parser.add_argument("decision_path", help="Path to envs/<repo_id>/decision.json")
    parser.add_argument("--venv-dir", default=None, help="Optional destination for the virtual environment")
    parser.add_argument("--python", default=None, help="Python binary used to create the venv")
    parser.add_argument("--force", action="store_true", help="Recreate the virtual environment even if it exists")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_path = Path(args.repo_path)
    decision_path = Path(args.decision_path)
    venv_dir = Path(args.venv_dir).resolve() if args.venv_dir else None

    metadata = install_env(
        repo_id=args.repo_id,
        repo_path=repo_path,
        decision_path=decision_path,
        venv_dir=venv_dir,
        python_executable=args.python,
        force_recreate=args.force,
    )
    print(json.dumps(metadata.to_dict(), indent=2))


if __name__ == "__main__":
    main()
