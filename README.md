# SURF

SURF is a local browser and web-research substrate for agents and one-off scripts. It exposes profile-scoped MCP over stdio and Streamable HTTP, launches local Chromium through Playwright, captures network responses, and provides fetch endpoints that can reuse browser-session cookies.

Beyond single-page browsing, SURF includes **web search** (`web_search`), **parallel content extraction** (`web_extract`), and **YouTube transcripts** (`youtube_transcript`). A **Finance Pack** (`finance_*` tools) adds structured market-data retrieval.

The goal is reliable occasional browsing, scraping, and research. SURF supports normal browser workflows, headed sessions, persistent cookies, conservative ad blocking, browser-like fetches, search-then-extract pipelines, and typed financial extractors. It is not a CAPTCHA solver, credential bypass tool, or high-volume crawler.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Run the keyless web MCP bridge:

```bash
.venv/bin/python surfctl.py mcp
```

Specialist stdio profiles require their matching environment key:

```bash
SURF_BROWSE_KEY="$(openssl rand -hex 24)" .venv/bin/python surfctl.py mcp --profile browse
SURF_UI_KEY="$(openssl rand -hex 24)" .venv/bin/python surfctl.py mcp --profile ui
SURF_FINANCE_KEY="$(openssl rand -hex 24)" .venv/bin/python surfctl.py mcp --profile finance
```

Raw JSONL stdio is available for scripts. Select a specialist profile for
browser or finance routes:

```bash
.venv/bin/python surfctl.py stdio
SURF_BROWSE_KEY=… .venv/bin/python surfctl.py stdio --profile browse
```

Send one JSON object per line:

```jsonl
{"id":"health","method":"GET","path":"/health/live"}
{"id":"quit","method":"QUIT"}
```

Manual HTTP development server:

```bash
.venv/bin/python start_surf.py
```

The repository-local HTTP CLI is available as `./surf`:

```bash
export SURF_URL=127.0.0.1:17777
./surf preflight
./surf search "Python official documentation" --max-results 3
./surf fetch https://example.com
./surf transcript https://www.youtube.com/watch?v=VIDEO_ID
```

Use `--json` for machine-readable output and `--timeout SECONDS` to override
the default 30-second HTTP timeout. `surf preflight` probes liveness, runtime
health, SearXNG, and one outbound URL without starting or mutating services.

OpenAPI docs are available at `/docs` when `SURF_DEBUG=true`.

## Auth

SURF uses capability profiles instead of a universal token. `web` is keyless on loopback or when `SURF_KEYLESS_WEB_ENABLED=true`; its `web_fetch` tool is restricted to a bounded public GET. `browse`, `ui`, and `finance` require distinct keys, and `ops` protects operational HTTP routes.

Configure only the profiles the deployment needs; an unset specialist key disables that profile:

```bash
export SURF_BROWSE_KEY="$(openssl rand -hex 24)"
export SURF_UI_KEY="$(openssl rand -hex 24)"
export SURF_FINANCE_KEY="$(openssl rand -hex 24)"
export SURF_OPS_KEY="$(openssl rand -hex 24)"
.venv/bin/python start_surf.py
```

The Streamable HTTP MCP endpoints are `/mcp/web`, `/mcp/browse`, `/mcp/ui`, and `/mcp/finance`. Send the selected profile key as a bearer token. A key never grants access to another profile.

The four canonical skill packages live under `skills/`; their guidance is also used as the MCP server instructions.

## Docker

SURF includes a Dockerfile and a `docker-compose.yml` that packages the HTTP service with SearXNG. The image uses the official Playwright Python base image. The pinned `yt-dlp[default,deno]` dependency supplies YouTube caption extraction and its JavaScript runtime; transcript-only operation does not require ffmpeg. Semantic embeddings are supplied by LiteLLM rather than a local ML runtime.

### Quickstart

```bash
cp .env.docker.example .env.docker
# Set the specialist keys you need, plus SEARXNG_SECRET and SURF_EMBEDDING_API_KEY
docker compose --env-file .env.docker \
  -f docker-compose.yml -f docker-compose.aegis.yml up --build
```

SURF is available only on host loopback at `http://127.0.0.1:17777`. SearXNG and its ephemeral Valkey limiter store are private to the compose network.

### Profiles inside the container

Compose explicitly enables keyless `web` because the service is published only on host loopback. Specialist profiles remain disabled until their independent keys are set in `.env.docker`:

```bash
# Generate independent values and put them in .env.docker
openssl rand -hex 24  # repeat for each enabled SURF profile key
openssl rand -hex 32  # SEARXNG_SECRET
```

Specialist HTTP and MCP clients send the matching key as `Authorization: Bearer …`. Keep `.env.docker` local — it is gitignored; use `.env.docker.example` as the template.

Optional: set `SURF_EXA_API_KEY` in `.env.docker` for Exa-backed search. Without it, search falls back to the compose-only SearXNG service at `http://searxng:8080`.

