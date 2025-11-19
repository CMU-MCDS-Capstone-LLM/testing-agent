"""Helpers for loading and querying repo<->yaml name mappings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


def load_name_map(
    *,
    base_dir: Path,
    name_map_path: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Load a name_map.json mapping repo folder -> yaml stem.

    Args:
        base_dir: Root directory containing name_map.json (default location).
        name_map_path: Optional explicit path to name_map.json.
    """
    path = Path(name_map_path) if name_map_path else (base_dir / "name_map.json")
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"name_map must be a mapping, got {type(data)}")
    # Normalize keys/values to str
    return {str(k): str(v) for k, v in data.items()}


def repo_to_yaml(repo_folder: str, mapping: Dict[str, str]) -> str:
    """Map repo folder name to yaml stem (fallback to input if missing)."""
    return mapping.get(repo_folder, repo_folder)


def yaml_to_repo(yaml_stem: str, mapping: Dict[str, str]) -> str:
    """Map yaml stem to repo folder (fallback to input if missing)."""
    for repo_folder, stem in mapping.items():
        if stem == yaml_stem:
            return repo_folder
    return yaml_stem
