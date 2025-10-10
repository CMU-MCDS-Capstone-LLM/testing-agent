#!/bin/bash
# config.sh: Configuration for automate.sh script.

# --- API Keys ---
# Set your primary API key for OpenAI. This is the key used by default.

# # If you want to use the school-provided API (via litellm.completion), set the school key.
# # In your Python code, use os.environ.get("LITELLM_API_KEY") to access it.
# export LITELLM_API_KEY="your_school_api_key_here"

# --- Cover-Agent Configuration ---
# These variables make it easy to change the command-line arguments for cover-agent.

# Derive repo name from GitHub URL if provided, otherwise use default
echo "DEBUG: GITHUB_URL='${GITHUB_URL:-}'"
echo "DEBUG: LOCAL_REPO_MODE='${LOCAL_REPO_MODE:-}'"
echo "DEBUG: REPO_NAME='${REPO_NAME:-}'"

if [ "${LOCAL_REPO_MODE:-}" = "1" ]; then
    # Local repo mode - use the repo name from environment or auto-detect
    if [ -z "${REPO_NAME:-}" ]; then
        REPO_NAME=$(ls /workspace | head -1)
        echo "DEBUG: Auto-detected REPO_NAME='$REPO_NAME'"
    fi
    PROJECT_ROOT="/workspace/$REPO_NAME"
    echo "DEBUG: LOCAL_REPO_MODE - PROJECT_ROOT='$PROJECT_ROOT'"
elif [ -n "${GITHUB_URL:-}" ]; then
    # GitHub mode - derive from URL
    REPO_PATH=$(printf "%s" "$GITHUB_URL" | sed -E 's#^.*github.com[/:]+##' | sed -E 's#\\.git$##')
    echo "DEBUG: REPO_PATH='$REPO_PATH'"
    ORG="${REPO_PATH%%/*}"
    REPO="${REPO_PATH##*/}"
    echo "DEBUG: ORG='$ORG', REPO='$REPO'"
    REPO_NAME="${ORG}__${REPO}"
    PROJECT_ROOT="/workspace/$REPO_NAME"
    echo "DEBUG: REPO_NAME='$REPO_NAME', PROJECT_ROOT='$PROJECT_ROOT'"
else
    PROJECT_ROOT="/workspace/keep2roam"
    echo "DEBUG: Using default PROJECT_ROOT='$PROJECT_ROOT'"
fi

CODE_COVERAGE_REPORT_PATH="$PROJECT_ROOT/tests/coverage.xml"
TEST_COMMAND="pytest --cov=.. --cov-report=xml --cov-report=term"
TEST_COMMAND_DIR="$PROJECT_ROOT/tests"
COVERAGE_TYPE="cobertura"
DESIRED_COVERAGE=90
MAX_ITERATIONS=8
ADDITIONAL_INSTRUCTIONS=""

# --- Environment and Output Setup ---
TEST_REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"  # requirements of the repo generating test for
OUTPUT_FILE="$TEST_COMMAND_DIR/testing_agent_output.txt"
