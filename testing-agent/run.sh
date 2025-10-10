#!/bin/bash
# run.sh - Automates environment setup, test file generation, and code coverage analysis.
#
# Usage: ./run.sh
# All configuration parameters are loaded from config.sh

# --- Load configuration ---
if [ -f ./config.sh ]; then
    source ./config.sh
else
    echo "Error: config.sh not found. Please create the config file with your settings."
    exit 1
fi

# --- 1. Clean up any stale flags ---
TESTING_COMPLETE_FLAG="/workspace/${REPO_NAME}/testing_complete.flag"
if [ -f "$TESTING_COMPLETE_FLAG" ]; then
    echo "DEBUG: Removing stale testing completion flag..."
    rm -f "$TESTING_COMPLETE_FLAG"
fi

# --- 2. Export API Keys ---
export OPENAI_API_KEY
# Only export LITELLM_API_KEY if it's defined
# if [ ! -z "$LITELLM_API_KEY" ]; then
#     export LITELLM_API_KEY
# fi
echo "API keys exported."

# --- 2. Install Dependencies ---
# Install packages in the current environment.
# Install repo requirements first, then reinstall testing requirements to ensure compatibility
REQUIREMENTS_FOUND=0
if [ -n "${PROJECT_ROOT:-}" ]; then
    # Try setup.py first (includes install_requires dependencies)
    if [ -f "$PROJECT_ROOT/setup.py" ]; then
        echo "Found setup.py, installing package with dependencies..."
        (cd "$PROJECT_ROOT" && pip install -e . 2>&1)
        if [ $? -eq 0 ]; then
            echo "Successfully installed package from setup.py"
        else
            echo "Warning: setup.py installation had issues, but continuing..."
        fi
        REQUIREMENTS_FOUND=1
    fi
    
    # Try pyproject.toml 
    if [ -f "$PROJECT_ROOT/pyproject.toml" ] && [ $REQUIREMENTS_FOUND -eq 0 ]; then
        echo "Found pyproject.toml, installing package with dependencies..."
        (cd "$PROJECT_ROOT" && pip install -e .) 2>&1 | tail -1
        REQUIREMENTS_FOUND=1
    fi
    
    # Try requirements.txt files
    for REQ_FILE in "$PROJECT_ROOT/requirements.txt" "$PROJECT_ROOT/requirements/base.txt" "$PROJECT_ROOT/requirements/dev.txt"; do
        if [ -f "$REQ_FILE" ]; then
            echo "Installing dependencies from $REQ_FILE..."
            pip install --no-cache-dir -r "$REQ_FILE" > /dev/null 2>&1 || true
            REQUIREMENTS_FOUND=1
        fi
    done
    
    # Try Pipfile (using pipenv)
    if [ -f "$PROJECT_ROOT/Pipfile" ]; then
        echo "Found Pipfile, installing dependencies..."
        pip install --no-cache-dir pipenv > /dev/null 2>&1 || true
        (cd "$PROJECT_ROOT" && pipenv install --system --skip-lock) > /dev/null 2>&1 || true
        REQUIREMENTS_FOUND=1
    fi
    
    if [ $REQUIREMENTS_FOUND -eq 0 ]; then
        echo "Warning: No dependency files found."
    fi
fi

# Always reinstall testing requirements last to ensure wandb/urllib3 compatibility
pip install --force-reinstall --no-cache-dir urllib3==1.26.20 wandb>=0.16.0 > /dev/null 2>&1 || true


# --- 3. Create Test Folder and File & Run Coverage Analysis ---
echo "Setting up test environment in $PROJECT_ROOT"

# Remove stale flags from previous runs (volume persists across runs)
READY_FILE="$PROJECT_ROOT/test_ready.flag"
[ -f "$READY_FILE" ] && echo "DEBUG: Removing stale ready flag at '$READY_FILE'" && rm -f "$READY_FILE"

# Also remove the testing_complete.flag from previous runs
TESTING_COMPLETE_FLAG="$PROJECT_ROOT/testing_complete.flag"
[ -f "$TESTING_COMPLETE_FLAG" ] && echo "DEBUG: Removing stale testing_complete flag at '$TESTING_COMPLETE_FLAG'" && rm -f "$TESTING_COMPLETE_FLAG"

# Ensure tests dir exists before touching output file
mkdir -p "$TEST_COMMAND_DIR"
# Clear the output file before appending (create if missing)
: > "$OUTPUT_FILE"

