#!/bin/bash

# TODO
# [run.sh change to python: import coveragent]
# [config.sh change to yaml]


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

# --- 1. Export API Keys ---
if [ -n "${LITELLM_API_KEY:-}" ]; then
    export LITELLM_API_KEY
    if [ -n "${API_BASE:-}" ]; then
        export OPENAI_API_KEY="$LITELLM_API_KEY"
    fi
fi
echo "API keys exported."

# Ensure the testing-agent sources are importable without packaging them
case ":${PYTHONPATH:-}:" in
  *":$SCRIPT_DIR:"*) ;;
  *) export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

# --- 2. Install Dependencies [TODO] ---
# 确认 REPO_VENV_PYTHON 有值且可执行
if [ -z "${REPO_VENV_PYTHON:-}" ]; then
  if command -v python >/dev/null 2>&1; then
    REPO_VENV_PYTHON="$(command -v python)"
    echo "REPO_VENV_PYTHON not set; using $(python -V) at $REPO_VENV_PYTHON"
  else
    echo "No python found and REPO_VENV_PYTHON not set. Abort." >&2
    exit 1
  fi
fi
if [ ! -x "$REPO_VENV_PYTHON" ]; then
  echo "Configured REPO_VENV_PYTHON '$REPO_VENV_PYTHON' is not executable." >&2
  exit 1
fi

# 定义 pip 封装
run_repo_pip() { "$REPO_VENV_PYTHON" -m pip "$@"; }

# 升级基础工具
run_repo_pip install -U pip wheel setuptools

# 1) 安装测试依赖（如果有）
if [ -n "${TEST_REQUIREMENTS_FILE:-}" ] && [ -f "$TEST_REQUIREMENTS_FILE" ]; then
    echo "Installing test requirements from $TEST_REQUIREMENTS_FILE..."
    run_repo_pip install --no-cache-dir -r "$TEST_REQUIREMENTS_FILE"
else
    echo "No separate testing-requirements file found."
fi

# 2) 安装 repo 自身依赖（如果有）
if [ -n "${REPO_REQUIREMENTS_FILE:-}" ] && [ -f "$REPO_REQUIREMENTS_FILE" ]; then
    echo "Installing repo requirements from $REPO_REQUIREMENTS_FILE..."
    if [ "${INSTALL_REPO_DEPS_WITH_NODEPS:-false}" = "true" ]; then
        run_repo_pip install --no-deps --no-cache-dir -r "$REPO_REQUIREMENTS_FILE"
    else
        run_repo_pip install --no-cache-dir -r "$REPO_REQUIREMENTS_FILE"
    fi
fi

# 3) 确保 pytest 工具存在（即使 requirements 里没写也强制装）
run_repo_pip install -U pytest pytest-cov

# 4) 自动推断 REPO_SITE_PACKAGES（若没显式提供）
if [ -z "${REPO_SITE_PACKAGES:-}" ]; then
  REPO_SITE_PACKAGES="$($REPO_VENV_PYTHON - <<'PY'
import site
cands = []
cands += getattr(site,"getsitepackages",lambda:[])() or []
cands += [site.getusersitepackages()]
for p in cands:
    if p and "site-packages" in p:
        print(p); break
PY
)"
  echo "REPO_SITE_PACKAGES = $REPO_SITE_PACKAGES"
fi

# --- 3. Select Files to Generate Tests on ---
# Run RepoGraph selector
SELECTOR_OUTPUT_DIR="repograph_runner/output"
SELECTOR_OUTPUT_FILE="repograph_result.json"
SELECTOR_OUTPUT_PATH="$(pwd)/${SELECTOR_OUTPUT_DIR}/${SELECTOR_OUTPUT_FILE}"

mkdir -p "$(dirname "$SELECTOR_OUTPUT_PATH")"

if [ -z "${MIGRATION_CONFIG:-}" ] || [ ! -f "$MIGRATION_CONFIG" ]; then
  echo "MIGRATION_CONFIG not set or file missing: $MIGRATION_CONFIG" >&2
  exit 1
