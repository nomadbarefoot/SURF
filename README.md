# SURF

**The whole web toolkit for AI agents, in one local MCP server, with no API keys.** SURF gives an agent (Claude, Codex, a local model, or any MCP client) web search, clean page reading, YouTube transcripts, a real browser for automation and UI testing, and structured finance data, all running on your own machine.

```bash
claude mcp add surf -- uvx --from git+https://github.com/nomadbarefoot/SURF surf-mcp
```

That's the whole install: search works immediately, and Chromium downloads itself the first time a browser tool runs.

```
agent ──MCP──▶ SURF ──▶ search (Exa, keyless / SearXNG) ─┐
                    ├─▶ Playwright Chromium ─────────────┼──▶ clean markdown back to the agent
                    └─▶ fetch / yt-dlp / finance ────────┘
```

## Why SURF

- **Everything in one place.** Search, reading, browsing, UI automation and data come from one server, with one install and one consistent output style, instead of five separate MCP servers.
- **No keys, no bills.** Search uses Exa's free endpoint out of the box. There's no hosted scraping service or per-page pricing, and the browser, cookies and downloads stay on your machine.
- **Built for agents.** Output is compact markdown sized for a context window, not raw HTML. Tool descriptions and bundled skills tell the agent which tool to use when.
- **Each agent gets only the tools it needs.** Combine profiles per agent (`--profile web,browse`). A research agent never sees click/type tools.
- **Handles real-world sites.** It uses a real Chromium with persistent profiles, headed fallback for JavaScript-heavy or protected pages, browser-cookie fetches and conservative ad blocking.
- **Safe defaults.** It binds to loopback only, blocks private-network egress (SSRF), sandboxes downloads to known folders, and runs a hardened Docker image (read-only, no capabilities).

## Features

### `web`: research (4 tools)
| Tool | What it does |
|---|---|
| `web_search` | Web search via Exa (**no API key needed**; a key raises limits) with optional SearXNG fallback, re-ranked by keyword + semantic (embedding) relevance and filtered by score |
| `web_extract` | Reads up to 10 URLs in parallel as clean markdown. `refine_query` keeps only the relevant sections |
| `web_fetch` | Bounded public GET for APIs and raw files |
| `youtube_transcript` | Timestamped captions for a YouTube video, also saved as markdown (`[youtube]` extra) |

### `browse`: read-only browser (16 tools)
One-shot rendered reads (`browser_browse`), multi-step sessions, page snapshots, link and structured-data extraction, screenshots, console logs, **network capture** (discover the XHR/JSON APIs behind a page) and file downloads.

### `ui`: interactive browser (22 tools)
Everything in `browse`, plus click, type, key presses, select, hover and viewport resize. Element handles come from snapshots and are verified before each action, so it suits end-to-end UI testing and agent-driven flows.

### `finance`: structured market data (6 tools)
Analyst consensus, insider transactions, corporate actions, macro (yields, CDS, FX), equity risk premium and a US equity snapshot. Each one reads from a curated list of sources in priority order and returns fixed-format markdown with the source, an as-of date and explicit `MISSING` fields. It supports US and Indian markets.

### Also included
- **Three ways in:** MCP over stdio, MCP over Streamable HTTP (`/mcp/<profile>`), and a plain HTTP API with a small CLI (`surf search …`).
- **Document parsing:** PDF, DOCX and XLSX downloads come back as text (`[docs]` extra).
- **Agent skills** in `skills/`: one ready-to-use skill per profile.

## Quickstart

