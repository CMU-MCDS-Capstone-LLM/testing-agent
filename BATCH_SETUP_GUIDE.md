# Batch Environment Setup & Testing Agent Run Guide

This guide explains how to automate environment setup and testing-agent execution across 59 repos.

## Architecture Overview

The batch processing is split into **2 phases**:

### Phase 1: Environment Setup (`setup_all_envs.py`)
- **System Level (APT)**: Install all unique system dependencies on the host OS (one-time, system-wide)
- **Python Level (Conda + venv)**: Create a conda environment for common packages, then setup per-repo venvs with specific dependencies

### Phase 2: Testing Agent Execution (`run_all_testing_agents.py`)
- Run testing-agent on all prepared repos (sequentially or in parallel)
- Track progress and allow resuming

## Why This Approach?

1. **System packages (apt)** won't conflict because they're just C/system libraries (gcc, libffi, etc.)
2. **Python packages** are isolated per-repo using venv, so different repos can use different numpy/scipy versions
3. **APT packages are needed before venv creation** for compiling native extensions (cryptography, numpy, etc.)
4. **Batch execution is cleaner** than mixing env setup and testing in a single script

## Prerequisites

```bash
# Make sure conda is installed
conda --version

# Make sure you have sudo access (for apt-get)
sudo apt-get --version
```

## Quick Start

### 1. Run Full Setup (APT + Conda + Per-Repo Envs)

```bash
cd /home/ubuntu/testing-agent

# Full setup (installs APT packages + conda + all repo envs)
python setup_all_envs.py

# With resume capability (useful if interrupted)
python setup_all_envs.py --resume
```

**What this does:**
- Calls `sudo apt-get install` for all unique packages across repos
- Creates/updates conda environment from `testing-agent-env.yml`
- For each repo:
  - Creates `.venv_helper` and `.venv_eval` inside the repo directory
  - Installs pip dependencies into venv
  - Saves metadata to `.testing_agent/env_metadata.json`

**Output:** `setup_envs.log` (detailed log of what was installed)

### 2. Run Testing Agent on All Repos

```bash
# Sequential execution (1 repo at a time)
python run_all_testing_agents.py

# Parallel execution (4 repos at a time)
python run_all_testing_agents.py --parallel 4

# Resume from last checkpoint
python run_all_testing_agents.py --parallel 4 --resume
```

**What this does:**
- Loads repo metadata from `.testing_agent/env_metadata.json`
- For each repo, runs `python -m testing_agent.main --config <config.yaml>`
- Tracks which repos completed in `testing_agent_status.json`
- Allows resuming without re-running completed repos

**Output:**
- `run_testing_agents.log` (detailed execution log)
- `testing_agent_status.json` (progress checkpoint for resume)

## Available Options

### setup_all_envs.py

```
--data-root PATH          Root folder with repos/, envs/ (default: full_data-success_only-all)
--skip-apt                Skip APT package installation (useful if already done)
--skip-conda              Skip conda environment setup
--resume                  Skip repos that already have env_metadata.json
--dry-run                 Show what would be done without doing it
```

### run_all_testing_agents.py

```
--data-root PATH          Root folder with repos/ (default: full_data-success_only-all)
--parallel N              Number of parallel workers (default: 1)
--timeout SECONDS         Per-repo timeout in seconds (default: 3600)
--resume                  Skip repos in testing_agent_status.json
--dry-run                 Show what would be done without doing it
```

## Typical Workflow

### Day 1: Setup Phase
```bash
# Check what would be installed (no changes)
python setup_all_envs.py --dry-run

# Actually install
python setup_all_envs.py

# Check logs
tail -f setup_envs.log

# If interrupted, resume
python setup_all_envs.py --resume
```

### Day 2: Testing Phase
```bash
# Do a dry run to verify everything is ready
python run_all_testing_agents.py --dry-run

# Run with 4 workers in parallel
python run_all_testing_agents.py --parallel 4

# Monitor progress
tail -f run_testing_agents.log

# If interrupted, resume
python run_all_testing_agents.py --parallel 4 --resume
```

## Understanding the Environment Structure

