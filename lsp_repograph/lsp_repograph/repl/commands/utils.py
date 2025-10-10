from __future__ import annotations

from typing import Tuple



def read_file_line(file_path: str, line_number: int) -> str:
    """Read a specific line from a file (0-indexed)."""
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except Exception as exc:  # pragma: no cover - IO errors surface to user directly
        return f"<Error reading file: {exc}>"

    if 0 <= line_number < len(lines):
        return lines[line_number].rstrip("\n")
    return "<Line not found>"


def format_location_for_display(path: str, line: int, character: int) -> Tuple[str, str]:
    """Produce display strings for definition/reference printing."""
    header = f"File \"{path}\", line {line}, character {character}"
    content = read_file_line(path, line)
    return header, content