# (a) Create tests folder if it does not exist
if [ ! -d "$TEST_COMMAND_DIR" ]; then
    echo "Tests folder not found. Creating folder: $TEST_COMMAND_DIR"
    mkdir -p "$TEST_COMMAND_DIR"
else
    echo "Tests folder exists: $TEST_COMMAND_DIR"
fi

# Defer readiness signal until after tests are generated and processing completes
READY_FILE="$PROJECT_ROOT/test_ready.flag"
echo "DEBUG: PROJECT_ROOT='$PROJECT_ROOT'"

# (b) Ensure tests/conftest.py exists to patch sys.path
CONFTEST="$TEST_COMMAND_DIR/conftest.py"
if [ ! -f "$CONFTEST" ]; then
  cat > "$CONFTEST" <<'PY'
# [AUTO] ensure package root is on sys.path for imports like 'from models import X'
import sys, pathlib
_pkg_root = pathlib.Path(__file__).resolve().parents[1]  # .../<pkg>
p = str(_pkg_root)
if p not in sys.path:
    sys.path.insert(0, p)
PY
  echo "Created $CONFTEST"
fi


export PYTHONPATH="$(cd "$PROJECT_ROOT" && pwd):$(cd "$PROJECT_ROOT/.." && pwd):${PYTHONPATH}"
PKG_NAME="$(basename "$PROJECT_ROOT")" 

# Get Python files from the project root to test
PYTHON_FILES=$(find "$PROJECT_ROOT" -name "*.py" -not -path "*/\.*" -not -path "*/test*" -not -path "*/venv*")
echo "Found $(echo "$PYTHON_FILES" | wc -l) Python files to process"