After setup, each repo has this structure:

```
full_data-success_only-all/repos/<repo-id>/
├── .venv_helper/          # venv with base dependencies
├── .venv_eval/            # copy of helper venv for eval mode
├── .testing_agent/
│   ├── env_metadata.json  # Metadata about the environment
│   ├── agent_config.yaml  # Config for testing-agent (generated)
│   └── ...
├── <repo-contents>/
└── ...
```

## How Environment Installation Works

For each repo, `env_manager.py` does:

1. **Read decision.json** from `full_data-success_only-all/envs/<repo-id>/decision.json`
2. **Extract variables:**
   - `python_version_tag` → Python version to use
   - `pip_deps` → List of pip packages to install
   - `install_editable` → Whether to do `pip install -e .`
   - `env_vars` → Environment variables to set during testing
   - `test_cmd` → Command to run tests

3. **Create venv** using the specified Python version
4. **Install pip packages** from decision.json + pytest-cov + pytest-mock
5. **Save metadata** to `.testing_agent/env_metadata.json`

### APT Package Installation

The `project_apt_packages` field in decision.json contains packages like:
- `gcc, g++` → C/C++ compilers
- `libffi-dev, libssl-dev` → Development headers for cryptography, etc.
- `libopenblas-dev, gfortran` → Numeric computing (numpy, scipy)
- `libxml2-dev` → XML parsing libraries

These are installed **once, system-wide** with `sudo apt-get install`.

## Troubleshooting

### "decision.json not found"
- Check that `full_data-success_only-all/envs/<repo-id>/decision.json` exists
- Verify data-root path is correct

### "Unable to locate python executable"
- The script tries to find Python matching the `python_version_tag` from decision.json
- If not found, falls back to system Python
- Install missing Python versions: `sudo apt-get install python3.9 python3.10`

### "Editable install failed"
- This is usually OK - the script logs a warning but continues
- Happens when `pip install -e .` fails due to missing dependencies or build issues
- Can be skipped with `--skip-editable` flag

### Parallel execution failures
- If using `--parallel 4`, some repos may fail while others succeed
- Check `testing_agent_status.json` to see which completed
- Use `--resume` to re-run failed repos

### Permission denied (apt install)
- The scripts require sudo access
- Make sure your user has passwordless sudo: `sudo visudo`
- Or run entire script with sudo: `sudo python setup_all_envs.py`

## Performance Notes

- **APT installation:** ~5-10 minutes (one-time, ~30 packages total)
- **Conda setup:** ~5 minutes
- **Per-repo env setup:** 30 seconds - 2 minutes each, depending on dependencies
- **Testing agent run:** 1-10 minutes per repo (depends on test suite size)

**Total estimate:**
- Setup phase: 1-2 hours
- Testing phase: 30 mins - 2 hours (depending on parallelism)

## Next Steps

1. Review `setup_envs.log` to identify any repos with setup issues
2. Review `run_testing_agents.log` and `testing_agent_status.json` for results
3. Check individual repo `.testing_agent/` directories for detailed outputs
4. Use `--skip-apt` and `--resume` for re-runs or partial setups

## Files Modified

- `testing_agent/env_manager.py` - Added missing `env_mode` parameter + fixed pip dependency path handling
  - Now handles `-r requirements.txt` correctly (converts to absolute paths)
  - Detects and corrects common mistakes like `-r ../requirements.txt` when file exists in repo root
  - Logs warnings for questionable dependency paths
- `setup_all_envs.py` - New script for batch environment setup
- `run_all_testing_agents.py` - New script for batch testing agent execution

## Dependency Path Handling

The environment setup now intelligently handles pip dependencies:

- `-r requirements.txt` → Converts to absolute path: `-r /full/path/to/requirements.txt`
- `-r requirements/test.txt` → Converts to absolute path for nested files
- `-r ../requirements.txt` → Detects if file exists in repo root, auto-corrects to use it
- `-e .` → Keeps as-is (editable install of current repo)
- `-e ./subdir` → Converts to absolute path if directory exists

This ensures pip works correctly regardless of how relative paths are specified in decision.json.
