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


class FindDefByFqnCommand(Command):
    """Find definition using a module + qualpath FQN."""

    @property
    def name(self) -> str:  # pragma: no cover - trivial property
        return "find-def-by-fqn"

    @property
    def description(self) -> str:  # pragma: no cover
        return "Find the definition location for <module>:<qualpath> (hover optional)."

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            add_help=False
        )
        parser.add_argument('--module', required=True,
                          help='Module name (e.g., collections, numpy)')
        parser.add_argument('--qualpath', required=False,
                          help='Qualified path within module (e.g., deque.popleft)')
        parser.add_argument('--with_hover_msg', type=str2bool, default=True,
                          help='Include hover text (true/false, default: true)')
        return parser

    def execute(self, client: MultilspyLSPClient, args: List[str]) -> None:
        try:
            parsed_args = self.get_parser().parse_args(args)
        except SystemExit:
            # argparse calls sys.exit on error, we catch this to prevent REPL from exiting
            return

        symbol_display = f"{parsed_args.module}:{parsed_args.qualpath}" if parsed_args.qualpath else parsed_args.module

        try:
            result = client.find_def_by_fqn(
                module=parsed_args.module,
                qualpath=parsed_args.qualpath,
                with_hover_msg=parsed_args.with_hover_msg
            )
        except Exception as exc:  # pragma: no cover - surfaces runtime issues to user
            print(f"No definition found for {symbol_display}")
            return

        if not result:
            print(f"No definition found for {symbol_display}")
            return

        path = result["absolute_path"]
        line = result["line"]
        character = result["character"]

        print(f"Found definition of {symbol_display} in file \"{path}\", line {line}, character {character}")
        _, content = format_location_for_display(path, line, character)
        print(content)

        hover_text = result.get("hover_text")
        if parsed_args.with_hover_msg and hover_text:
            print("\nHover Text:")
            print(hover_text)


class FindRefsByFqnCommand(Command):
    """Find references using a module + qualpath FQN."""

    @property
    def name(self) -> str:  # pragma: no cover
        return "find-refs-by-fqn"

    @property
    def description(self) -> str:  # pragma: no cover
        return "List all references for <module>:<qualpath>."

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.description,
            add_help=False
        )
        parser.add_argument('--module', required=True,
                          help='Module name (e.g., collections, numpy)')
        parser.add_argument('--qualpath', required=False,
                          help='Qualified path within module (e.g., deque.popleft)')
        return parser

    def execute(self, client: MultilspyLSPClient, args: List[str]) -> None:
        try:
            parsed_args = self.get_parser().parse_args(args)
        except SystemExit:
            # argparse calls sys.exit on error, we catch this to prevent REPL from exiting
            return

        symbol_display = f"{parsed_args.module}:{parsed_args.qualpath}" if parsed_args.qualpath else parsed_args.module

        try:
            references = client.find_refs_by_fqn(
                module=parsed_args.module,
                qualpath=parsed_args.qualpath
            )
        except Exception as exc:  # pragma: no cover
            print(f"Error executing reference lookup: {exc}")
            return

        print(f"Found {len(references)} references of {symbol_display} at these locations")

        if not references:
            return

        for ref in references:
            path = ref["absolute_path"]
            line = ref["line"]
            character = ref["character"]
            header, content = format_location_for_display(path, line, character)
            print(f"\n{header}")
            print(content)
