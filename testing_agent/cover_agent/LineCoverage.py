import json
import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple

import yaml
from testing_agent.name_map_utils import load_name_map


def _normalize_rel(path: Optional[str]) -> Optional[str]:
    if path is None:
        return None
    return os.path.normpath(path.replace("\\", "/").lstrip("./"))


def _is_test_like(relpath: str) -> bool:
    low = relpath.lower()
    return "test" in low or "_scratch" in low


def load_repograph_refs(repo_path: str) -> Optional[List[Tuple[str, int]]]:
    path = os.path.join(repo_path, ".testing_agent", "repograph_result.json")
    if not os.path.exists(path):
        return None
    data = json.load(open(path, "r"))
    refs: List[Tuple[str, int]] = []

    if isinstance(data, dict) and "library_consumers" in data:
        ref_list = data.get("library_consumers", {}).get("references", []) or []
        for ref in ref_list:
            rel = _normalize_rel(ref.get("relative_path"))
            line = ref.get("line")
            if rel is None or line is None or line <= 0:
                continue
            if _is_test_like(rel):
                continue
            refs.append((rel, int(line)))
    else:
        for entry in data.values() if isinstance(data, dict) else []:
            for ref in entry.get("library_consumers", {}).get("references", []) or []:
                rel = _normalize_rel(ref.get("relative_path"))
                line = ref.get("line")
                if rel is None or line is None or line <= 0:
                    continue
                if _is_test_like(rel):
                    continue
                refs.append((rel, int(line)))

    seen = set()
    out: List[Tuple[str, int]] = []
    for rel, ln in refs:
        key = (rel, ln)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def load_repoyaml_refs(repo_path: str, name_map_path: str, repo_yaml_dir: str) -> Optional[List[Tuple[str, int]]]:
    repo_name = os.path.basename(repo_path.rstrip("/"))
    try:
        name_map = load_name_map(name_map_path)
    except FileNotFoundError:
        return None

    yaml_basename = name_map.get(repo_name)
    if not yaml_basename:
        return None
    yaml_path = os.path.join(repo_yaml_dir, f"{yaml_basename}.yaml")
    if not os.path.exists(yaml_path):
        return None

    data = yaml.safe_load(open(yaml_path, "r")) or {}
    refs: List[Tuple[str, int]] = []

    for file_entry in data.get("files", []) or []:
        rel = _normalize_rel(file_entry.get("path"))
        if rel is None or _is_test_like(rel):
            continue
        for change in file_entry.get("code_changes", []) or []:
            line_field = change.get("line")
            if not line_field:
                continue
            src_part = str(line_field).split(":")[0].strip()
            if not src_part:
                continue
            if "-" in src_part:
                start_str, end_str = src_part.split("-", 1)
                try:
                    start, end = int(start_str), int(end_str)
                except ValueError:
                    continue
                for ln in range(start, end + 1):
                    refs.append((rel, ln))
            else:
                try:
                    refs.append((rel, int(src_part)))
                except ValueError:
                    continue

    seen = set()
    out: List[Tuple[str, int]] = []
    for rel, ln in refs:
        key = (rel, ln)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def load_coverage_hits(repo_path: str, cov_path: Optional[str] = None) -> Optional[Dict[str, Set[int]]]:
    if cov_path is None:
        eval_cov = os.path.join(repo_path, ".testing_agent/coverage_eval.xml")
        if os.path.exists(eval_cov):
            cov_path = eval_cov
        else:
            cov_path = os.path.join(repo_path, ".testing_agent/coverage.xml")
    if not os.path.exists(cov_path):
        return None

    try:
        root = ET.parse(cov_path).getroot()
    except ET.ParseError:
        return None

    sources = [s.text for s in root.findall("./sources/source") if s.text]
    hits: Dict[str, Set[int]] = {}
    for cls in root.iter("class"):
        filename = cls.attrib.get("filename")
        if not filename:
            continue
        line_nodes = cls.find("lines")
        if line_nodes is None:
            continue
        line_hits = {int(line.attrib["number"]): int(line.attrib.get("hits", 0)) for line in line_nodes.iter("line")}
        abs_path: Optional[str] = None
        for src in sources:
            candidate = os.path.normpath(os.path.join(src, filename))
            if os.path.exists(candidate):
                abs_path = candidate
                break
        if abs_path is None:
            candidate = os.path.normpath(os.path.join(repo_path, filename))
            if os.path.exists(candidate):
                abs_path = candidate
        if abs_path is None:
            rel = os.path.normpath(filename)
        else:
            rel = os.path.relpath(abs_path, repo_path) if abs_path.startswith(repo_path) else os.path.normpath(filename)
        hits.setdefault(rel, set()).update({ln for ln, hv in line_hits.items() if hv > 0})
    return hits


def compute_hit_rate(refs: Optional[List[Tuple[str, int]]], hits: Optional[Dict[str, Set[int]]]) -> Tuple[str, List[str]]:
    if refs is None:
        return "N/A (no refs)", []
    if not refs:
        return "0/0 (0%)", []
    if hits is None:
        return f"0/{len(refs)} (0%) – no coverage data", [f"{rel}:{line}" for rel, line in refs]

    total = len(refs)
    missed: List[str] = []
    hit_count = 0
    for rel, line in refs:
        covered_lines = hits.get(rel)
        if covered_lines and line in covered_lines:
            hit_count += 1
        else:
            missed.append(f"{rel}:{line}")
    pct = round((hit_count / total) * 100, 1)
    return f"{hit_count}/{total} ({pct}%)", missed
