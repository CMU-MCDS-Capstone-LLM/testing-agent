#!/bin/bash
# config.sh: Configuration for automate.sh script.

# --- API Keys ---
# Set your primary API key for OpenAI. This is the key used by default.

# # If you want to use the school-provided API (via litellm.completion), set the school key.
# # In your Python code, use os.environ.get("LITELLM_API_KEY") to access it.
# export LITELLM_API_KEY="your_school_api_key_here"

# --- Cover-Agent Configuration ---
# These variables make it easy to change the command-line arguments for cover-agent.
PROJECT_ROOT="keep2roam"
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
