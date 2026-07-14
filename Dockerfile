FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SURF_HOST=0.0.0.0 \
    SURF_PORT=17777

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r surf -g 10001 && \
    useradd -r -g surf -u 10001 -m -s /bin/bash surf

WORKDIR /app

COPY requirements.txt .
RUN if [ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "arm64" ]; then \
        sed -i 's/^torch>=2\.0\.0+cpu$/torch==2.0.0/' requirements.txt; \
    else \
        sed -i 's/^torch>=2\.0\.0+cpu$/torch==2.0.0+cpu/' requirements.txt; \
    fi && \
    sed -i 's/^playwright>=1\.40\.0$/playwright==1.45.0/' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/profiles data/downloads data/filterlists && \
    chown -R surf:surf /app /home/surf

USER surf

EXPOSE 17777

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["python", "start_surf.py"]
