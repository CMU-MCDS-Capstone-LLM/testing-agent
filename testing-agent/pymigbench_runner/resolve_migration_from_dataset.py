#!/usr/bin/env python3
"""Export PyMigBench migration metadata as YAML using commit-based lookup."""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml


def to_plain(value: Any, seen: Optional[Set[int]] = None) -> Any:
    """Recursively convert PyMigBench objects into YAML-serialisable primitives."""

    if seen is None:
        seen = set()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {str(key): to_plain(val, seen) for key, val in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_plain(item, seen) for item in value]

    if is_dataclass(value):
        return to_plain(asdict(value), seen)

    if isinstance(value, Enum):
        return value.value if hasattr(value, "value") else value.name

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return to_plain(model_dump(), seen)

    if isinstance(value, Path):
        return str(value)

    obj_id = id(value)
    if obj_id in seen:
        return None
    seen.add(obj_id)

    if hasattr(value, "__dict__") and not isinstance(value, type):
        filtered = {
            str(k): v
            for k, v in value.__dict__.items()
            if not callable(v) and not k.startswith("_") and k not in {"mig", "file"}
        }
        return to_plain(filtered, seen)

    return str(value)


def migration_to_mapping(migration: object) -> Dict[str, object]:
    """Convert a PyMigBench migration instance to a plain mapping."""

    if isinstance(migration, dict):
        return to_plain(migration)

    if is_dataclass(migration):
        return to_plain(asdict(migration))

    model_dump = getattr(migration, "model_dump", None)
    if callable(model_dump):
        return to_plain(model_dump())

    attrs = getattr(migration, "__dict__", None)
    if isinstance(attrs, dict):
        return to_plain(
            {k: v for k, v in attrs.items() if not callable(v) and not k.startswith("_")}
        )

    raise TypeError(f"Unsupported migration object type: {type(migration)!r}")


def commit_url_matches(expected: str, actual: str) -> bool:
    """Return True if the commit URLs refer to the same commit."""

    if not expected:
        return True
    if expected == actual:
        return True

    expected_tail = expected.rsplit("/", 1)[-1]
    actual_tail = actual.rsplit("/", 1)[-1]

    if expected_tail and expected_tail == actual_tail:
        return True

    if expected.startswith(actual) or actual.startswith(expected):
        return True

    return False


def find_matching_migration(
    dataset_dir: Path,
    *,
    commit: Optional[str],
    commit_url: Optional[str],
    repo: Optional[str],
) -> Dict[str, object]:
    try:
        from pymigbench.database import Database  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover - injected dependency
        raise RuntimeError("pymigbench must be installed to resolve migrations") from exc

    database = Database.load_from_dir(dataset_dir)
    matches: List[Dict[str, object]] = []
    normalized_repo = (repo or "").strip().lower()
    normalized_commit = (commit or "").strip()
    normalized_commit_url = (commit_url or "").strip()

    if not normalized_commit and not normalized_commit_url:
        raise ValueError("Either commit or commit_url must be provided")

    for migration in database.migs():
        entry = migration_to_mapping(migration)
        entry_commit = str(entry.get("commit") or "").strip()
        entry_commit_url = str(entry.get("commit_url") or "").strip()

        if normalized_commit and entry_commit != normalized_commit:
            continue
        if normalized_commit_url and not commit_url_matches(normalized_commit_url, entry_commit_url):
            continue

        if normalized_repo:
            entry_repo = str(entry.get("repo") or "").strip().lower()
            if entry_repo != normalized_repo:
                continue

        matches.append(entry)

    if not matches:
        parts: List[str] = []
        if normalized_commit:
            parts.append(f"commit={normalized_commit}")
        if normalized_commit_url:
            parts.append(f"commit_url={normalized_commit_url}")
        if normalized_repo:
            parts.append(f"repo={normalized_repo}")
        detail = ", ".join(parts) or "<unspecified>"
        raise LookupError(
            f"Could not locate migration in dataset '{dataset_dir}' matching {detail}"
        )

    if len(matches) > 1:
        repos = sorted({str(m.get("repo")) for m in matches})
        raise LookupError(
            "Multiple migrations matched the provided identifiers. Include MIGRATION_REPO to disambiguate. Candidates: "
            + f"{repos}"
        )

    return matches[0]


def write_config(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a single PyMigBench migration as YAML",
    )
    parser.add_argument(
        "--dataset-dir",
        required=True,
        help="Directory containing PyMigBench YAML files",
    )
    parser.add_argument(
        "--commit",
        help="Commit SHA identifying the migration",
    )
    parser.add_argument(
        "--commit-url",
        help="Commit URL identifying the migration",
    )
    parser.add_argument(
        "--repo",
        help="Optional GitHub repo (owner/name) to disambiguate the commit",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Where to write the resolved migration YAML",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    output_path = Path(args.output).resolve()

    if not dataset_dir.exists() or not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    commit = args.commit.strip() if args.commit else None
    commit_url = args.commit_url.strip() if args.commit_url else None
    if not commit and not commit_url:
        raise ValueError("Either --commit or --commit-url must be supplied")

    repo = args.repo.strip() if args.repo else None

    dataset_entry = find_matching_migration(
        dataset_dir,
        commit=commit,
        commit_url=commit_url,
        repo=repo,
    )
    write_config(output_path, dataset_entry)


if __name__ == "__main__":
    main()
