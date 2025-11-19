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
    helper_image_name: str
    eval_image_name: str
    python_path: str  # Path to python in container (usually /usr/local/bin/python)
    environment: Dict[str, str]
    pip_deps: List[str]
    test_cmd: List[str]
    install_editable: bool

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["root"] = str(self.root)
        return payload

    @classmethod
    def from_json(cls, path: Path) -> "EnvMetadata":
        data = json.loads(path.read_text(encoding="utf-8"))
        data["root"] = Path(data["root"])
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
    env_mode: str = "helper",
) -> EnvMetadata:
    """Build Docker images for repository testing environment."""

    decision = _load_decision_json(decision_path)
    variables: Dict[str, object] = decision.get("variables", {}) if isinstance(decision, dict) else {}
    pip_deps: List[str] = list(variables.get("pip_deps", []) or [])
    # Always ensure pytest + coverage helpers available; ignore decision-provided test_cmd when choosing deps.
    for dep in ("pytest", "pytest-cov", "pytest-mock"):
        if dep not in pip_deps:
            pip_deps.append(dep)

    install_editable = bool(variables.get("install_editable", False)) and not skip_editable

    # Force pytest-based default test command; do not inherit decision.json test_cmd to avoid legacy/coverage-only commands.
    test_cmd: List[str] = ["python", "-m", "pytest", "-v", "tests/"]
    env_vars: Dict[str, str] = {str(k): str(v) for k, v in (variables.get("env_vars", {}) or {}).items()}

    repo_path = repo_path.resolve()

    # Find Dockerfile in envs directory
    env_dir = decision_path.parent
    dockerfile_path = env_dir / "Dockerfile"
    if not dockerfile_path.exists():
        raise EnvironmentError(f"Dockerfile not found at {dockerfile_path}")

    # Docker image names
    helper_image_name = f"{repo_id}:helper"
    eval_image_name = f"{repo_id}:eval"

    # Build helper image (always for helper mode, prerequisite for eval mode)
    if env_mode == "helper" or not _docker_image_exists(helper_image_name):
        print(f"Building Docker image: {helper_image_name}")
        _run([
            "sudo", "docker", "build",
            "-f", str(dockerfile_path),
            "-t", helper_image_name,
            str(repo_path)  # Build context is the repo root
        ])
        print(f"✓ Built {helper_image_name}")

        # Install lsp-repograph and jedi-language-server for repograph functionality
        # lsp-repograph requires Python >= 3.8, so check version first
        print(f"Checking Python version in {helper_image_name}...")
        version_check = subprocess.run(
            ["sudo", "docker", "run", "--rm", helper_image_name,
             "python", "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            text=True,
            check=False
        )

        if version_check.returncode == 0:
            py_version = version_check.stdout.strip()
            py_major, py_minor = map(int, py_version.split('.'))

            # Install Python 3.11 and lsp-repograph for all Python versions
            print(f"Installing Python 3.11 and lsp-repograph into {helper_image_name} (base Python {py_version})...")
            temp_container_name = f"temp_{repo_id}_lsp_install"
            try:
                # Install Python 3.11 and lsp-repograph
                # Python 3.11 will be used for running repograph, base Python for repo tests
                _run([
                    "sudo", "docker", "run", "--name", temp_container_name, "--user", "root",
                    helper_image_name,
                    "bash", "-c",
                    # Install Python 3.11 and pip
                    "apt-get update && "
                    "apt-get install -y --no-install-recommends python3.11 python3.11-distutils python3-pip wget && "
                    "rm -rf /var/lib/apt/lists/* && "
                    # Install pip for Python 3.11 (using --break-system-packages to bypass PEP 668)
                    "wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py && "
                    "python3.11 /tmp/get-pip.py --break-system-packages && "
                    "rm /tmp/get-pip.py && "
                    # Install lsp-repograph dependencies in Python 3.11
                    "python3.11 -m pip install --break-system-packages multilspy psutil toml jedi-language-server && "
                    "python3.11 -m pip install --break-system-packages --no-deps git+https://github.com/CMU-MCDS-Capstone-LLM/LSP-Repograph.git@main"
                ])
                # Commit the container as the updated image
                _run(["sudo", "docker", "commit", temp_container_name, helper_image_name])
                print(f"✓ Installed Python 3.11 and lsp-repograph")
            finally:
                # Clean up temporary container
                subprocess.run(
                    ["sudo", "docker", "rm", "-f", temp_container_name],
                    capture_output=True,
                    check=False
                )

        # Always ensure pytest is available in the helper image (for coverage collection)
        print(f"Ensuring pytest is installed in {helper_image_name}...")
        pytest_check = subprocess.run(
            ["sudo", "docker", "run", "--rm", helper_image_name, "python", "-c", "import pytest"],  # noqa: S603
            capture_output=True,
            text=True,
            check=False,
        )
        if pytest_check.returncode != 0:
            print("Installing pytest/pytest-cov into helper image...")
            temp_container_name = f"temp_{repo_id}_pytest"
            try:
                _run(
                    [
                        "sudo",
                        "docker",
                        "run",
                        "--name",
                        temp_container_name,
                        "--user",
                        "root",
                        helper_image_name,
                        "bash",
                        "-c",
                        "pip install pytest pytest-cov pytest-mock || python -m pip install pytest pytest-cov pytest-mock",
                    ]
                )
                _run(["sudo", "docker", "commit", temp_container_name, helper_image_name])
                print("✓ Installed pytest/pytest-cov in helper image")
            finally:
                subprocess.run(
                    ["sudo", "docker", "rm", "-f", temp_container_name],
                    capture_output=True,
                    check=False,
                )
    else:
        print(f"Using existing Docker image: {helper_image_name}")

    # For eval mode, we'll handle library swapping in run_repo.py
    # Here we just note that eval image will be created on demand

    # Python path in container (standard location for python:*-slim images)
    python_path_in_container = "/usr/local/bin/python"

    metadata = EnvMetadata(
        repo_id=repo_id,
        root=repo_path,
        helper_image_name=helper_image_name,
        eval_image_name=eval_image_name,
        python_path=python_path_in_container,
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


def _docker_image_exists(image_name: str) -> bool:
    """Check if a Docker image exists locally."""
    try:
        result = subprocess.run(
            ["sudo", "docker", "images", "-q", image_name],
            capture_output=True,
            text=True,
            check=True
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


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

    metadata = install_env(
        repo_id=args.repo_id,
        repo_path=repo_path,
        decision_path=decision_path,
        python_executable=args.python,
        force_recreate=args.force,
    )
    print(json.dumps(metadata.to_dict(), indent=2))


if __name__ == "__main__":
    main()