Semantic ranking and section refinement use the OpenAI-compatible LiteLLM embedding route. Set `SURF_EMBEDDING_API_KEY` to a restricted LiteLLM key. The Docker defaults call the `embed-text` model alias at `http://litellm:4000/v1` and request 768 dimensions; override `SURF_EMBEDDING_BASE_URL` for a different deployment. Nomic retrieval prefixes are applied once at the query/document boundary. If the endpoint is unavailable, ranking falls back to BM25 and refinement leaves sections unchanged.

### LiteLLM network

The base stack attaches SURF only to `surf-net`. To use LiteLLM from the Aegis stack, attach SURF to its shared external Docker network with the override:

```bash
docker compose --env-file .env.docker \
  -f docker-compose.yml -f docker-compose.aegis.yml up --build
```

### MCP transports

The Docker image serves the four Streamable HTTP MCP endpoints through `start_surf.py`. Host-side `surfctl.py mcp --profile …` remains available for stdio clients and runs FastAPI in-process.

### Persistent data

Compose mounts named volumes for:

- `data/` — browser profiles, downloads, adblock filter lists
- SearXNG configuration/cache; Valkey limiter state is deliberately ephemeral

### Headed sessions

`Xvfb` is installed and started by the entrypoint, so headed fallback and `background_headed` sessions work inside the container without a host display.

## Quick Agent Flow

SURF exposes four isolated MCP profiles: `web`, `browse`, `ui`, and `finance`.

### Browser automation

- `browser_create_session`
- `browser_network_start` when XHR/API discovery matters.
- `browser_navigate`
- `browser_snapshot`
- `browser_links` for full DOM link extraction on disclosure/download pages.
- `web_fetch` for a bounded public GET.
- `browser_download`; pass `output_dir` when the caller needs the file in its own workspace.
- `browser_close_session`

### Web search and extraction

No session required — search and extract spin up ephemeral browser sessions internally.

1. `web_search` — search the web and return ranked results.
2. Pick URLs from the results.
3. `web_extract` — fetch readable content from up to 10 URLs in parallel. Pass `refine_query` to keep only relevant sections.

Example pipeline:

```json
{"tool": "web_search", "query": "India Nifty 50 outlook 2026", "max_results": 5}
{"tool": "web_extract", "urls": ["https://example.com/article"], "refine_query": "Nifty 50 outlook 2026", "content_mode": "reader"}
```

SearXNG must be reachable at `SURF_SEARXNG_BASE_URL` (default `http://localhost:8888` outside compose). An authenticated `GET /health/searxng` is probe-only. When `SURF_SEARXNG_AUTOWAKE_ENABLED=true`, an authenticated `POST /health/searxng/autowake` may start the configured Docker runtime.

Semantic relevance scoring and section filtering use the OpenAI-compatible embedding endpoint configured by `SURF_EMBEDDING_BASE_URL` and `SURF_EMBEDDING_MODEL`. Host-side execution defaults to `http://127.0.0.1:4000/v1`; Compose uses `http://litellm:4000/v1`. Without a working endpoint, search falls back to BM25-only scoring and skips embedding-based filtering.

### Finance Pack

Typed endpoints that walk curated source ladders and return fixed markdown (source, as-of, confidence). Prefer these over generic search for recurring ledger data. See `research/FINANCE_PACK.md` for design detail.

- `finance_analyst_consensus(symbol, market)` — analyst PT mean/range, EPS estimates
- `finance_insider_transactions(symbol, market)` — insider/promoter transactions and pledges
- `finance_corporate_actions(symbol, market)` — buybacks, dividends, splits
- `finance_macro(country)` — 10Y yield, CDS, FX spot, FX implied vol
- `finance_equity_risk_premium(home, foreign)` — ERP and country default spreads
- `finance_us_snapshot(symbol)` — degraded US-book basics (price, mcap, P/E)

Probe ladder health with authenticated `GET /health/finance`. Run the harness with `.venv/bin/python scripts/run_finance_tool_harness.py`.

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
- `POST /browser/batch` (sequential operations on one session; 10-operation cap)
- `POST /browser/extract-structured`
- `POST /browser/detect-captcha`

Fetch:

- `POST /fetch/request`

Downloads:

- `GET /downloads/`
- `GET /downloads/{download_id}`
- `GET /downloads/{download_id}/content`
- `DELETE /downloads/{download_id}`

Screenshot artifacts:

- `GET /artifacts/{artifact_id}/content`

`POST /browser/screenshot` and screenshot-enabled `POST /browser/observe` return an
opaque `artifact_id` and `content_url`; container-local paths are not exposed. Fetch
the URL with the same bearer-token authorization required by other protected SURF
routes. The response carries media type `image/png`, the original filename via
`Content-Disposition`, and exact `size_bytes` in the creation response. Artifacts
use `SURF_DOWNLOAD_RETENTION_SECONDS` (24 hours by default); expired or unknown IDs
return 404.

YouTube transcripts use the same download sandbox and retention policy. The
response returns bounded timestamped text plus the complete Markdown download
record. Its `content_url` uses the authenticated downloads route; local
loopback callers can also use the returned path.

