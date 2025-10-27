#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_CONFIG="$SCRIPT_DIR/config.yaml"

CONFIG_PATH="${1:-$DEFAULT_CONFIG}"
shift || true

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Configuration file not found: $CONFIG_PATH" >&2
  exit 1
fi

export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

LOG_PATH=$(python3 - "$CONFIG_PATH" <<'PY'
import sys
from pathlib import Path

from testing_agent.config_loader import TestingAgentConfig

config = TestingAgentConfig.from_yaml(Path(sys.argv[1]))
print(config.log_file)
PY
)

LOG_PATH="${LOG_PATH//$'\n'/}"

if [ -n "$LOG_PATH" ]; then
  mkdir -p "$(dirname "$LOG_PATH")"
  : > "$LOG_PATH"
  echo "Logs will be written to $LOG_PATH"
  python3 -m testing_agent.main --config "$CONFIG_PATH" "$@" >> "$LOG_PATH" 2>&1
else
  python3 -m testing_agent.main --config "$CONFIG_PATH" "$@"
fi
