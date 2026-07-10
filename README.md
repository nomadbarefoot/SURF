# SURF

SURF is a local browser and web-research substrate for agents and one-off scripts. Agents use an MCP stdio bridge that runs the FastAPI app in-process, launches local Chromium through Playwright, captures network responses, and provides fetch endpoints that can reuse browser-session cookies without binding a local port.

Beyond single-page browsing, SURF includes **web search** (`search_query` via SearXNG metasearch) and **parallel content extraction** (`search_extract` with headless-to-headed retry, challenge handling, and optional embedding-based section filtering). A **Finance Pack** (`finance_*` tools) adds curated source ladders that return structured markdown for recurring market-data needs.

The goal is reliable occasional browsing, scraping, and research. SURF supports normal browser workflows, headed sessions, persistent cookies, conservative ad blocking, browser-like fetches, search-then-extract pipelines, and typed financial extractors. It is not a CAPTCHA solver, credential bypass tool, or high-volume crawler.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Run the agent MCP bridge:

```bash
.venv/bin/python surfctl.py mcp
```

Raw JSONL stdio is available for scripts:

```bash
.venv/bin/python surfctl.py stdio
```

Send one JSON object per line:

```jsonl
{"id":"health","method":"GET","path":"/health/live"}
{"id":"create","method":"POST","path":"/sessions/","data":{"config":{"profile_id":"agent-default","persist_profile":true}}}
{"id":"quit","method":"QUIT"}
```

Manual HTTP development server:

```bash
.venv/bin/python start_surf.py
```

OpenAPI docs are available at `/docs` when `SURF_DEBUG=true`.

## Auth

SURF defaults to `SURF_AUTH_MODE=loopback`, which requires no bearer token but only works when bound to a loopback host.

For stricter local process isolation:

```bash
export SURF_AUTH_MODE=token
export SURF_API_TOKEN="$(openssl rand -hex 24)"
.venv/bin/python start_surf.py
```

Then send `Authorization: Bearer $SURF_API_TOKEN`.

SURF refuses `loopback` auth on non-loopback hosts. Runtime demo login and runtime API-key creation are disabled; configure `SURF_API_TOKEN` instead.

## Quick Agent Flow

SURF exposes three MCP tool families: `browser_*`, `search_*`, and `finance_*`.

### Browser automation

- `browser_create_session`
- `browser_network_start` when XHR/API discovery matters.
- `browser_navigate`
- `browser_observe`
- `browser_links` for full DOM link extraction on disclosure/download pages.
- `browser_fetch` with `backend="browser"` and `session_id` when cookies matter.
- `browser_download`; pass `output_dir` when the caller needs the file in its own workspace.
- `browser_close_session`

### Web search and extraction

No session required — search and extract spin up ephemeral browser sessions internally.

1. `search_query` — run a SearXNG metasearch query; returns ranked results with titles, snippets, URLs, source engine, and hybrid relevance scores.
2. Pick URLs from the results.
3. `search_extract` — fetch full page content from up to 10 URLs in parallel. Pass `refine_query` to keep only sections relevant to your research topic. Pass a `relevance` map (URL → score from `search_query`) to prioritize headed retries for high-value failures.

Example pipeline:

```json
{"tool": "search_query", "query": "India Nifty 50 outlook 2026", "max_results": 5}
{"tool": "search_extract", "urls": ["https://example.com/article"], "refine_query": "Nifty 50 outlook 2026", "content_mode": "reader"}
```

SearXNG must be reachable at `SURF_SEARXNG_BASE_URL` (default `http://localhost:8888`). SURF can autostart a Docker container when `SURF_SEARXNG_AUTOWAKE_ENABLED=true`. Check reachability with `GET /health/searxng?autowake=true`.

Optional: set `SURF_EMBEDDING_BASE_URL` and `SURF_EMBEDDING_MODEL` for semantic relevance scoring in search and section filtering during extraction. Without an embedder, search falls back to BM25-only scoring.

### Finance Pack

Typed endpoints that walk curated source ladders and return fixed markdown (source, as-of, confidence). Prefer these over generic search for recurring ledger data. See `FINANCE_PACK.md` for design detail.

- `finance_consensus(symbol, market)` — analyst PT mean/range, EPS estimates
- `finance_insider(symbol, market)` — insider/promoter transactions and pledges
- `finance_corp_actions(symbol, market)` — buybacks, dividends, splits
- `finance_macro(country)` — 10Y yield, CDS, FX spot, FX implied vol
- `finance_erp(home, foreign)` — Damodaran ERP and country default spreads
- `finance_snapshot_us(symbol)` — degraded US-book basics (price, mcap, P/E)

Probe ladder health with `GET /health/finance`. Run the harness with `.venv/bin/python scripts/run_finance_tool_harness.py`.

## API Surface

Sessions:

