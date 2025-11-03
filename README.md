# 🧪 Testing Agent

This containerized **testing agent** automates environment setup, test file generation, and code coverage analysis for a target project. It’s designed to run standalone or as part of a multi-agent code migration workflow.

---

## 📦 Assumptions
 - `OPENAI_API_KEY` – must be set either:
    - in your shell before running `docker compose up`, e.g.:
      ```bash
      export OPENAI_API_KEY=sk-xxxx...
      docker compose up testing-agent
      ```
    - or via your `.env` file (referenced automatically by Docker Compose):
      ```
      OPENAI_API_KEY=sk-xxxx...
      ```
- You have a **target project** mounted into the container at `/workspace/keep2roam` (see `docker-compose.yml`).  
- The target project contains:
  - A `requirements.txt` for runtime/test dependencies.  
  - A `tests/` directory (created automatically if missing).  
- The `testing-agent` container is built from the provided `Dockerfile` and run via Docker Compose.  
- API keys (e.g., `OPENAI_API_KEY`) are provided through environment variables.

---

## ⚙️ Configuration

All configuration lives in `config.sh` (loaded by `run.sh`).  
Docker Compose can override these values with environment variables.

| Variable                   | Purpose                                              | Example Value |
|-----------------------------|------------------------------------------------------|---------------|
| `PROJECT_ROOT`              | Path to the target project inside the container     | `/workspace/keep2roam` |
| `TEST_COMMAND_DIR`          | Directory where tests are created/executed          | `/workspace/keep2roam/tests` |
| `CODE_COVERAGE_REPORT_PATH` | Where to write the coverage XML report              | `/workspace/keep2roam/tests/coverage.xml` |
| `TEST_REQUIREMENTS_FILE`    | Path to install test dependencies                   | `/workspace/keep2roam/requirements.txt` |
| `HTML_REPORT_PATH`          | Optional HTML report path (leave empty to disable)  | `/workspace/keep2roam/tests/testing_agent_report.html` |
| `LOG_FILE`                  | Path where run.sh stores stdout/stderr              | `/workspace/keep2roam/logs/testing_agent.log` |
| `TEST_COMMAND`              | Command used to run tests                           | `pytest -q` |
| `COVERAGE_TYPE`             | Coverage tool to use (e.g. `branch`, `line`)        | `line` |
| `DESIRED_COVERAGE`          | Target coverage threshold (%)                       | `80` |
| `MAX_ITERATIONS`            | Max test generation iterations per file             | `3` |
| `ADDITIONAL_INSTRUCTIONS`   | Extra hints passed to the test generator            | `""` |

### Notes on `MAX_ITERATIONS`
- Each iteration generates up to **4 new tests**.  
- Some generated tests may fail against the original codebase or may not increase coverage.  
- Setting `MAX_ITERATIONS` too low can stop the agent before it finds a useful set of tests.  
- **Recommendation:** allow enough iterations for multiple rounds of generation, while avoiding runaway runtime.

---

## 🔍 Current & Future Capabilities

- ✅ **Current:**  
  - Parses code with Python `ast` to identify **downstream files** (files that a given source file depends on).  
  - Still runs test generation **across all files in the repository**, not only those linked to a change.

- 🚧 **Planned (next version):**  
  - Smarter file targeting: generate tests only for files identified as **targets** (directly changed) and their **upstreams** (files that depend on them).  
  - This will reduce noise and runtime while keeping test generation focused.

---

## 🚀 How to Run

### 1. Build the container
```bash
docker compose build testing-agent
```

### 2. Run the agent
```bash
docker compose up testing-agent
```

The container will:
- Export API keys (set `OPENAI_API_KEY`; `testing-agent/config.sh` defaults `API_BASE` to `https://ai-gateway.andrew.cmu.edu/`).
- Install dependencies from $TEST_REQUIREMENTS_FILE.
- Ensure tests/ folder and conftest.py exist.
- Walk through each Python file under $PROJECT_ROOT.
- Generate or reuse test files (tests/test_<source>.py).
- Run the coverage agent until the desired threshold is reached.
- Redirect stdout/stderr to the configured log file.

### 3. Inspect results
- Execution log: `logs/testing_agent.log`
- Coverage XML: `tests/coverage.xml`
- HTML report (optional): only if `HTML_REPORT_PATH` is set in the configuration