Search:

- `POST /search/query`
- `POST /search/extract`
- `GET /search/stats`

YouTube:

- `POST /youtube/transcript`

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
- `POST /health/searxng/autowake`
- `GET /health/finance`

Only `GET /health/live` is anonymous. Detailed health, readiness, metrics, runtime, SearXNG, and finance probes require the configured API token and return HTTP 503 when unhealthy.

In loopback mode, `/youtube/` follows the same free-tier policy as `/search/`
and `/fetch/`. Container deployments still require the global bearer token.

## YouTube Transcripts

`POST /youtube/transcript` and the `youtube_transcript` MCP tool accept one
public watch, Shorts, embed, or `youtu.be` URL. With no language preference,
SURF chooses the original manual track, then original automatic captions.
Pass ordered `languages`, set `allow_auto_captions=false` to require manual
captions, and use `max_text_length` to bound inline output.

V1 does not download audio or video and does not support playlists, live or
private videos, machine translation, speech-to-text fallback, or summarization.
Relevant settings are `SURF_YOUTUBE_TRANSCRIPT_TIMEOUT_SECONDS`,
`SURF_YOUTUBE_TRANSCRIPT_CONCURRENCY`,
`SURF_YOUTUBE_TRANSCRIPT_MAX_CAPTION_BYTES`,
`SURF_YOUTUBE_TRANSCRIPT_MAX_SEGMENTS`, and
`SURF_YOUTUBE_TRANSCRIPT_CACHE_TTL_SECONDS`.

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
- `ignore_https_errors`: defaults to `false`; enable only for a deliberately trusted test target.

Defaults are tuned for one-off agent work: silent browser, persistent local cookies, conservative blocking, stable browser identity, 3 active browser sessions, 1 headed session, 10 minute session idle timeout, 60 second browser-runtime idle teardown, and 2 hour hard TTL.

## Runtime Lifecycle

For agents, `surfctl.py mcp` and `surfctl.py stdio` keep SURF in-process and exit when the stdio process exits. They do not bind TCP or Unix sockets. Playwright/Chromium starts lazily on browser-session creation and stops after `SURF_BROWSER_IDLE_TIMEOUT_SECONDS` when no sessions remain.

`start_surf.py` is only the optional manual HTTP development server.

## Observe Modes

`/browser/observe` is the preferred first call for agents. It returns current URL, title, visible text, links, forms, action candidates, tables, warnings, token estimate, blocker stats, per-navigation blocker deltas, and optional screenshot artifact ID and content URL.

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

Set `save_to_downloads=true` to store a response body under `data/downloads/`. Caller-provided `output_dir` and screenshot paths must resolve beneath `SURF_EXPORT_ROOTS` (comma-separated); symlink escapes are rejected. SURF returns both `path` and `absolute_path`. Existing files are refused unless `overwrite=true`. Fetch bodies are capped by `SURF_MAX_RESPONSE_SIZE`, and JSON parsing has the separate `SURF_MAX_JSON_PARSE_SIZE` budget.

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
- `provider` (optional: `exa` or `searxng`)
- `fallback` (optional bool)
- `min_relevance` (optional 0–1 override for `SURF_SEARCH_RELEVANCE_THRESHOLD`)

Returns `{success, results[], ms}` where each result has `title`, `url`, `snippet`, `source`, and `relevance` (0–1 hybrid BM25 + semantic score). Results are sorted by relevance and filtered to scores `>= SURF_SEARCH_RELEVANCE_THRESHOLD` (default `0.5`). If no result reaches the threshold, the response returns `success: false`, an error message, and the top 3 results with `metadata.below_threshold: true`.

`POST /search/extract` accepts:

- `urls` (required, 1–10 URLs)
- `content_mode` (default `reader`; also `compact`, `data`, `full`)
- `max_text_length` (default 8000)
- `relevance` (optional URL→score map from search)
- `refine_query` (optional topic for embedding-based section filtering)

Extraction runs headless first, then retries failed or challenge-blocked URLs concurrently under the headed-session limit. The response reports `success_count`, `failure_count`, `partial`, and per-result `truncated`; an all-failed batch has top-level `success: false`. Protected sites may return `challenge_blocked: true` — back off rather than retry aggressively.

All browser, fetch, search-extract, redirect, and subresource destinations pass a shared egress policy. Private, loopback, link-local, reserved, multicast, and metadata-service addresses are blocked by default. Use narrow `SURF_OUTBOUND_ALLOWED_HOSTS` exceptions for trusted internal targets; avoid the global `SURF_OUTBOUND_ALLOW_PRIVATE_NETWORKS` escape hatch.

## Agent Integration

Use `surfctl.py mcp` as a stdio MCP server. MCP server instructions mark SURF as the preferred local tool for browsing, scraping, downloads, browser-cookie fetches, web search, content extraction, and structured financial data.

## Verification

```bash
.venv/bin/python -m compileall main.py controllers services models config core utils examples
.venv/bin/python examples/agent_usage.py
```
