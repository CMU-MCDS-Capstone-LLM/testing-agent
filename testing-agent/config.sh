#!/bin/bash
# config.sh: Configuration for automate.sh script.

# --- API Keys ---
# Set your primary API key for OpenAI. This is the key used by default.

# # If you want to use the school-provided API (via litellm.completion), set the school key.
# # In your Python code, use os.environ.get("LITELLM_API_KEY") to access it.
# export LITELLM_API_KEY="your_school_api_key_here"

# --- Global Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Cover-Agent Configuration ---
# These variables make it easy to change the command-line arguments for cover-agent.
REPO_NAME="keep2roam"
# Auto-detect if running locally or in container
if [ -d "/demos/$REPO_NAME" ]; then
    PROJECT_ROOT="/demos/$REPO_NAME"
else
    PROJECT_ROOT="$ROOT_DIR/demos/$REPO_NAME"
fi
CODE_COVERAGE_REPORT_PATH="$PROJECT_ROOT/.pytest_cache/coverage.xml"
TEST_COMMAND="pytest"
TEST_COMMAND_DIR="$PROJECT_ROOT/tests"
COVERAGE_TYPE="cobertura"
DESIRED_COVERAGE=90
MAX_ITERATIONS=10
MODEL="openai/gpt-4o"
API_BASE="https://cmu.litellm.ai" 
ADDITIONAL_INSTRUCTIONS="
Only mock external dependencies; never patch functions or classes defined inside the source file under test.
Let the real implementation run; patch file, network, or database I/O only when necessary, and patch each target (for example, builtins.open) once per test.

When you need path-like objects, prefer real Path(...) instances. If you must mock path.joinpath(), assign a Mock to the return value and configure is_file() and suffix instead of chaining return_value assignments.

Import helpers from the source module directly (e.g., from convert import open_note, write_or_append_note, convert, run_parser) and call them by name. Avoid patterns such as convert.convert(...).
If the production code filters resources (Path.iterdir, os.listdir, etc.), configure mocks so the predicates remain true—return objects where is_file() is True and suffix equals '.json'.
Whenever you mock domain objects (Notes, etc.), set every attribute or method that the production code touches, or build real instances via project utilities.

Focus on uncovered lines from the latest coverage report. Skip tests that would only exercise code that already has non-zero hits.

Coverage priorities for convert.py:
  1. If lines 18-20 (the open_note exception handler) remain uncovered, you MUST generate a test that triggers NoteSchema().load to raise, asserts SystemExit, and confirms the printed Path appears in stdout. Treat this as mandatory even though it is an error branch.
  2. If the module entry glue (lines around main()) is still uncovered, import convert as convert_module, patch run_parser/convert, invoke convert_module.main(), and assert the helpers are called with the expected arguments. Do not create duplicate tests if this behavior is already covered in the current suite.

Generate normal (happy-path) scenarios first, but fulfil the mandatory exception-path test above whenever those lines are uncovered.
Ensure each proposed test adds new line or branch coverage; skip any test that duplicates existing behavior.
"

# --- Environment and Output Setup ---
REPO_REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"
INSTALL_REPO_DEPS_WITH_NODEPS=false
TEST_REQUIREMENTS_FILE=""
OUTPUT_FILE="$TEST_COMMAND_DIR/testing_agent_output.txt"

# --- LSP-Repograph Configuration ---
if [ -f "/demos/${REPO_NAME}_commit.yaml" ]; then
    MIGRATION_CONFIG="/demos/${REPO_NAME}_commit.yaml"
else
    MIGRATION_CONFIG="$ROOT_DIR/demos/${REPO_NAME}_commit.yaml"
fi
# Auto-detect Python: use container path if exists, otherwise find local python3
if [ -x "/usr/local/bin/python" ]; then
    REPO_VENV_PYTHON="/usr/local/bin/python"
else
    REPO_VENV_PYTHON="$(command -v python3 || command -v python)"
fi
# REPO_SITE_PACKAGES="$PROJECT_ROOT/.venv/lib/python3.13/site-packages"
SELECTOR_OUTPUT="repograph_runner/output/repograph_result.json"

# Override pytest arguments (can be empty; build_pytest_args.py will fill as needed)
PYTEST_COV_TARGET=""
PYTEST_INCLUDE_EXPR=""
PYTEST_EXCLUDE_EXPR=""