- `POST /sessions/`
- `GET /sessions/`
- `GET /sessions/monitor`
- `POST /sessions/{session_id}/touch`
- `POST /sessions/reap`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}?force=false`

Browser:

- `POST /browser/navigate`
- `POST /browser/observe`
- `POST /browser/wait`
- `POST /browser/extract`
- `POST /browser/interact`
- `POST /browser/screenshot`
- `POST /browser/download/click`
- `POST /browser/network/start`
- `POST /browser/network/stop`
- `GET /browser/network/events/{session_id}`

Fetch:

- `POST /fetch/request`

Downloads:

- `GET /downloads/`
- `GET /downloads/{download_id}`
- `GET /downloads/{download_id}/content`
- `DELETE /downloads/{download_id}`

Search:

- `POST /search/query`
- `POST /search/extract`
- `GET /search/stats`

Finance:

- `POST /finance/consensus`
- `POST /finance/insider`
- `POST /finance/corp_actions`
- `POST /finance/macro`
- `POST /finance/erp`
- `POST /finance/snapshot_us`

Health:

- `GET /health/`
- `GET /health/live`
- `GET /health/ready`
- `GET /health/metrics`
- `GET /health/runtime`
- `GET /health/searxng`
- `GET /health/finance`

## Session Config

Important keys:

- `profile_id`: stable local browser profile name. Only one active persistent session can use a profile at a time.
- `silent`: defaults to `true`.
- `headed`: set `true` to show the browser.
- `background_headed`: defaults to `true`, placing headed windows off-screen for protected-site fallback.
- `persist_profile`: defaults to `true`.
- `stealth_strategy`: `minimal`, `none`, or `legacy`; default is `minimal`.
- `block_mode`: `off`, `conservative`, or `token_saver`.
- `content_mode`: `compact`, `reader`, `data`, or `full`.
- `locale`, `timezone_id`, `viewport`, `user_agent`.

Defaults are tuned for one-off agent work: silent browser, persistent local cookies, conservative blocking, stable browser identity, 3 active browser sessions, 1 headed session, 10 minute session idle timeout, 60 second browser-runtime idle teardown, and 2 hour hard TTL.

## Runtime Lifecycle

For agents, `surfctl.py mcp` and `surfctl.py stdio` keep SURF in-process and exit when the stdio process exits. They do not bind TCP or Unix sockets. Playwright/Chromium starts lazily on browser-session creation and stops after `SURF_BROWSER_IDLE_TIMEOUT_SECONDS` when no sessions remain.

`start_surf.py` is only the optional manual HTTP development server.

## Observe Modes

`/browser/observe` is the preferred first call for agents. It returns current URL, title, visible text, links, forms, action candidates, tables, warnings, token estimate, blocker stats, per-navigation blocker deltas, and optional screenshot path.

Modes:

- `compact`: general agent view with common noise removed.
- `reader`: article/main-content focused view.
- `data`: removes most navigation/forms/buttons and favors tables/text.
- `full`: raw visible body text.

## Fetch Backends

- `auto`: uses `curl_cffi` when installed, otherwise `httpx`.
- `httpx`: normal HTTP client.
- `browser`: Playwright browser-context request sharing cookies with the active session.
- `curl_cffi`: browser-like TLS/session fetches.
- `cloudscraper`: optional backend if installed.

Browser-context fetches are API calls made from the browser context; they reuse cookies but are not counted in page adblock metrics.

Set `save_to_downloads=true` to store a response body under `data/downloads/`. Pass `output_dir` plus `filename` when the caller needs a directly readable artifact path; SURF returns both `path` and `absolute_path`. Existing files are refused unless `overwrite=true`.

Session creation failures return local diagnostic detail, including exception type, message, SURF error code when available, and hints for common launch problems such as sandbox-denied Chromium startup.

## Corporate Actions Probe

For NSE/BSE-style protected sites, use a headed session first:

```json
{
  "config": {
    "profile_id": "agent-protected",
    "headed": true,
    "persist_profile": true,
    "block_mode": "conservative"
  }
}
```

Then warm the site homepage before calling API endpoints with browser cookies.

NSE RELIANCE:

```json
{
  "method": "GET",
  "url": "https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=RELIANCE",
  "backend": "browser",
  "session_id": "<session_id>",
  "timeout": 60000
}
```

BSE RELIANCE:

```json
{
  "method": "GET",
  "url": "https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w?scripcode=500325",
  "backend": "curl_cffi",
  "session_id": "<session_id>",
  "headers": {
    "Referer": "https://www.bseindia.com/"
  },
  "timeout": 60000
}
```

## Operational Rules

- Keep request volume low and respect site terms.
- Prefer browser navigation first for protected or JS-heavy sites, then use fetch with browser cookies for specific endpoints.
- Use headed mode when a site requires normal visible-browser interaction.
- Stop or back off on 403, 429, CAPTCHA, login, or challenge warnings.
- Do not automate CAPTCHA solving or use SURF to bypass access controls.
- Leave `user_agent` unset unless the user explicitly needs an override.

Runtime browser profiles, downloads, and filter-list caches live under `data/` and are ignored by Git.

## Search and Extraction

`POST /search/query` accepts:

- `query` (required)
- `max_results` (default 10, max 50)
- `engines`, `categories` (optional SearXNG filters)
- `language` (default `en`)
- `time_range` (optional: `day`, `week`, `month`, `year`)

Returns `{success, results[], ms}` where each result has `title`, `url`, `snippet`, `engine`, and `relevance` (0–1 hybrid BM25 + semantic score).

`POST /search/extract` accepts:

- `urls` (required, 1–10 URLs)
- `content_mode` (default `reader`; also `compact`, `data`, `full`)
- `max_text_length` (default 8000)
- `relevance` (optional URL→score map from search)
- `refine_query` (optional topic for embedding-based section filtering)

Extraction runs headless first, then retries failed or challenge-blocked URLs in headed mode. Protected sites may return `challenge_blocked: true` — back off rather than retry aggressively.

## Agent Integration

Use `surfctl.py mcp` as a stdio MCP server. MCP server instructions mark SURF as the preferred local tool for browsing, scraping, downloads, browser-cookie fetches, web search, content extraction, and structured financial data.

## Verification

```bash
.venv/bin/python -m compileall main.py controllers services models config core utils examples
.venv/bin/python examples/agent_usage.py
```
