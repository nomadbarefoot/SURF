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
- **The agent gets only the tools it needs.** Tools are split into four profiles (`web`, `browse`, `ui`, `finance`) that you combine per agent (`--profile web,browse`). A research agent never sees click/type tools, and over HTTP each specialist profile needs its own key.
- **Handles real-world sites.** It uses a real Chromium with persistent profiles, headed fallback for JavaScript-heavy or protected pages, browser-cookie fetches and conservative ad blocking.
- **Safe defaults.** It binds to loopback only, blocks private-network egress (SSRF), sandboxes downloads to known folders, and runs a hardened Docker image (read-only, no capabilities).

## Features

### `web`: research (keyless, 4 tools)
| Tool | What it does |
|---|---|
| `web_search` | Web search via Exa (**no API key needed**; a key raises limits) with optional SearXNG fallback, re-ranked by keyword + semantic (embedding) relevance and filtered by score |
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

One container for SURF, plus a local embeddings server for ranking. Search needs no API key.

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
cp .env.docker.example .env.docker
# Optional: SURF_EXA_API_KEY, or add `searxng` to COMPOSE_PROFILES for a self-hosted fallback.
docker compose --env-file .env.docker up --build -d
./surf preflight          # service, search, embeddings, outbound fetch → [ok]
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

Search, extract, fetch and transcripts work right away with no keys. For good ranking, also set up embeddings (next section).

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

### Choose the tools each agent gets

`--profile` picks which tools the agent sees. Use it to give each agent only what it needs:

| `--profile` | Tools | Good for |
|---|---|---|
| `web` (default) | 4 | research: search, read pages, fetch, transcripts |
| `web,browse` | 20 | research plus rendered pages, screenshots, network capture |
| `web,ui` | 26 | everything above plus clicking, typing and UI testing |
| `web,finance` | 10 | research plus structured market data |
| `all` | 32 | everything |

Over stdio no keys are needed: SURF runs in-process and authorizes itself with throwaway per-process keys. Add `--require-keys` (or `SURF_STDIO_REQUIRE_KEYS=true`) to insist on explicit `SURF_*_KEY` values. Over HTTP (`/mcp/web`, `/mcp/browse`, `/mcp/ui`, `/mcp/finance`), the specialist profiles always need their own key.

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
| **Docker** | On by default (`COMPOSE_PROFILES=embeddings` in `.env.docker`). Runs a CPU llama.cpp server with `nomic-embed-text-v1.5` at `http://embeddings:8080/v1` |
| **Local** | `ollama pull nomic-embed-text`, then `SURF_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1` and `SURF_EMBEDDING_MODEL=nomic-embed-text` |
| **Your own** | Any OpenAI-compatible `/v1/embeddings` endpoint (LiteLLM, OpenAI, vLLM). Set `SURF_EMBEDDING_BASE_URL`, `_MODEL` and `_API_KEY` |

Embeddings are **off until `SURF_EMBEDDING_BASE_URL` is set**. Check them with `./surf preflight` (the `embeddings` line) or `GET /health/embeddings`, which reports `ready`, `down` or `disabled` plus a hint. Nomic models rank best, because SURF adds Nomic's `search_query:` / `search_document:` prefixes to its inputs. Details are in [docs/INSTALL.md](docs/INSTALL.md#using-a-different-embeddings-provider).

## Other options

| Setting | Effect |
|---|---|
| `SURF_EXA_API_KEY` | Uses the Exa API directly. Without a key, SURF uses Exa's free hosted endpoint, which is rate-limited (SURF queues requests and retries) |
| `SURF_SEARXNG_BASE_URL` | Self-hosted SearXNG as a fallback search provider. In Docker, add `searxng` to `COMPOSE_PROFILES` and set `SEARXNG_SECRET` |
| `SURF_EXA_KEYLESS_ENABLED=false` | Never send queries to Exa without a key (e.g. SearXNG-only for privacy) |
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