fi

SELECTOR_SCRIPT="$SCRIPT_DIR/repograph_runner/repograph_selector.py"

"$REPO_VENV_PYTHON" "$SELECTOR_SCRIPT" \
--repo-path "$PROJECT_ROOT" \
--config "$MIGRATION_CONFIG" \
--env-python "$REPO_VENV_PYTHON" \
--extra-path "$REPO_SITE_PACKAGES" \
--output "$SELECTOR_OUTPUT_PATH"

if [ ! -f "$SELECTOR_OUTPUT_PATH" ]; then
    echo "Selector failed to produce $SELECTOR_OUTPUT_PATH" >&2
    exit 1
fi

# Generate pytest arguments derived from selector output
PYTEST_ENV_FILE="$PROJECT_ROOT/pytest_args.env"
"$REPO_VENV_PYTHON" "$SCRIPT_DIR/scripts/build_pytest_args.py" \
    --repo-root "$PROJECT_ROOT" \
    --selector-json "$SELECTOR_OUTPUT_PATH" \
    --output "$PYTEST_ENV_FILE"

if [ -f "$PYTEST_ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$PYTEST_ENV_FILE"
fi

SOURCE_FILES=($($REPO_VENV_PYTHON - "$SELECTOR_OUTPUT_PATH" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
files = set(data["library_consumers"]["files"])
for callers in data.get("workspace_callers", {}).values():
    files.update(callers.get("files", []))
print(" ".join(sorted(files)))
PY
))

INCLUDED_ABS=$($REPO_VENV_PYTHON - "$SELECTOR_OUTPUT_PATH" "$PROJECT_ROOT" <<'PY'
import json, sys, pathlib
data = json.load(open(sys.argv[1]))
root = pathlib.Path(sys.argv[2]).resolve()
files = set()
for callers in data.get("workspace_callers", {}).values():
    files.update(callers.get("files", []))
print(" ".join(str(root / fname) for fname in sorted(files)))
PY
)

# --- 4. Create Test Folder and File & Run Coverage Analysis [TODO] ---
# TODO
# use additional file
# do not match test file name
# use lsp/ast to check which test file uses which src file, only keep those

echo "Setting up test environment in $PROJECT_ROOT"

# --- Build pytest command based on selector-derived arguments ---
if [[ "$TEST_COMMAND" =~ ^pytest ]]; then
  ORIGINAL_ARGS="${TEST_COMMAND#pytest}"
  ORIGINAL_ARGS="${ORIGINAL_ARGS## }"
  PYTEST_CMD="$REPO_VENV_PYTHON -m pytest"

  if [ -n "${PYTEST_COV_TARGET:-}" ]; then
    IFS=',' read -r -a _cov_targets <<< "$PYTEST_COV_TARGET"
    for target in "${_cov_targets[@]}"; do
      trimmed="${target// /}"
      if [ -n "$trimmed" ]; then
        PYTEST_CMD+=" --cov=$trimmed"
      fi
    done
  else
    PYTEST_CMD+=" --cov=.."
  fi

  PYTEST_CMD+=" --cov-report=xml:${CODE_COVERAGE_REPORT_PATH} --cov-report=term"

  if [ -n "${PYTEST_INCLUDE_EXPR:-}" ]; then
    PYTEST_CMD+=" -k \"${PYTEST_INCLUDE_EXPR}\""
  fi

  if [ -n "$ORIGINAL_ARGS" ]; then
    PYTEST_CMD+=" $ORIGINAL_ARGS"
  fi

  TEST_COMMAND="$PYTEST_CMD"
else
  TEST_COMMAND="$TEST_COMMAND"
fi

echo "Using test runner: $TEST_COMMAND"

# Clear the output file before appending
mkdir -p "$(dirname "$OUTPUT_FILE")"
> "$OUTPUT_FILE"

# Ensure coverage report directory exists
mkdir -p "$(dirname "$CODE_COVERAGE_REPORT_PATH")"

# (a) Create tests folder if it does not exist
if [ ! -d "$TEST_COMMAND_DIR" ]; then
    echo "Tests folder not found. Creating folder: $TEST_COMMAND_DIR"
    mkdir -p "$TEST_COMMAND_DIR"
else
    echo "Tests folder exists: $TEST_COMMAND_DIR"
fi

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

if [ -d "$PROJECT_ROOT/src" ]; then
    export PYTHONPATH="$(cd "$PROJECT_ROOT/src" && pwd):$(cd "$PROJECT_ROOT" && pwd):$(cd "$PROJECT_ROOT/.." && pwd):${PYTHONPATH}"
  else
    export PYTHONPATH="$(cd "$PROJECT_ROOT" && pwd):$(cd "$PROJECT_ROOT/.." && pwd):${PYTHONPATH}"
  fi
  
PKG_NAME="$(basename "$PROJECT_ROOT")"

  for rel_path in "${SOURCE_FILES[@]}"; do
      if [[ "$rel_path" == tests/* ]]; then
          echo "Skipping test file: $rel_path"
          continue
      fi
      SOURCE_PATH="$PROJECT_ROOT/$rel_path"
      if [ ! -f "$SOURCE_PATH" ]; then
          echo "Skipping missing source: $SOURCE_PATH"
          continue
      fi

      echo "Processing: $SOURCE_PATH"
      BASENAME=$(basename "$SOURCE_PATH")
      NAME_NO_EXT="${BASENAME%.py}"

    TEST_CANDIDATES=()
    while IFS= read -r candidate; do
        TEST_CANDIDATES+=("$candidate")
    done < <(
        find "$PROJECT_ROOT" -type f \
            \( -name "test_${BASENAME}" -o -name "test_${NAME_NO_EXT}.py" -o -name "${NAME_NO_EXT}_test.py" \) \
            -not -path "*/venv*" -not -path "*/.*" \
            2>/dev/null | sort
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
    # Create initial test file that imports the source module to allow coverage tracking
    cat > "$TEST_FILE" <<EOF
# do not delete this comment, this is where pytest adding import pkg msg
import ${NAME_NO_EXT}

def test_dummy():
    assert True  # dummy test - placeholder for future tests
EOF
fi

# 无论 test file 新建还是已有，都要补 imports
IMPORT_BLOCK=$("$REPO_VENV_PYTHON" - "$SOURCE_PATH" "$PKG_NAME" <<'PY'
import ast, sys, pathlib, re
src = pathlib.Path(sys.argv[1])
pkg = sys.argv[2]
code = src.read_text(encoding="utf-8", errors="ignore")
tree = ast.parse(code, filename=str(src))
lines = code.splitlines()

imports = []
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        imports.extend(lines[start:end])
    else:
        break

seen, out = set(), []
for l in imports:
    if l not in seen:
        out.append(l); seen.add(l)

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

    echo "Running cover-agent for source file: $SOURCE_PATH and test file: $TEST_FILE"
    echo "======================================" >> "$OUTPUT_FILE"
    echo "Processing: $SOURCE_PATH" >> "$OUTPUT_FILE"
    echo "Test file: $TEST_FILE" >> "$OUTPUT_FILE"
    echo "======================================" >> "$OUTPUT_FILE"

    INCLUDED_ARGS=()
    if [ -n "$INCLUDED_ABS" ]; then
        INCLUDED_ARGS=(--included-files $INCLUDED_ABS)
    fi

    $REPO_VENV_PYTHON -m cover_agent.main \
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
        --model "${MODEL:-gpt-4o}" \
        --api-base "${API_BASE:-}" \
        "${INCLUDED_ARGS[@]}" >> "$OUTPUT_FILE" 2>&1

    RESULT=$?
    if [ $RESULT -eq 0 ]; then
        echo "Successfully processed $SOURCE_PATH"
    else
        echo "Error processing $SOURCE_PATH (exit code: $RESULT)"
    fi

    echo "" >> "$OUTPUT_FILE"
    echo "--------------------------------------" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
done

echo "All cover-agent tasks completed. Full output is available in $OUTPUT_FILE"
