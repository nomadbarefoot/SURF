# SURF

**A local web toolkit for AI agents.** SURF gives an agent (Claude, Codex, or any MCP client) a real browser and a set of web-research tools, all running on your own machine. It covers search, reading pages, YouTube transcripts, browser automation, UI testing and structured finance data, all from one MCP server.

```
agent ──MCP──▶ SURF ──▶ search (Exa / SearXNG) ─┐
                    ├─▶ Playwright Chromium ────┼──▶ clean markdown back to the agent
                    └─▶ fetch / yt-dlp / finance┘
```

## Why SURF

- **Runs locally.** No hosted scraping service, no per-page billing. The browser, cookies and downloads stay on your machine.
- **Built for agents.** Output is compact, readable markdown sized for a context window, not raw HTML. Tool descriptions and bundled skills tell the agent which tool to use when.
- **The agent gets only the tools it needs.** Tools are split into four profiles (`web`, `browse`, `ui`, `finance`). A research agent never sees click/type tools, and each specialist profile needs its own key.
- **Handles real-world sites.** It uses a real Chromium with persistent profiles, headed fallback for JavaScript-heavy or protected pages, browser-cookie fetches and conservative ad blocking.
- **Safe defaults.** It binds to loopback only, blocks private-network egress (SSRF), sandboxes downloads to known folders, and runs a hardened Docker image (read-only, no capabilities).

## Features

### `web`: research (keyless, 4 tools)
| Tool | What it does |
|---|---|
| `web_search` | Web search via Exa (if keyed) or SearXNG, re-ranked by keyword + semantic (embedding) relevance and filtered by score |
| `web_extract` | Reads up to 10 URLs in parallel as clean markdown. `refine_query` keeps only the relevant sections |
| `web_fetch` | Bounded public GET for APIs and raw files |
| `youtube_transcript` | Timestamped captions for a YouTube video, also saved as markdown |

### `browse`: read-only browser (16 tools)
One-shot rendered reads (`browser_browse`), multi-step sessions, page snapshots, link and structured-data extraction, screenshots, console logs, **network capture** (discover the XHR/JSON APIs behind a page) and file downloads.

### `ui`: interactive browser (22 tools)
Everything in `browse`, plus click, type, key presses, select, hover and viewport resize. Element handles come from snapshots and are verified before each action, so it suits end-to-end UI testing and agent-driven flows.

### `finance`: structured market data (6 tools)
Analyst consensus, insider transactions, corporate actions, macro (yields, CDS, FX), equity risk premium and a US equity snapshot. Each one reads from a curated list of sources in priority order and returns fixed-format markdown with the source, an as-of date and explicit `MISSING` fields. It supports US and Indian markets.

### Also included
- **Three ways in:** MCP over stdio, MCP over Streamable HTTP (`/mcp/<profile>`), and a plain HTTP API with a small CLI (`./surf search …`).
- **Document parsing:** PDF, DOCX and XLSX downloads come back as text.
- **Agent skills** in `skills/`: one ready-to-use skill per profile.

## Quickstart

> **Installing with an AI agent?** Point it at [docs/INSTALL.md](docs/INSTALL.md). It covers every step, including embeddings, with a check after each one.

### Option A: Docker (full stack, recommended)

Includes SearXNG (search with no API key) and a local embeddings server for ranking.

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
cp .env.docker.example .env.docker
# Set SEARXNG_SECRET (e.g. `openssl rand -hex 32`). Everything else is optional.
docker compose --env-file .env.docker --profile embeddings up --build -d
./surf preflight          # service, SearXNG, embeddings, outbound fetch → [ok]
```

SURF is now at `http://127.0.0.1:17777`. Point an MCP client at `http://127.0.0.1:17777/mcp/web`. The first boot downloads a ~140 MB embedding model.

### Option B: Local Python

