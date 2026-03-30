FROM python:3.13-slim

WORKDIR /app

# Install Docker CLI (for triggering runs on the worker container)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
       https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    flask>=3.0.0 \
    neo4j>=5.0.0

COPY dashboard/ /app/

EXPOSE 5050

CMD ["python", "app.py"]
