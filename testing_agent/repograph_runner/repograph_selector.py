#!/usr/bin/env python3
"""
repograph_selector.py

Utility script that leverages MultilspyLSPClient to gather:

1) Every file inside the repository that references a given external symbol
    (identified by module + optional dotted path inside the module).
2) Optionally, for additional workspace symbols, every file that references
    those symbols as well.

The script produces JSON output so downstream tooling (e.g., your test
generation pipeline) can consume the filtered file set easily.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from lsp_repograph.core.multilspy_client import MultilspyLSPClient  # type: ignore[attr-defined]


@dataclass
class RepoGraphRequest:
    """Input parameters required to execute a RepoGraph query."""

    repo_path: Path
    migration_config: Path
    env_python: Optional[str] = None
    extra_paths: Sequence[str] = ()
    workspace_symbols: Sequence[str] = ()


@dataclass
class RepoGraphResult:
    """Structured output produced by a RepoGraph runner."""

    source_module: str
    source_qualpath: Optional[str]
    library_consumers: Dict[str, object]
    workspace_callers: Dict[str, Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": {
                "module": self.source_module,
                "qualpath": self.source_qualpath,
            },
            "library_consumers": self.library_consumers,
            "workspace_callers": self.workspace_callers,
        }


class RepoGraphRunner(ABC):
    """Abstract interface for executing RepoGraph in different environments."""

    @abstractmethod
    def run(self, request: RepoGraphRequest) -> RepoGraphResult:
        """Execute RepoGraph and return its structured result."""


class LocalRepoGraphRunner(RepoGraphRunner):
    """Run RepoGraph against a local checkout using the host interpreter."""

    def run(self, request: RepoGraphRequest) -> RepoGraphResult:
        repo_root = request.repo_path.resolve()
        config_path = request.migration_config.resolve()

        if not repo_root.exists():
            raise FileNotFoundError(f"repo_path not found: {repo_root}")
        if not config_path.exists():
            raise FileNotFoundError(f"config not found: {config_path}")

        migration_cfg = load_migration_config(config_path)

        source_entry = migration_cfg.get("source")
        if isinstance(source_entry, dict):
            source_module = source_entry.get("module")
            source_qualpath = source_entry.get("qualpath")
        else:
            source_symbol = str(source_entry)
            source_module, source_qualpath = guess_module_and_qualpath(
                source_symbol, repo_root
            )

        if not source_module:
            raise ValueError("Migration config must define a source module or symbol")

        custom_init = build_custom_init(request.env_python, request.extra_paths)
        client = MultilspyLSPClient(str(repo_root), custom_init_params=custom_init)

        try:
            library_refs = client.find_refs_by_fqn(
                module=source_module, qualpath=source_qualpath
            )
            library_consumers = format_references(repo_root, library_refs)

            workspace_callers: Dict[str, Dict[str, object]] = {}
            for sym in request.workspace_symbols:
                if ":" in sym:
                    module_part, qualpath_part = sym.split(":", 1)
                    qualpath_part = qualpath_part or None
                else:
                    module_part, qualpath_part = guess_module_and_qualpath(sym, repo_root)

                refs = client.find_refs_by_fqn(
                    module=module_part, qualpath=qualpath_part
                )
                key = f"{module_part}:{qualpath_part or ''}"
                workspace_callers[key] = format_references(repo_root, refs)

        finally:
            client.shutdown()

        return RepoGraphResult(
            source_module=source_module,
            source_qualpath=source_qualpath,
            library_consumers=library_consumers,
            workspace_callers=workspace_callers,
        )


def build_custom_init(
    env_python: Optional[str], extra_paths: Iterable[str]
) -> Optional[Dict[str, object]]:
    """Prepare initializationOptions for Multilspy/Jedi so the target repo's environment is on the path."""
    workspace_cfg: Dict[str, object] = {}
    normalized_extra_paths = [str(Path(p).resolve()) for p in extra_paths if p]

    if env_python:
        workspace_cfg["environmentPath"] = str(Path(env_python).resolve())
    if normalized_extra_paths:
        workspace_cfg["extraPaths"] = normalized_extra_paths

    if workspace_cfg:
        return {"initializationOptions": {"workspace": workspace_cfg}}
    return None