Tested on Python 3.12 (Docker image) and 3.14.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python surfctl.py mcp          # stdio MCP server, `web` profile
```

Extract, fetch and transcripts work right away. For `web_search`, either set `SURF_EXA_API_KEY` or run SearXNG at `http://localhost:8888` (or set `SURF_SEARXNG_BASE_URL`). For good ranking, also set up embeddings (next section).

### Connect your agent

Claude Code:

```bash
claude mcp add surf \
  -e SURF_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1 -e SURF_EMBEDDING_MODEL=nomic-embed-text \
  -- /path/to/SURF/.venv/bin/python /path/to/SURF/surfctl.py mcp
```

Any MCP client (JSON config):

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

To use the browser, UI or finance tools, add `--profile browse|ui|finance` and set the matching key, e.g. `SURF_BROWSE_KEY="$(openssl rand -hex 24)"`. A profile with no key set stays disabled.

### Try it from the shell

```bash
export SURF_URL=127.0.0.1:17777
./surf preflight
./surf search "Python asyncio tutorial" --max-results 3
./surf extract https://docs.python.org/3/
./surf transcript https://www.youtube.com/watch?v=VIDEO_ID
```

## Embeddings (search ranking)

Search engines return results in their own order. SURF re-scores each result against your query: **60% keyword match (BM25) + 40% semantic similarity** from an embedding model, then drops anything below a relevance threshold. `web_extract`'s `refine_query` uses the same embeddings to keep only the sections of a page that match.

Without embeddings, SURF falls back to keywords alone. It still works, but it's easily fooled. For "how to write async code in python", keyword-only scoring ranks a pet-snake care guide (0.71) above an actual asyncio tutorial (0.43). Embeddings fix that kind of mistake.

| Setup | How |
|---|---|
| **Docker** | `--profile embeddings` (above). Runs a CPU llama.cpp server with `nomic-embed-text-v1.5` at `http://embeddings:8080/v1` |
| **Local** | `ollama pull nomic-embed-text`, then `SURF_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1` and `SURF_EMBEDDING_MODEL=nomic-embed-text` |
| **Your own** | Any OpenAI-compatible `/v1/embeddings` endpoint (LiteLLM, OpenAI, vLLM). Set `SURF_EMBEDDING_BASE_URL`, `_MODEL` and `_API_KEY` |

Embeddings are **off until `SURF_EMBEDDING_BASE_URL` is set**. Check them with `./surf preflight` (the `embeddings` line) or `GET /health/embeddings`, which reports `ready`, `down` or `disabled` plus a hint. Nomic models rank best, because SURF adds Nomic's `search_query:` / `search_document:` prefixes to its inputs. Details are in [docs/INSTALL.md](docs/INSTALL.md#using-a-different-embeddings-provider).

## Other options

| Setting | Effect |
|---|---|
| `SURF_EXA_API_KEY` | Uses Exa as the primary search provider, with SearXNG as fallback |
| `SURF_OUTBOUND_ALLOWED_HOSTS` | Lets SURF reach specific internal hosts (private networks are blocked by default) |

See [docs/REFERENCE.md](docs/REFERENCE.md) for every setting and endpoint.

## Use responsibly

SURF is for occasional browsing and research, **not** high-volume crawling. It does not solve CAPTCHAs or bypass logins or access controls, and it isn't meant to. Keep request volume low, respect each site's terms of service, and back off on 403/429 or challenge pages.

## Docs

- [docs/INSTALL.md](docs/INSTALL.md): step-by-step setup with checks (good for agents)
- [USAGE.md](USAGE.md): agent workflows and JSONL examples
- [docs/REFERENCE.md](docs/REFERENCE.md): full configuration, HTTP API and Docker details
- [ARCHITECTURE.md](ARCHITECTURE.md): how the pieces fit together
- [docs/adr-001-interaction-contract.md](docs/adr-001-interaction-contract.md): design of the UI interaction contract

## License

[MIT](LICENSE)
