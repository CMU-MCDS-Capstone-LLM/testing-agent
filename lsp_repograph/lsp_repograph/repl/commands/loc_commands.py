from __future__ import annotations

import argparse
from typing import List

from .base import Command
from .utils import format_location_for_display
from lsp_repograph.core.multilspy_client import MultilspyLSPClient


def str2bool(v: str) -> bool:
    """Convert string to boolean for argparse."""
    if v.lower() in {'true', '1', 'yes', 'y'}:
        return True
    elif v.lower() in {'false', '0', 'no', 'n'}:
        return False
    else:
        raise argparse.ArgumentTypeError(f'Boolean value expected, got: {v}')


class FindDefByLocCommand(Command):
    """Find definition by caret location."""

    @property
    def name(self) -> str:  # pragma: no cover
        return "find-def-by-loc"

    @property
    def description(self) -> str:  # pragma: no cover
        return "Resolve definition from a file position (relative or absolute path, hover optional)."

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            add_help=False
        )
        parser.add_argument('--path', required=True,
                          help='File path (relative or absolute)')
        parser.add_argument('--line', type=int, required=True,
                          help='Line number (0-indexed)')
        parser.add_argument('--character', type=int, required=True,
                          help='Character position (0-indexed)')
        parser.add_argument('--with_hover_msg', type=str2bool, default=True,
                          help='Include hover text (true/false, default: true)')
        return parser

    def execute(self, client: MultilspyLSPClient, args: List[str]) -> None:
        try:
            parsed_args = self.get_parser().parse_args(args)
        except SystemExit:
            # argparse calls sys.exit on error, we catch this to prevent REPL from exiting
            return

        try:
            result = client.find_def_by_loc(
                path=parsed_args.path,
                line=parsed_args.line,
                character=parsed_args.character,
                with_hover_msg=parsed_args.with_hover_msg,
            )
        except Exception as exc:  # pragma: no cover
            print("No definition found for the supplied location")
            return

        if not result:
            print("No definition found for the supplied location")
            return

        path = result["absolute_path"]
        line_num = result["line"]
        char_num = result["character"]

        print(
            "Found definition at file \"{path}\", line {line}, character {char}".format(
                path=path,
                line=line_num,
                char=char_num,
            )
        )
        _, content = format_location_for_display(path, line_num, char_num)
        print(content)

        hover_text = result.get("hover_text")
        if parsed_args.with_hover_msg and hover_text:
            print("\nHover Text:")
            print(hover_text)


class FindRefsByLocCommand(Command):
    """Find references by caret location."""

    @property
    def name(self) -> str:  # pragma: no cover
        return "find-refs-by-loc"

    @property
    def description(self) -> str:  # pragma: no cover
        return "List all references for the symbol at a file position (relative or absolute path)."

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            add_help=False
        )
        parser.add_argument('--path', required=True,
                          help='File path (relative or absolute)')
        parser.add_argument('--line', type=int, required=True,
                          help='Line number (0-indexed)')
        parser.add_argument('--character', type=int, required=True,
                          help='Character position (0-indexed)')
        return parser

    def execute(self, client: MultilspyLSPClient, args: List[str]) -> None:
        try:
            parsed_args = self.get_parser().parse_args(args)
        except SystemExit:
            # argparse calls sys.exit on error, we catch this to prevent REPL from exiting
            return

        try:
            references = client.find_refs_by_loc(
                path=parsed_args.path,
                line=parsed_args.line,
                character=parsed_args.character
            )
        except Exception as exc:  # pragma: no cover
            print(f"Error executing reference lookup: {exc}")
            return

        print(
            "Found {count} references for location {path}:{line}:{char}".format(
                count=len(references),
                path=parsed_args.path,
                line=parsed_args.line,
                char=parsed_args.character,
            )
        )

        if not references:
            return

        for ref in references:
            path = ref["absolute_path"]
            line_num = ref["line"]
            char_num = ref["character"]
            header, content = format_location_for_display(path, line_num, char_num)
            print(f"\n{header}")
            print(content)