def guess_module_and_qualpath(symbol: str, repo_root: Path) -> Tuple[str, Optional[str]]:
    """
    Split a dotted string like 'collections.deque.popleft' into (module, qualpath).

    Strategy:
    1. Temporarily insert repo_root into sys.path.
    2. Try longest prefix imports, falling back to 'first component' if none succeed.
    3. Try common package name mappings if direct import fails (e.g., attr -> attrs).

    Returns:
        (module, qualpath or None)
    """
    parts = symbol.split(".")
    if not parts:
        raise ValueError(f"Invalid symbol string: '{symbol}'")

    repo_str = str(repo_root)
    sys_path_added = False
    if repo_str and repo_str not in sys.path:
        sys.path.insert(0, repo_str)
        sys_path_added = True

    try:
        for i in range(len(parts), 0, -1):
            module_candidate = ".".join(parts[:i])
            try:
                spec = importlib.util.find_spec(module_candidate)
            except (ImportError, ValueError):
                spec = None
            if spec is not None:
                qualpath = ".".join(parts[i:]) or None
                return module_candidate, qualpath
    finally:
        if sys_path_added:
            try:
                sys.path.remove(repo_str)
            except ValueError:
                pass

    # If direct import failed, try common package name mappings
    # The repo.yaml source field may be a package name (e.g., "slackclient", "pyyaml")
    # but we need the module name for find_refs_by_fqn (e.g., "slack", "yaml")
    # This maps package_name -> module_name when direct import fails
    common_mappings = {
        "slackclient": "slack",  # slackclient package, slack module
        "slack-sdk": "slack_sdk",  # slack-sdk package, slack_sdk module
        "pyyaml": "yaml",  # pyyaml package, yaml module
        "beautifulsoup4": "bs4",  # beautifulsoup4 package, bs4 module
        "opencv-python": "cv2",  # opencv-python package, cv2 module
        "scikit-learn": "sklearn",  # scikit-learn package, sklearn module
        "pillow": "PIL",  # pillow package, PIL module
    }

    first_part = parts[0]
    if first_part in common_mappings:
        # Use the mapped module name directly without checking if it's importable,
        # since this function runs in the testing-agent environment which may not
        # have the target libraries installed. The target environment will have them.
        mapped_name = common_mappings[first_part]
        qualpath = ".".join(parts[1:]) or None
        return mapped_name, qualpath

    module = parts[0]
    qualpath = ".".join(parts[1:]) or None
    return module, qualpath


def has_module_level_side_effects(file_path: Path) -> bool:
    """
    Check if a Python file has module-level side effects that would cause
    import-time failures (e.g., instantiating clients, making network calls).

    Returns True if the file contains suspicious patterns at module level.
    """
    try:
        content = file_path.read_text()

        # Check for module-level instantiation of HTTP clients, database connections, etc.
        suspicious_patterns = [
            r'^\s*\w+\s*=\s*\w*HttpClient\s*\(',
            r'^\s*\w+\s*=\s*\w*Client\s*\(',
            r'^\s*\w+\s*=\s*\w*Database\s*\(',
            r'^\s*\w+\s*=\s*\w*Connection\s*\(',
            r'^\s*\w+\s*=\s*requests\.',
            r'^\s*\w+\s*=\s*mlflow\.',
        ]

        import re
        lines = content.split('\n')
        for i, line in enumerate(lines):
            # Skip comments and docstrings
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue

            # Stop at function/class definitions (module level code ends)
            if stripped.startswith('def ') or stripped.startswith('class '):
                break

            # Check for suspicious patterns
            for pattern in suspicious_patterns:
                if re.match(pattern, line):
                    return True

        return False
    except Exception:
        return False


def format_references(repo_root: Path, refs: Iterable[Dict[str, object]]) -> Dict[str, object]:
    """
    Convert raw reference dictionaries (absolute_path, line, character) into a normalized JSON-friendly format.
    Filters out test files, temporary/generated files, and files with module-level side effects.

    Returns:
        {
            "files": [... unique relative paths ...],
            "references": [
                {
                    "relative_path": "...",
                    "absolute_path": "...",
                    "line": 12,         # 1-based
                    "character": 5      # 1-based
                },
                ...
            ]
        }
    """
    seen_paths = set()
    files: List[str] = []
    formatted_refs: List[Dict[str, object]] = []

    for ref in refs:
        abs_path = Path(ref["absolute_path"]).resolve()
        rel_path = abs_path.relative_to(repo_root)
        rel_path_str = str(rel_path)

        # Skip test files
        if looks_like_test(rel_path_str):
            continue

        # Skip temporary/generated files
        if rel_path.name.startswith("_scratch_"):
            continue

        # Skip files with module-level side effects (import-time failures)
        if has_module_level_side_effects(abs_path):
            continue

        if rel_path_str not in seen_paths:
            seen_paths.add(rel_path_str)
            files.append(rel_path_str)

        formatted_refs.append(
            {
                "relative_path": rel_path_str,
                "absolute_path": str(abs_path),
                "line": ref["line"] + 1,        # convert to 1-based
                "character": ref["character"] + 1,
            }
        )

    return {"files": files, "references": formatted_refs}


def looks_like_test(path: str) -> bool:
    lower = path.lower()
    name = lower.split("/")[-1]
    return (
        "tests" in lower
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def load_migration_config(path: Path) -> Dict[str, object]:
    """Parse a migration YAML and return its dictionary representation."""
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Cannot parse migration config at {path}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="RepoGraph selector utility")
    parser.add_argument("--repo-path", required=True, help="Path to the repository under analysis")
    parser.add_argument("--config", required=True, help="Migration config YAML (e.g., PyMigBench entry)")
    parser.add_argument("--env-python", help="Path to the interpreter for the target repo's virtualenv")
    parser.add_argument(
        "--extra-path",
        action="append",
        default=[],
        help="Additional site-packages directories to include in LSP resolution (repeatable)",
    )
    parser.add_argument(
        "--workspace-symbol",
        action="append",
        default=[],
        help="Workspace symbol to inspect, format 'package.module:qualpath' or just 'package.module'",
    )
    parser.add_argument("--output", help="If provided, write JSON result to this path; otherwise print to stdout")
    args = parser.parse_args()

    request = RepoGraphRequest(
        repo_path=Path(args.repo_path),
        migration_config=Path(args.config),
        env_python=args.env_python,
        extra_paths=tuple(args.extra_path),
        workspace_symbols=tuple(args.workspace_symbol),
    )

    result = LocalRepoGraphRunner().run(request)
    payload = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload)
    else:
        print(payload)



if __name__ == "__main__":
    main()
