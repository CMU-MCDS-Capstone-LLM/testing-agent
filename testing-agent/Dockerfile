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

COPY testing-agent/testing-agent-requirements.txt ./testing-agent-requirements.txt
RUN pip install --no-cache-dir -r testing-agent-requirements.txt

COPY testing-agent/testing_agent/build_pytest_args.py ./scripts/
COPY testing-agent/run.sh testing-agent/config.sh ./
COPY testing-agent/repograph_runner ./repograph_runner

RUN pip install --no-cache-dir --upgrade "jedi-language-server==0.41.4"

COPY workspace/keep2roam /workspace/keep2roam
COPY workspace/keep2roam_commit.yaml /workspace/keep2roam_commit.yaml
RUN pip install --no-cache-dir -r /workspace/keep2roam/requirements.txt

CMD ["bash", "-lc", "/app/run.sh"]
