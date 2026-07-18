FROM mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69

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
