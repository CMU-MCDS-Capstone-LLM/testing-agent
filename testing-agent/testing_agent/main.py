"""CLI entry point for the testing agent workflow."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

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

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="[%(levelname)s] %(message)s",
    )

    config = TestingAgentConfig.from_yaml(Path(args.config))
    agent = TestingAgent(config=config)
    agent.run()


if __name__ == "__main__":
    main()
