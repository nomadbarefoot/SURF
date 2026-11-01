# Installing SURF

Step-by-step setup, written so a person **or an AI coding agent** can follow it start to finish. Every step ends with a check. Don't skip the checks: SURF degrades quietly. For example, search still "works" without embeddings, it just ranks results worse.

> **Agents:** do every step, including embeddings. A finished install means `surf preflight` exits 0: every required line is `[ok]` (`[skip]` lines are optional). If a step fails, fix it or tell the user exactly which line failed and why. Don't report success while running in BM25-only mode.

## What a complete install has

| Part | Needed for | Without it |
|---|---|---|
| SURF + Chromium | everything | nothing works (Chromium installs itself on first browser use) |
| Search: keyless Exa (default), `SURF_EXA_API_KEY`, or SearXNG | `web_search` | nothing extra to install; keyless Exa is rate-limited |
| **Embeddings endpoint** | good search ranking, `refine_query` | keyword-only (BM25) ranking, no section filtering |

Pick a path. **Path A** (uvx) suits one machine with stdio MCP clients such as Claude Code, Codex or Cursor. **Path B** (Docker) suits a shared HTTP service.

---

## Path A: uvx (recommended)

### 1. Install uv

```bash
command -v uvx || curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Check:** `uvx --version` prints a version.

### 2. Install SURF and Chromium

```bash
uvx --from "surf-web[all] @ git+https://github.com/nomadbarefoot/SURF" surf-mcp --help
uvx --from git+https://github.com/nomadbarefoot/SURF playwright install chromium
```

The first line downloads SURF with all extras (YouTube and document parsing) and caches it. Drop `[all]` for a smaller install. The second line pre-downloads Chromium (~2 min); skipping it is fine, because SURF also installs Chromium on the first browser call.

**Check:** the first command prints `usage: surf-mcp`.

### 3. Embeddings

Install [Ollama](https://ollama.com/download), then pull the model:

```bash
ollama pull nomic-embed-text
```

**Check** that the endpoint answers:

```bash
curl -s http://127.0.0.1:11434/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text","input":["hello"]}' | head -c 120
```

You should see `{"object":"list","data":[{"object":"embedding","embedding":[...`.

Save the settings where SURF always reads them, `~/.surf/.env`:

```bash
mkdir -p ~/.surf && cat >> ~/.surf/.env <<'EOF'
SURF_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1
SURF_EMBEDDING_MODEL=nomic-embed-text
EOF
```

(Any OpenAI-compatible endpoint works instead of Ollama; see [Using a different embeddings provider](#using-a-different-embeddings-provider).)

### 4. Verify

Start the HTTP server briefly, run the preflight, then stop the server:

```bash
SURF="git+https://github.com/nomadbarefoot/SURF"
uvx --from "$SURF" surf-server &  SERVER=$!
sleep 8 && SURF_URL=127.0.0.1:17777 uvx --from "$SURF" surf preflight
kill $SERVER
```

Expected output: `[ok]` for `service`, `search`, `embeddings` and `outbound fetch`. `[skip]` on `browser runtime` and `SearXNG (optional)` is fine. If embeddings says `disabled`, `~/.surf/.env` isn't being read. If it says `down`, the URL or model is wrong, or Ollama isn't running.

### 5. Connect your agents

```bash
uvx --from "surf-web[all] @ git+https://github.com/nomadbarefoot/SURF" surf-mcp install --extras all --profile web
```

This detects the installed agents (Claude Code, Codex CLI, Cursor, VS Code, Gemini CLI, Claude Desktop, Windsurf, OpenCode, Hermes Agent) and adds SURF to each one's user-level config. It runs the server once first so the agents' first launch is fast, and prints a YAML report:

- `installed`: done. Restart that agent.
- `exists`: a `surf` entry is already there. Rerun with `--force` to replace it.
- `manual`: the config couldn't be edited safely. Paste the printed `snippet`.
- `failed`: shows the error, plus a snippet to paste instead.

Useful options: `--client codex,hermes` targets specific agents, `--dry-run` previews the changes, and `--profile web,browse` (or `web,ui`, `web,finance`, `all`) chooses the tools. No keys are needed over stdio. For an agent that isn't listed, use the generic command from the [README](../README.md#manual-any-mcp-client).

**Check:** restart the agent and ask it to search for something. Most agents also list connected MCP servers, e.g. `/mcp` in Claude Code or `codex mcp list`.

---

## Path B: Docker (HTTP service)

### 1. Configure

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
cp .env.docker.example .env.docker
```

The template enables the bundled embeddings service (`COMPOSE_PROFILES=embeddings`) and points SURF at it:

```
SURF_EMBEDDING_BASE_URL=http://embeddings:8080/v1
SURF_EMBEDDING_MODEL=nomic-embed-text
```

To enable `browse`, `ui` or `finance` over HTTP, set their keys in `.env.docker` (`openssl rand -hex 24` for each).

### 2. Start

```bash
docker compose --env-file .env.docker up --build -d
```

The `embeddings` container is a CPU-only llama.cpp server (~1.2 GB image). On first start it downloads `nomic-embed-text-v1.5` (~140 MB) from Hugging Face into a Docker volume, and later starts reuse it. SURF waits for it to be healthy, so the first boot can take a few minutes. To serve a different GGUF model, set `SURF_EMBEDDING_HF_MODEL`.

**Check:** `docker compose --env-file .env.docker ps` shows `surf` and `surf-embeddings` as `healthy`.

> Always pass `--env-file .env.docker`. It carries `COMPOSE_PROFILES`; without it, Compose starts SURF with no embeddings container, and `/health/embeddings` reports `down`.
>
> Optional self-hosted search fallback: set `COMPOSE_PROFILES=embeddings,searxng` and `SEARXNG_SECRET=$(openssl rand -hex 32)`.

### 3. Verify

```bash
SURF_URL=127.0.0.1:17777 ./surf preflight
```

Expected output: `[ok]` for `service`, `search`, `embeddings` and `outbound fetch`. `[skip]` on `browser runtime` (needs a key over HTTP) and `SearXNG (optional)` is fine.

### 4. Connect an agent

Streamable HTTP MCP endpoints: `http://127.0.0.1:17777/mcp/web` (keyless), plus `/mcp/browse`, `/mcp/ui` and `/mcp/finance` with `Authorization: Bearer <that profile's key>`.

---

## Using a different embeddings provider

SURF works with any OpenAI-compatible `/v1/embeddings` server.

| Provider | `SURF_EMBEDDING_BASE_URL` | `SURF_EMBEDDING_MODEL` | Notes |
|---|---|---|---|
| Ollama (local) | `http://127.0.0.1:11434/v1` | `nomic-embed-text` | No key |
| Bundled Docker service | `http://embeddings:8080/v1` | `nomic-embed-text` | No key; the server ignores the model name |
| LiteLLM proxy | `http://<host>:4000/v1` | your model alias | Set `SURF_EMBEDDING_API_KEY` |
| OpenAI | `https://api.openai.com/v1` | `text-embedding-3-small` | Set `SURF_EMBEDDING_API_KEY`. Set `SURF_EMBEDDING_DIMENSIONS=768` or leave it as is |

SURF adds Nomic-style `search_query:` / `search_document:` prefixes to its inputs, so **Nomic models rank best**. Other models still work but may score a little lower. If a server rejects the `dimensions` request field, set `SURF_EMBEDDING_DIMENSIONS=0`.

## Where settings and data live

| Install | Settings file | Runtime data |
|---|---|---|
| uvx / pipx | `~/.surf/.env` (and `./.env` in the working directory) | `~/.surf/data` |
| Source checkout | `./.env` | `./data` |
| Docker | `.env.docker` | the `surf-data` volume |

`SURF_HOME` overrides the data location in every case. Environment variables (including an MCP client's `env` block) override files.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `embeddings: 503 - Set SURF_EMBEDDING_BASE_URL…` | Not configured | Path A step 3 |
| `embeddings: 503 - …request failed` | Wrong URL or model name, server down, or bad key | Run the `curl` check in step 3 against the same URL and model |
| Agent says the SURF server timed out on first start | Its first launch downloaded dependencies | Run `uvx --from git+https://github.com/nomadbarefoot/SURF surf-mcp --help` once, then restart the agent (`surf-mcp install` does this automatically) |
| First browser tool call is slow or times out | Chromium is downloading (~2 min) | Wait and retry, or pre-install: `uvx --from git+https://github.com/nomadbarefoot/SURF playwright install chromium` |
| `yt-dlp is not installed` / `parser not installed` | Installed without extras | Use `surf-web[all] @ git+…` (or `[youtube]` / `[docs]`) |
| Docker: `embeddings` down after a restart | Started without `--env-file .env.docker`, or `COMPOSE_PROFILES` lacks `embeddings` | Re-run `up` with the env file |
| `search` fails with `Exa MCP returned 429` | The free keyless tier is rate-limited | Wait and retry, set `SURF_EXA_API_KEY`, or add SearXNG as a fallback |
| `search/stats` shows `embedder_active: false` | No search has run since startup, or the last embedding call failed | Use `GET /health/embeddings` instead, which runs a live probe |
