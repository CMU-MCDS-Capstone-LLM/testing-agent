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

    log_format = "[%(levelname)s] %(message)s"
    # log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    log_level = logging.DEBUG
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
