FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps — CPU-only torch for sentence-transformers
COPY pyproject.toml /app/pyproject.toml
COPY agift/ /app/agift/
COPY import_agift.py /app/import_agift.py
RUN pip install --no-cache-dir /app[all] \
    torch --extra-index-url https://download.pytorch.org/whl/cpu \
    gunicorn>=22.0.0 flask>=3.0.0

COPY dashboard/ /app/dashboard/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Model cache volume mount point
ENV TRANSFORMERS_CACHE=/app/models

EXPOSE 5050

ENTRYPOINT ["/entrypoint.sh"]