> **Installing with an AI agent?** Point it at [docs/INSTALL.md](docs/INSTALL.md). It covers every step, including embeddings, with a check after each one.

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`). Python 3.12+ is fetched automatically if you don't have it.

### Claude Code

```bash
claude mcp add surf -- uvx --from git+https://github.com/nomadbarefoot/SURF surf-mcp
```

### Any MCP client (JSON config)

```json
{
  "mcpServers": {
    "surf": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/nomadbarefoot/SURF", "surf-mcp", "--profile", "web"],
      "env": {
        "SURF_EMBEDDING_BASE_URL": "http://127.0.0.1:11434/v1",
        "SURF_EMBEDDING_MODEL": "nomic-embed-text"
      }
    }
  }
}
```

The `env` block turns on semantic ranking (see [Embeddings](#embeddings-search-ranking)). Leave it out to start with keyword ranking only.

### Optional extras

```bash
# YouTube transcripts (+~100 MB) and PDF/DOCX/XLSX parsing (+~26 MB)
uvx --from "surf-web[all] @ git+https://github.com/nomadbarefoot/SURF" surf-mcp
# Pre-download Chromium (~2 min) instead of waiting on the first browser call
uvx --from git+https://github.com/nomadbarefoot/SURF playwright install chromium
```

Use `[youtube]` or `[docs]` to pick one. Runtime data (browser profiles, downloads, caches) lives in `~/.surf`; set `SURF_HOME` to move it.

### Choose the tools each agent gets

Add `--profile` after `surf-mcp`:

| `--profile` | Tools | Good for |
|---|---|---|
| `web` (default) | 4 | research: search, read pages, fetch, transcripts |
| `web,browse` | 20 | research plus rendered pages, screenshots, network capture |
| `web,ui` | 26 | everything above plus clicking, typing and UI testing |
| `web,finance` | 10 | research plus structured market data |
| `all` | 32 | everything |

Over stdio no keys are needed: SURF runs in-process and authorizes itself with throwaway per-process keys. Add `--require-keys` (or `SURF_STDIO_REQUIRE_KEYS=true`) to insist on explicit `SURF_*_KEY` values. Over HTTP (`/mcp/web`, `/mcp/browse`, `/mcp/ui`, `/mcp/finance`), the specialist profiles always need their own key.

### Docker (HTTP service)

Use this for a long-running server that several agents share over HTTP. It runs SURF plus a local embeddings server.

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build -d
./surf preflight          # service, search, embeddings, outbound fetch → [ok]
```

Then point an MCP client at `http://127.0.0.1:17777/mcp/web`. The first boot downloads a ~140 MB embedding model. Add `searxng` to `COMPOSE_PROFILES` in `.env.docker` for a self-hosted search fallback.

### From source (development)

```bash
git clone https://github.com/nomadbarefoot/SURF.git && cd SURF
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python surfctl.py mcp --profile web
```

In a checkout, runtime data stays in `./data`.

## Embeddings (search ranking)

Search engines return results in their own order. SURF re-scores each result against your query: **60% keyword match (BM25) + 40% semantic similarity** from an embedding model, then drops anything below a relevance threshold. `web_extract`'s `refine_query` uses the same embeddings to keep only the sections of a page that match.

Without embeddings, SURF falls back to keywords alone. It still works, but it's easily fooled. For "how to write async code in python", keyword-only scoring ranks a pet-snake care guide (0.71) above an actual asyncio tutorial (0.43). Embeddings fix that kind of mistake.

Bring your own, or use one of these:

| Setup | How |
|---|---|
| **Ollama** (local) | `ollama pull nomic-embed-text`, then `SURF_EMBEDDING_BASE_URL=http://127.0.0.1:11434/v1` and `SURF_EMBEDDING_MODEL=nomic-embed-text` |
| **Docker** | On by default (`COMPOSE_PROFILES=embeddings` in `.env.docker`). Runs a CPU llama.cpp server with `nomic-embed-text-v1.5` at `http://embeddings:8080/v1` |
| **Anything else** | Any OpenAI-compatible `/v1/embeddings` endpoint (LiteLLM, OpenAI, vLLM). Set `SURF_EMBEDDING_BASE_URL`, `_MODEL` and `_API_KEY` |

Embeddings are **off until `SURF_EMBEDDING_BASE_URL` is set**. Check them with `surf preflight` (the `embeddings` line) or `GET /health/embeddings`, which reports `ready`, `down` or `disabled` plus a hint. Nomic models rank best, because SURF adds Nomic's `search_query:` / `search_document:` prefixes to its inputs. Details are in [docs/INSTALL.md](docs/INSTALL.md#using-a-different-embeddings-provider).

## Other options

| Setting | Effect |
|---|---|
| `SURF_EXA_API_KEY` | Uses the Exa API directly. Without a key, SURF uses Exa's free hosted endpoint, which is rate-limited (SURF queues requests and retries) |
| `SURF_SEARXNG_BASE_URL` | Self-hosted SearXNG as a fallback search provider. In Docker, add `searxng` to `COMPOSE_PROFILES` and set `SEARXNG_SECRET` |
| `SURF_EXA_KEYLESS_ENABLED=false` | Never send queries to Exa without a key (e.g. SearXNG-only for privacy) |
| `SURF_HOME` | Where runtime data lives (default `~/.surf` when installed, `./` in a checkout) |
| `SURF_BROWSER_AUTO_INSTALL=false` | Don't download Chromium automatically |
| `SURF_OUTBOUND_ALLOWED_HOSTS` | Lets SURF reach specific internal hosts (private networks are blocked by default) |

Settings can also go in `~/.surf/.env`. See [docs/REFERENCE.md](docs/REFERENCE.md) for every setting and endpoint.

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
