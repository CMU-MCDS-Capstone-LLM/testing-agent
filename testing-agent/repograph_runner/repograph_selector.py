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
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import yaml

from lsp_repograph.core.multilspy_client import MultilspyLSPClient  # type: ignore[attr-defined]


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

    module = parts[0]
    qualpath = ".".join(parts[1:]) or None
    return module, qualpath


def format_references(repo_root: Path, refs: Iterable[Dict[str, object]]) -> Dict[str, object]:
    """
    Convert raw reference dictionaries (absolute_path, line, character) into a normalized JSON-friendly format.

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

        if str(rel_path) not in seen_paths:
            seen_paths.add(str(rel_path))
            files.append(str(rel_path))

        formatted_refs.append(
            {
                "relative_path": str(rel_path),
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
    """Parse a PyMigBench-style migration YAML and return its dictionary representation."""
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

    repo_root = Path(args.repo_path).resolve()
    config_path = Path(args.config).resolve()

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
        source_module, source_qualpath = guess_module_and_qualpath(source_symbol, repo_root)

    if not source_module:
        raise ValueError("Migration config must define a source module or symbol")

    custom_init = build_custom_init(args.env_python, args.extra_path)
    client = MultilspyLSPClient(str(repo_root), custom_init_params=custom_init)

    try:
        # 1) Find every file that references the source symbol
        library_refs = client.find_refs_by_fqn(module=source_module, qualpath=source_qualpath)
        library_consumers = format_references(repo_root, library_refs)

        result = {
            "source": {"module": source_module, "qualpath": source_qualpath},
            "library_consumers": library_consumers,
            "workspace_callers": {},
        }

        # 2) For each requested workspace symbol, resolve its references as well
        for sym in args.workspace_symbol:
            if ":" in sym:
                module_part, qualpath_part = sym.split(":", 1)
                qualpath_part = qualpath_part or None
            else:
                module_part, qualpath_part = guess_module_and_qualpath(sym, repo_root)

            refs = client.find_refs_by_fqn(module=module_part, qualpath=qualpath_part)
            key = f"{module_part}:{qualpath_part or ''}"
            result["workspace_callers"][key] = format_references(repo_root, refs)

    finally:
        client.shutdown()

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload)
    else:
        print(payload)



if __name__ == "__main__":
    main()
