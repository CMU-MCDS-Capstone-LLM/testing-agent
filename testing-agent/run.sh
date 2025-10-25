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

python3 -m testing_agent.main --config "$CONFIG_PATH" "$@"
