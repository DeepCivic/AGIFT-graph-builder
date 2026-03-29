FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps — sentence-transformers uses CPU-only torch
RUN pip install --no-cache-dir \
    neo4j>=5.0.0 \
    isaacus>=0.1.0 \
    sentence-transformers>=3.0.0 \
    torch --extra-index-url https://download.pytorch.org/whl/cpu

COPY agift/import_agift.py /app/import_agift.py
COPY agift/worker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Model cache volume mount point
ENV TRANSFORMERS_CACHE=/app/models

ENTRYPOINT ["/entrypoint.sh"]
