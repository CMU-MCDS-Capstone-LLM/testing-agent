#!/usr/bin/env python3
"""
Remote Python shim: intercepts "python ..." invocations and executes them
INSIDE the container via the command server's /run-command endpoint.
"""

import os, sys, json, shlex, requests

# ---- EDIT THESE IF NEEDED ----
BASE_URL = os.environ.get("REMOTE_BASE_URL", "http://127.0.0.1:8000")
CONTAINER_REPO_ROOT = os.environ.get("CONTAINER_REPO_ROOT", "/home/appuser/repo")
VENV_ACTIVATE = f"{CONTAINER_REPO_ROOT}/.venv/bin/activate"
CWD_IN_CONTAINER = CONTAINER_REPO_ROOT
TIMEOUT_SECS = int(os.environ.get("REMOTE_TIMEOUT", "1800"))
# ------------------------------

def main():
    # argv after "python": e.g. ["-m","pytest","..."]
    argv = sys.argv[1:]
    if not argv:
        print("remote_py_shim: no args; expected to proxy a python invocation", file=sys.stderr)
        sys.exit(2)

    # Build the command to run INSIDE container
    # bash -lc 'source .../.venv/bin/activate && python <argv...>'
    remote_cmd = (
        "bash -lc " +
        shlex.quote(f"source {VENV_ACTIVATE} && python " + " ".join(shlex.quote(a) for a in argv))
    )

    # Prepare a minimal env for tests in container
    py_path = ":".join([
        f"{CONTAINER_REPO_ROOT}/src",
        f"{CONTAINER_REPO_ROOT}",
        f"{CONTAINER_REPO_ROOT}/..",
    ])
    env = {"PYTHONPATH": py_path}

    payload = {
        "command": remote_cmd,
        "cwd": CWD_IN_CONTAINER,
        "env": env,
        "timeout": TIMEOUT_SECS,
    }

    try:
        resp = requests.post(f"{BASE_URL}/run-command", json=payload, timeout=TIMEOUT_SECS + 30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[remote_py_shim] HTTP error: {e}", file=sys.stderr)
        sys.exit(127)

    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    exit_code = int(data.get("exit_code", 1))

    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
