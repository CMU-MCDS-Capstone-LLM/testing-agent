FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY testing-requirements.txt /tmp/testing-requirements.txt
RUN pip install --no-cache-dir -r /tmp/testing-requirements.txt

WORKDIR /app
COPY run.sh config.sh setup_repo.sh ./
COPY cover_agent ./cover_agent/
RUN chmod +x /app/run.sh /app/setup_repo.sh 

# Add cover_agent to Python path
ENV PYTHONPATH="/app/cover_agent:${PYTHONPATH}"

CMD ["bash", "-lc", "/app/run.sh"]