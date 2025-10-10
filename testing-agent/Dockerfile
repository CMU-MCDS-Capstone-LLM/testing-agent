FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV TMPDIR=/tmp

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY testing-agent/pyproject.toml testing-agent/README.md ./
COPY testing-agent/cover_agent ./cover_agent
RUN pip install --no-cache-dir -e .

COPY testing-agent/qodo-requirements.txt ./qodo-requirements.txt
RUN pip install --no-cache-dir -r qodo-requirements.txt

COPY testing-agent/run.sh testing-agent/config.sh ./
COPY testing-agent/scripts/build_pytest_args.py ./scripts/
COPY testing-agent/repograph_runner ./repograph_runner

# Install lsp_repograph and copy initialize_params.json to installed package
COPY lsp_repograph ./lsp_repograph
RUN pip install --no-cache-dir ./lsp_repograph
RUN pip install --no-cache-dir --upgrade "jedi-language-server==0.41.4"
RUN python - <<'PY'
import shutil, pathlib
src = pathlib.Path("/app/lsp_repograph/lsp_repograph/core/lsp/jedi_language_server/initialize_params.json")
# Install to site-packages with same nested structure as local
dst = pathlib.Path("/usr/local/lib/python3.11/site-packages/lsp_repograph/core/lsp/jedi_language_server/initialize_params.json")
dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copy(src, dst)
PY

COPY workspace/keep2roam /workspace/keep2roam
COPY workspace/keep2roam_commit.yaml /workspace/keep2roam_commit.yaml
RUN pip install --no-cache-dir -r /workspace/keep2roam/requirements.txt

CMD ["bash", "-lc", "/app/run.sh"]