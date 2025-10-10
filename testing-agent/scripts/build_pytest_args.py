#!/usr/bin/env python3
"""Generate pytest coverage arguments from repograph output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence, Set, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build pytest --cov and -k arguments from repograph selector output.",
    )
    parser.add_argument("--repo-root", required=True, help="Path to the repository root.")
    parser.add_argument(
        "--selector-json",
        required=True,
        help="Path to repograph_result.json produced by repograph_selector.py.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="File where environment variables will be written.",
    )
    return parser.parse_args()


def load_selected_paths(selector_json: Path) -> Set[Path]:
    with selector_json.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    paths: Set[Path] = set()
    for key in ("library_consumers", "workspace_callers"):
        block = data.get(key, {})
        if isinstance(block, dict):
            for item in block.get("files", []):
                if item:
                    paths.add(Path(item))
    return paths


def normalize_module(path: Path) -> str | None:
    if path.suffix != ".py":
        return None
    parts = path.with_suffix("").parts
    if "src" in parts:
        index = parts.index("src") + 1
        module_parts = parts[index:]
    else:
        module_parts = parts
    if not module_parts:
        return None
    return ".".join(module_parts)


def discover_test_tokens(repo_root: Path, rel_path: Path) -> Set[str]:
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

    for name in candidate_names:
        tokens.add(name)

    for candidate in candidate_paths:
        if (repo_root / candidate).exists():
            tokens.add(candidate.stem)

    return tokens


def build_arguments(repo_root: Path, selected: Set[Path]) -> Tuple[Set[str], Set[str]]:
    cov_targets: Set[str] = set()
    include_tokens: Set[str] = set()

    for rel_path in selected:
        module = normalize_module(rel_path)
        if not module:
            continue

        if module.startswith("tests") or ".tests." in module:
            include_tokens.add(Path(module).name)
            continue

        cov_targets.add(module)
        include_tokens.update(discover_test_tokens(repo_root, rel_path))

    include_tokens = {token for token in include_tokens if token}
    cov_targets = {target for target in cov_targets if target}
    return cov_targets, include_tokens


def write_env_file(output: Path, cov_targets: Set[str], expressions: Set[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    cov_value = ",".join(sorted(cov_targets)) if cov_targets else ""
    expr_value = " or ".join(sorted(expressions)) if expressions else ""

    with output.open("w", encoding="utf-8") as handle:
        handle.write(f'PYTEST_COV_TARGET="{cov_value}"\n')
        handle.write(f'PYTEST_INCLUDE_EXPR="{expr_value}"\n')


def main() -> None:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    selector_json = Path(args.selector_json).resolve()
    output_path = Path(args.output).resolve()

    if not selector_json.exists():
        write_env_file(output_path, set(), set())
        return

    selected_paths = load_selected_paths(selector_json)
    cov_targets, expressions = build_arguments(repo_root, selected_paths)
    write_env_file(output_path, cov_targets, expressions)


if __name__ == "__main__":
    main()
