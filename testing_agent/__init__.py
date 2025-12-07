"""Testing agent package entry point."""

import os
import sys

# Ensure package-local imports work when running from repo root
sys.path.append(os.path.dirname(__file__))

from .config_loader import TestingAgentConfig
from .testing_agent import TestingAgent  # noqa: F401

__all__ = ["TestingAgent", "TestingAgentConfig"]
