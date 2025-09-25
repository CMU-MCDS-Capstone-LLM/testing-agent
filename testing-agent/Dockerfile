FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
&& rm -rf /var/lib/apt/lists/*

COPY testing-requirements.txt /tmp/testing-requirements.txt
RUN pip install --no-cache-dir -r /tmp/testing-requirements.txt

WORKDIR /app
COPY run.sh config.sh cover_agent ./
RUN chmod +x /app/run.sh

CMD ["bash", "-lc", "/app/run.sh"]