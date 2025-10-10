"""
Jedi LSP client using multilspy for semantic code analysis.
Provides utilities to resolve definitions and references by location or FQN.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, TypedDict
import uuid

from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from multilspy.multilspy_types import Hover, Location, UnifiedSymbolInformation

from lsp_repograph.core.lsp.jedi_language_server.custom_jedi_server import CustomJediServer


class DefinitionResult(TypedDict):
    """Typed dict for definition lookup results."""
    absolute_path: str
    line: int
    character: int
    hover_text: Optional[str]


class ReferenceResult(TypedDict):
    """Typed dict for reference lookup results."""
    absolute_path: str
    line: int
    character: int


class MultilspyLSPClient:
    """LSP client wrapper that exposes high-level definition/reference helpers."""

    def __init__(self, repo_path: str, custom_init_params: dict | None = None):
        """
        Initialize MultilspyLSPClient with optional custom initialization parameters.

        Args:
            repo_path: Path to repository root
            custom_init_params: Custom initialization parameters to override defaults.
        """
        self.repo_path = Path(repo_path).resolve()
        self.custom_init_params = custom_init_params
        self.server: Optional[SyncLanguageServer] = None
        self._initialize_multilspy()

    def _initialize_multilspy(self) -> None:
        """Initialize multilspy with Jedi configuration."""
        try:
            config = MultilspyConfig.from_dict(
                {
                    "code_language": "python",
                    "trace_lsp_communication": False,
                }
            )
            logger = MultilspyLogger()
            self.server = SyncLanguageServer(
                CustomJediServer(config, logger, str(self.repo_path), self.custom_init_params),
                timeout=None,
            )
        except Exception as exc:  # pragma: no cover - multilspy init errors surface directly
            raise RuntimeError(f"Failed to initialize multilspy: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_def_by_fqn(
        self,
        *,
        module: str,
        qualpath: Optional[str] = None,
        with_hover_msg: bool = True,
    ) -> Optional[DefinitionResult]:
        """Find the definition for a symbol identified by module and qualpath."""
        if not module:
            raise ValueError("'module' is required for find_def_by_fqn")

        scratch_content, target_line, target_char = self._build_scratch_snippet(module, qualpath)
        with self._scratch_file(scratch_content, target_line, target_char) as (scratch_path, line, char):
            return self._definition_from_position(
                str(scratch_path),
                line,
                char,
                with_hover_msg=with_hover_msg,
                scratch_path=scratch_path,
            )

    def find_refs_by_fqn(
        self,
        *,
        module: str,
        qualpath: Optional[str] = None,
    ) -> List[ReferenceResult]:
        """Find all references for a symbol identified by module and qualpath."""
        if not module:
            raise ValueError("'module' is required for find_refs_by_fqn")

        scratch_content, target_line, target_char = self._build_scratch_snippet(module, qualpath)
        with self._scratch_file(scratch_content, target_line, target_char) as (scratch_path, line, char):
            return self._references_from_position(
                str(scratch_path),
                line,
                char,
                scratch_path=scratch_path,
            )

    def find_def_by_loc(
        self,
        *,
        path: str,
        line: int,
        character: int,
        with_hover_msg: bool = True,
    ) -> Optional[DefinitionResult]:
        """Find the definition pointed to by a file location (relative or absolute path)."""
        abs_path = self._resolve_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {abs_path}")

        return self._definition_from_position(
            str(abs_path),
            line,
            character,
            with_hover_msg=with_hover_msg,
        )

    def find_refs_by_loc(
        self,
        *,
        path: str,
        line: int,
        character: int,
    ) -> List[ReferenceResult]:
        """Find all references for the symbol at a file location (relative or absolute path)."""
        abs_path = self._resolve_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found: {abs_path}")

        return self._references_from_position(str(abs_path), line, character)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> Path:
        """Convert relative or absolute path to absolute Path object."""
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        else:
            return self.repo_path / path_obj

    @contextmanager
    def _scratch_file(self, content: str, target_line: int, target_char: int) -> Iterable[Tuple[Path, int, int]]:
        scratch_filename = f"_scratch_{uuid.uuid4().hex[:8]}.py"
        scratch_path = self.repo_path / scratch_filename
        scratch_path.write_text(content)

        try:
            yield scratch_path, target_line, target_char
        finally:
            if scratch_path.exists():
                scratch_path.unlink()

    def _definition_from_position(
        self,
        absolute_path: str,
        line: int,
        character: int,
        *,
        with_hover_msg: bool,
        scratch_path: Optional[Path] = None,
    ) -> Optional[DefinitionResult]:
        if not self.server:
            return None

        with self.server.start_server():
            definitions = self.server.request_definition(absolute_path, line, character)
            if not isinstance(definitions, list) or not definitions:
                return None

            definition = self._first_non_scratch_definition(definitions, scratch_path)
            if not definition:
                return None

            result = self._format_location_for_definition(definition)
            if not result:
                return None

            hover_text = None
            if with_hover_msg:
                hover_response = self.server.request_hover(absolute_path, line, character)
                hover_text = self._extract_hover_text(hover_response)

            return DefinitionResult(
                absolute_path=result["absolute_path"],
                line=result["line"],
                character=result["character"],
                hover_text=hover_text,
            )

    def _references_from_position(
        self,
        absolute_path: str,
        line: int,
        character: int,
        *,
        scratch_path: Optional[Path] = None,
    ) -> List[ReferenceResult]:
        if not self.server:
            return []

        with self.server.start_server():
            references = self.server.request_references(absolute_path, line, character)
            if not isinstance(references, list):
                return []

            filtered: List[ReferenceResult] = []
            seen: set[Tuple[str, int, int]] = set()

            for ref in references:
                if self._is_in_venv(ref):
                    continue
                if scratch_path and self._is_scratch_file_ref(ref, scratch_path):
                    continue

                formatted = self._format_location_for_reference(ref)
                if not formatted:
                    continue

                key = (formatted["absolute_path"], formatted["line"], formatted["character"])
                if key in seen:
                    continue
                seen.add(key)
                filtered.append(formatted)

            return filtered

    def _first_non_scratch_definition(
        self,
        definitions: Iterable[Location],
        scratch_path: Optional[Path],
    ) -> Optional[Location]:
        for definition in definitions:
            if scratch_path and self._is_scratch_file_ref(definition, scratch_path):
                continue
            return definition
        return None

    def _format_location_for_definition(self, definition: Location) -> Optional[DefinitionResult]:
        file_path = self._extract_absolute_path(definition)
        if not file_path:
            return None

        line, character = self._extract_position(definition)
        return DefinitionResult(
            absolute_path=file_path,
            line=line,
            character=character,
            hover_text=None,
        )

    def _format_location_for_reference(self, reference: Location) -> Optional[ReferenceResult]:
        file_path = self._extract_absolute_path(reference)
        if not file_path:
            return None

        line, character = self._extract_position(reference)
        return ReferenceResult(
            absolute_path=file_path,
            line=line,
            character=character,
        )

    def _extract_absolute_path(self, location: Location | UnifiedSymbolInformation) -> Optional[str]:
        if "absolutePath" in location and location["absolutePath"]:
            return str(location["absolutePath"])

        if "uri" in location and location["uri"]:
            uri = location["uri"]
            if uri.startswith("file://"):
                return uri[7:]
            return uri

        if "location" in location:
            inner = location["location"]
            if "uri" in inner:
                uri = inner["uri"]
                if uri.startswith("file://"):
                    return uri[7:]
                return uri

        return None

    def _extract_position(self, location: Location | UnifiedSymbolInformation) -> Tuple[int, int]:
        if "range" in location:
            range_info = location["range"]
        elif "location" in location and "range" in location["location"]:
            range_info = location["location"]["range"]
        else:
            return 0, 0

        start = range_info.get("start", {})
        return int(start.get("line", 0)), int(start.get("character", 0))

    def _build_scratch_snippet(self, module: str, qualpath: Optional[str]) -> Tuple[str, int, int]:
        alias = "__m"

        if qualpath:
            import_line = f"import {module} as {alias}\n"
            access_expr = f"{alias}.{qualpath}"
            scratch_content = f"{import_line}{access_expr}\n"
            target_line = 1
            target_char = max(len(access_expr) - 1, 0)
        else:
            import_stmt = f"import {module}"
            scratch_content = f"{import_stmt}\n"
            target_line = 0
            target_char = max(len(import_stmt) - 1, 0)

        return scratch_content, target_line, target_char

    def _extract_hover_text(self, hover_response: Optional[Hover]) -> Optional[str]:
        if not hover_response or not isinstance(hover_response, dict):
            return None

        contents = hover_response.get("contents")
        if not contents:
            return None

        if isinstance(contents, str):
            return contents.strip() or None

        if isinstance(contents, dict):
            value = contents.get("value") or contents.get("contents")
            if isinstance(value, str):
                cleaned = value.strip()
                return cleaned or None
            return None

        if isinstance(contents, list):
            parts: List[str] = []
            for entry in contents:
                if isinstance(entry, str):
                    stripped = entry.strip()
                    if stripped:
                        parts.append(stripped)
                elif isinstance(entry, dict):
                    value = entry.get("value") or entry.get("contents")
                    if isinstance(value, str):
                        stripped = value.strip()
                        if stripped:
                            parts.append(stripped)
            joined = "\n".join(parts)
            return joined or None

        return None

    def _is_in_venv(self, reference: Location) -> bool:
        """Return True when a reference resides inside a virtual environment path."""
        paths_to_check: List[str] = []

        if "absolutePath" in reference and reference["absolutePath"]:
            paths_to_check.append(str(reference["absolutePath"]))
        if "relativePath" in reference and reference["relativePath"]:
            paths_to_check.append(str(reference["relativePath"]))
        if "uri" in reference and reference["uri"]:
            uri = reference["uri"]
            if uri.startswith("file://"):
                paths_to_check.append(uri[7:])

        venv_patterns = [
            "/venv/",
            "\\venv\\",
            "/env/",
            "\\env\\",
            "/.venv/",
            "\\.venv\\",
            "/site-packages/",
            "\\site-packages\\",
            "/lib/python",
            "\\lib\\python",
            "/Scripts/",
            "\\Scripts\\",
            "/bin/python",
            "\\bin\\python",
        ]

        for path in paths_to_check:
            lowered = path.lower()
            if any(pattern in lowered for pattern in venv_patterns):
                return True
        return False

    def _is_scratch_file_ref(self, reference: Location, scratch_path: Path) -> bool:
        scratch_path_str = str(scratch_path)

        if "absolutePath" in reference and reference["absolutePath"] == scratch_path_str:
            return True

        if "relativePath" in reference and reference["relativePath"]:
            relative_abs = str(self.repo_path / reference["relativePath"])
            if relative_abs == scratch_path_str:
                return True

        if "uri" in reference and reference["uri"]:
            uri = reference["uri"]
            if uri.startswith("file://") and uri[7:] == scratch_path_str:
                return True

        if "location" in reference:
            location = reference["location"]
            if isinstance(location, dict):
                uri = location.get("uri")
                if isinstance(uri, str) and uri.startswith("file://") and uri[7:] == scratch_path_str:
                    return True

        return False

    def shutdown(self) -> None:
        """Release the cached server reference (multilspy handles lifecycle)."""
        self.server = None

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        self.shutdown()
