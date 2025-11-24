"""CLI entry point for the testing agent workflow."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from testing_agent import TestingAgent, TestingAgentConfig


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the testing agent workflow")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML configuration file (default: %(default)s)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    config = TestingAgentConfig.from_yaml(Path(args.config))

    # Append PASS-TO-PASS testing rules to ensure framework-neutral tests
    PASS_TO_PASS_RULES = """---

***** CRITICAL GLOBAL RULES FOR PASS-TO-PASS TESTS *****

You are generating PASS-TO-PASS Python unit tests.

HARD REQUIREMENT: FRAMEWORK/LIBRARY NEUTRAL TESTING
These frameworks MUST NEVER be imported directly:
    flask, flask_restful, fastapi, django,
    argparse, click, requests, httpx,
    starlette, sanic, aiohttp, pydantic

Instead:
- ALWAYS replace framework/library classes with mocks
- Use: from unittest.mock import patch, MagicMock
- ALWAYS test structure, NOT framework behavior
- NEVER assert real framework types

PASS-TO-PASS TESTS MUST:
- Never import libraryA
- Never import libraryB
- Never assert Client from either library
- Never call real Client()
- Only mock when needed: @patch("module.Client", MagicMock())

EXAMPLE - GOOD TEST (correct):
    def test_module_initialization():
        import mymodule
        assert hasattr(mymodule, "ClientWrapper")

EXAMPLE - BETTER TEST (when Client is required):
    from unittest.mock import patch, MagicMock

    @patch("mymodule.Client", MagicMock())
    def test_wrapper_works_with_mock():
        import mymodule
        wrapper = mymodule.ClientWrapper()
        assert wrapper is not None

EXAMPLE - BAD TESTS (NEVER DO):
    from libraryA import Client       # ❌ forbidden
    from libraryB import Client       # ❌ forbidden
    real_client = Client()            # ❌ forbidden
    assert isinstance(wrapper.client, Client)   # ❌ framework-dependent

Key principle: Test the CALLER (code that uses A/B), NOT the libraries A/B directly.
Tests must be invariant across migration.

***** END OF CRITICAL GLOBAL RULES *****"""

    # Append to existing additional_instructions if it exists
    if config.additional_instructions:
        config.additional_instructions = config.additional_instructions + "\n" + PASS_TO_PASS_RULES
    else:
        config.additional_instructions = PASS_TO_PASS_RULES

    log_format = "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d: %(message)s"
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    handlers = [
        logging.StreamHandler(sys.stdout)
    ]

    if config.log_file:
        config.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(config.log_file, mode="w", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)

    logging.basicConfig(level=log_level, format=log_format, handlers=handlers)

    try:
        agent = TestingAgent(config=config)
        agent.run()
    except Exception as e:
        logging.exception(f"Failed to run testing agent. Got error: {e}")


if __name__ == "__main__":
    main()