# Process each Python file
while read -r SOURCE_PATH; do
    if [ -z "$SOURCE_PATH" ]; then
        continue
    fi
    
        echo "Processing: $SOURCE_PATH"

    BASENAME=$(basename "$SOURCE_PATH")
    NAME_NO_EXT="${BASENAME%.py}"

    # --- Resolve TEST_FILE: prefer existing repo tests, else create in TEST_COMMAND_DIR ---
    mapfile -t TEST_CANDIDATES < <( \
      find "$PROJECT_ROOT" -type f \
        \( -name "test_${BASENAME}" -o -name "test_${NAME_NO_EXT}.py" -o -name "${NAME_NO_EXT}_test.py" \) \
        -not -path "*/venv*" -not -path "*/.*" \
        2>/dev/null | sort \
    )

    BEST_MATCH=""
    if [ ${#TEST_CANDIDATES[@]} -gt 0 ]; then
        for p in "${TEST_CANDIDATES[@]}"; do
            if [[ "$p" == *"/tests/"* || "$p" == *"/test/"* ]]; then
                BEST_MATCH="$p"
                break
            fi
        done
        if [ -z "$BEST_MATCH" ]; then
            BEST_MATCH="${TEST_CANDIDATES[0]}"
        fi
    fi

    if [ -n "$BEST_MATCH" ]; then
        TEST_FILE="$BEST_MATCH"
        echo "Found existing test file: $TEST_FILE"
        NEWLY_CREATED=0
    else
        TEST_FILE="${TEST_COMMAND_DIR}/test_${BASENAME}"
        NEWLY_CREATED=1
        mkdir -p "$(dirname "$TEST_FILE")"
        echo "No existing test file found. Will create: $TEST_FILE"
    fi

    if [ $NEWLY_CREATED -eq 1 ] && [ ! -f "$TEST_FILE" ]; then
        cat > "$TEST_FILE" <<'EOF'
# do not delete this comment, this is where pytest adding import pkg msg
def test_dummy():
    assert True  # dummy test - placeholder for future tests
EOF

        # Detect the actual Python package name by finding the first package directory
        PKG_NAME=$(find "$PROJECT_ROOT" -maxdepth 2 -type f -name "__init__.py" ! -path "*/test*" ! -path "*/.*" -exec dirname {} \; | head -1 | xargs basename 2>/dev/null || basename "$PROJECT_ROOT" | tr '-' '_')
        IMPORT_BLOCK=$(
python - "$SOURCE_PATH" "$PKG_NAME" <<'PY'
import ast, sys, pathlib, re
src = pathlib.Path(sys.argv[1])
pkg = sys.argv[2]
code = src.read_text(encoding="utf-8", errors="ignore")
tree = ast.parse(code, filename=str(src))
lines = code.splitlines()

# 1) contiguous top-of-file imports
imports = []
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        imports.extend(lines[start:end])
    else:
        break

# 2) de-dup while preserving order
seen, out = set(), []
for l in imports:
    if l not in seen:
        out.append(l); seen.add(l)

# 3) rewrite relative imports to absolute (package-rooted)
def rewrite(line: str) -> str:
    m = re.match(r'^(\s*from\s+)(\.+)([A-Za-z_][\w\.]*)(\s+import\b.*)$', line)
    if m:
        return f"{m.group(1)}{pkg}.{m.group(3)}{m.group(4)}"
    return line

print("\n".join(rewrite(l) for l in out))
PY
)



        if [ -n "$IMPORT_BLOCK" ] && ! grep -q "^# \[AUTO-IMPORTED FROM SOURCE\]" "$TEST_FILE"; then
            TMP_FILE="$(mktemp)"
            {
                echo "# [AUTO-IMPORTED FROM SOURCE] — do not edit below manually"
                printf "%s\n\n" "$IMPORT_BLOCK"
                cat "$TEST_FILE"
            } > "$TMP_FILE" && mv "$TMP_FILE" "$TEST_FILE"
            echo "Inserted source imports into $TEST_FILE"
        else
            echo "No imports found to insert (or already inserted)."
        fi
    else
        echo "Test file ready: $TEST_FILE"
    fi

    
    # Run the cover-agent command for this Python file
    echo "Running cover-agent for source file: $SOURCE_PATH and test file: $TEST_FILE"
    echo "======================================" >> "$OUTPUT_FILE"
    echo "Processing: $SOURCE_PATH" >> "$OUTPUT_FILE"
    echo "Test file: $TEST_FILE" >> "$OUTPUT_FILE"
    echo "======================================" >> "$OUTPUT_FILE"
    
    # Run cover-agent with parameters from config.sh
    echo "DEBUG: OPENAI_API_KEY is set to: $OPENAI_API_KEY" >> "$OUTPUT_FILE"
    echo "DEBUG: GITHUB_TOKEN is set to: $GITHUB_TOKEN" >> "$OUTPUT_FILE"

    OPENAI_API_KEY="$OPENAI_API_KEY" GITHUB_TOKEN="$GITHUB_TOKEN" python /app/cover_agent/main.py \
        --source-file-path "$SOURCE_PATH" \
        --test-file-path "$TEST_FILE" \
        --project-root "$PROJECT_ROOT" \
        --code-coverage-report-path "$CODE_COVERAGE_REPORT_PATH" \
        --test-command "$TEST_COMMAND" \
        --test-command-dir "$TEST_COMMAND_DIR" \
        --coverage-type "$COVERAGE_TYPE" \
        --desired-coverage "$DESIRED_COVERAGE" \
        --max-iterations "$MAX_ITERATIONS" \
        --additional-instructions "$ADDITIONAL_INSTRUCTIONS" \
        --model "openai/gpt-4o" \
        --api-base "https://cmu.litellm.ai" >> "$OUTPUT_FILE" 2>&1

    RESULT=$?
    if [ $RESULT -eq 0 ]; then
        echo "Successfully processed $SOURCE_PATH"
    else
        echo "Error processing $SOURCE_PATH (exit code: $RESULT)"
    fi
    
    echo "" >> "$OUTPUT_FILE"
    echo "--------------------------------------" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
done <<< "$PYTHON_FILES"

echo "All cover-agent tasks completed. Full output is available in $OUTPUT_FILE"

echo "All tests generated and processed successfully"

# Create the completion flag that the healthcheck is waiting for
# Only derive REPO_NAME from GITHUB_URL if not in LOCAL_REPO_MODE (where it's already set)
if [ "${LOCAL_REPO_MODE:-}" != "1" ]; then
    REPO_PATH=$(echo "$GITHUB_URL" | sed 's|.*github.com/||' | sed 's|\.git$||')
    ORG=${REPO_PATH%%/*}
    REPO=${REPO_PATH##*/}
    REPO_NAME="${ORG}__${REPO}"
fi

TESTING_COMPLETE_FLAG="/workspace/${REPO_NAME}/testing_complete.flag"

echo "Creating testing completion flag: $TESTING_COMPLETE_FLAG"
echo "DEBUG: REPO_NAME=$REPO_NAME"
echo "DEBUG: TESTING_COMPLETE_FLAG=$TESTING_COMPLETE_FLAG"

# Ensure the directory exists
mkdir -p "/workspace/${REPO_NAME}"
touch "$TESTING_COMPLETE_FLAG"
echo "Testing completion flag created successfully"
ls -la "$TESTING_COMPLETE_FLAG"
echo "Testing agent setup complete - worker can now start"