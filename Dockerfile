FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/surf \
    SURF_HOST=0.0.0.0 \
    SURF_PORT=17777

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r surf -g 10001 && \
    useradd -r -g surf -u 10001 -m -s /bin/bash surf

WORKDIR /app

COPY --chown=root:root requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=root:root . .

RUN mkdir -p data/profiles data/downloads data/screenshots data/filterlists && \
    chown -R surf:surf /app/data /home/surf && \
    chmod 0755 /app /app/scripts/docker-entrypoint.sh

USER surf

EXPOSE 17777

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["python", "start_surf.py"]
