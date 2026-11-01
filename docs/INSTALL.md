# Installing SURF

Step-by-step setup, written so a person **or an AI coding agent** can follow it start to finish. Every step ends with a check. Don't skip the checks: SURF degrades quietly. For example, search still "works" without embeddings, it just ranks results worse.

> **Agents:** do all of the steps, including step 3. A finished install means `./surf preflight` reports `[ok]` on every line. If a step fails, fix it or tell the user exactly which line failed and why. Don't report success while running in BM25-only mode.

## What a complete install has

| Part | Needed for | Without it |
|---|---|---|
| SURF + Playwright Chromium | everything | nothing works |
| Search backend: SearXNG (bundled in Docker) or `SURF_EXA_API_KEY` | `web_search` | search fails |
| **Embeddings endpoint** | good search ranking, `refine_query` | keyword-only (BM25) ranking, no section filtering |

---

## Path A: Docker (recommended)

### 1. Configure

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
cp .env.docker.example .env.docker
sed -i.bak "s/^SEARXNG_SECRET=.*/SEARXNG_SECRET=$(openssl rand -hex 32)/" .env.docker && rm .env.docker.bak
```

The template already points embeddings at the bundled service:

```
SURF_EMBEDDING_BASE_URL=http://embeddings:8080/v1
SURF_EMBEDDING_MODEL=nomic-embed-text
```

### 2. Start (with the embeddings profile)

```bash
docker compose --env-file .env.docker --profile embeddings up --build -d
```

The `embeddings` container is a CPU-only llama.cpp server (~1.2 GB image). On first start it downloads `nomic-embed-text-v1.5` (~140 MB) from Hugging Face into a Docker volume, and later starts reuse it. SURF waits for it to be healthy, so the first boot can take a few minutes. To serve a different GGUF model, set `SURF_EMBEDDING_HF_MODEL`.

**Check:** `docker compose --env-file .env.docker --profile embeddings ps` shows `surf`, `surf-searxng` and `surf-embeddings` as `healthy`.

> Always include `--profile embeddings` when you re-run `up`. Without it, Compose starts SURF with no embeddings container, and `/health/embeddings` reports `down`.

### 3. Verify

```bash
SURF_URL=127.0.0.1:17777 ./surf preflight
```

Expected output: `[ok]` for `service`, `SearXNG`, `embeddings` and `outbound fetch`. (`browser runtime` needs a `browse`, `ui` or `ops` key, so it may show `401` on a keyless setup. That's fine.)

### 4. Connect an agent

Streamable HTTP MCP: `http://127.0.0.1:17777/mcp/web`. See the [README](../README.md#connect-your-agent).

---

## Path B: Local Python

### 1. Install

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

**Check:** `.venv/bin/python -c "import playwright, fastapi; print('ok')"`

### 2. Search backend

Pick one:
- **Exa:** `export SURF_EXA_API_KEY=...`
- **SearXNG:** run any SearXNG instance with JSON output enabled and set `SURF_SEARXNG_BASE_URL` (default `http://localhost:8888`).

### 3. Embeddings

Install [Ollama](https://ollama.com/download), then:

```bash
ollama pull nomic-embed-text
export SURF_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
export SURF_EMBEDDING_MODEL=nomic-embed-text
```

**Check** that the endpoint answers before going further:

```bash
curl -s http://127.0.0.1:11434/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text","input":["hello"]}' | head -c 120
```

You should see `{"object":"list","data":[{"object":"embedding","embedding":[...`.

Put these variables in a `.env` file in the repo root (it's gitignored) so they persist, or in your MCP client's `env` block (see below).

### 4. Verify

```bash
.venv/bin/python start_surf.py &          # HTTP server on 127.0.0.1:17777
SURF_URL=127.0.0.1:17777 ./surf preflight
```

Expected output: `[ok] embeddings: 200`. If it says `disabled`, the variables aren't reaching SURF. If it says `down`, the URL or model name is wrong, or Ollama isn't running.

### 5. Connect an agent (stdio)

The MCP stdio server reads the same environment. Pass the variables explicitly so they don't depend on your shell:

```json
{
  "mcpServers": {
    "surf": {
      "command": "/path/to/SURF/.venv/bin/python",
      "args": ["/path/to/SURF/surfctl.py", "mcp"],
      "env": {
        "SURF_EMBEDDING_BASE_URL": "http://127.0.0.1:11434/v1",
        "SURF_EMBEDDING_MODEL": "nomic-embed-text"
      }
    }
  }
}
```

---

## Using a different embeddings provider

SURF works with any OpenAI-compatible `/v1/embeddings` server.

| Provider | `SURF_EMBEDDING_BASE_URL` | `SURF_EMBEDDING_MODEL` | Notes |
|---|---|---|---|
| Bundled Docker service | `http://embeddings:8080/v1` | `nomic-embed-text` | No key; the model name is ignored by the server |
| Ollama (local default) | `http://127.0.0.1:11434/v1` | `nomic-embed-text` | No key |
| LiteLLM proxy | `http://<host>:4000/v1` | your model alias | Set `SURF_EMBEDDING_API_KEY` |
| OpenAI | `https://api.openai.com/v1` | `text-embedding-3-small` | Set `SURF_EMBEDDING_API_KEY`. Set `SURF_EMBEDDING_DIMENSIONS=768` or leave it as is |

SURF adds Nomic-style `search_query:` / `search_document:` prefixes to its inputs, so **Nomic models rank best**. Other models still work but may score a little lower. If a server rejects the `dimensions` request field, set `SURF_EMBEDDING_DIMENSIONS=0`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `embeddings: 503 - Set SURF_EMBEDDING_BASE_URL…` | Not configured | Step 3 |
| `embeddings: 503 - …request failed` | Wrong URL or model name, server down, or bad key | Run the `curl` check in step 3 against the same URL and model |
| Docker: `embeddings` down after a restart | Started without `--profile embeddings` | Re-run `up` with the profile |
| `search/stats` shows `embedder_active: false` | No search has run since startup, or the last embedding call failed | Use `GET /health/embeddings` instead, which runs a live probe |
