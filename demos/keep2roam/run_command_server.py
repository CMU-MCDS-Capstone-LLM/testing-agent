from flask import Flask, request, jsonify
import subprocess, os, time, logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

@app.get("/")
def home():
    return jsonify({"status": "ok", "message": "Command server is running"}), 200

# 旧接口（仅供你 curl 调试时用）: {"cmd": "..."}
@app.post("/run")
def run_legacy():
    data = request.get_json(force=True) or {}
    cmd = data.get("cmd")
    if not cmd:
        return jsonify({"error": "Missing 'cmd'"}), 400
    return _exec_shell(command=cmd, cwd="/home/appuser/repo", env=os.environ.copy(), timeout=None)

# ✅ 新接口：TestingAgent 的 RemoteCommandRunner 用这个（支持 cwd/env/timeout）
# payload: {"command":"...","cwd":"/home/appuser/repo","env":{...},"timeout":180}
@app.post("/run-command")
def run_command():
    data = request.get_json(force=True) or {}
    cmd = data.get("command")
    if not cmd:
        return jsonify({"error": "Missing 'command'"}), 400

    cwd = data.get("cwd") or "/home/appuser/repo"

    base_env = os.environ.copy()
    incoming_env = data.get("env") or {}
    for k, v in incoming_env.items():
        if v is None:
            base_env.pop(k, None)
        else:
            base_env[str(k)] = str(v)

    timeout = data.get("timeout")
    
    print(">>> executing:", repr(cmd), "cwd:", cwd, flush=True)
    return _exec_shell(command=cmd, cwd=cwd, env=base_env, timeout=timeout)

def _exec_shell(command: str, cwd: str, env: dict, timeout: int | None):
    logging.info(f"[Server] Received command: {command}")
    start = time.time()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        rc = int(proc.returncode)
        dur = int((time.time() - start) * 1000)
        logging.info(f"[Server] Finished rc={rc} in {dur} ms")
        return jsonify({
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": rc,
            "duration_ms": dur,
        }), 200
    except subprocess.TimeoutExpired as e:
        dur = int((time.time() - start) * 1000)
        logging.warning(f"[Server] Timeout after {dur} ms")
        return jsonify({
            "stdout": e.stdout or "",
            "stderr": (e.stderr or "") + "\n[TIMEOUT]",
            "exit_code": 124,
            "duration_ms": dur,
        }), 200
    except Exception as e:
        dur = int((time.time() - start) * 1000)
        logging.exception("[Server] Execution failed")
        return jsonify({
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "duration_ms": dur,
        }), 200

if __name__ == "__main__":
    # 一定要 0.0.0.0 才能被容器外访问
    app.run(host="0.0.0.0", port=8000)
