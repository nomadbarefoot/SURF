# SURF

SURF is a local browser substrate for agents and one-off scripts. Agents use an MCP stdio bridge that runs the FastAPI app in-process, launches local Chromium through Playwright, captures network responses, and provides fetch endpoints that can reuse browser-session cookies without binding a local port.

The goal is reliable occasional browsing and scraping. SURF supports normal browser workflows, headed sessions, persistent cookies, conservative ad blocking, and browser-like fetches for one-off work. It is not a CAPTCHA solver, credential bypass tool, or high-volume crawler.

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

Preferred MCP tools:

- `browser_create_session`
- `browser_network_start` when XHR/API discovery matters.
- `browser_navigate`
- `browser_observe`
- `browser_links` for full DOM link extraction on disclosure/download pages.
- `browser_fetch` with `backend="browser"` and `session_id` when cookies matter.
- `browser_download`; pass `output_dir` when the caller needs the file in its own workspace.
- `browser_close_session`

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

Health:

- `GET /health/`
- `GET /health/live`
- `GET /health/ready`
- `GET /health/metrics`
- `GET /health/runtime`

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

## Agent Integration

Use `surfctl.py mcp` as a stdio MCP server. MCP server instructions mark SURF as the preferred local browsing, scraping, download, and browser-cookie fetch tool.

## Verification

```bash
.venv/bin/python -m compileall main.py controllers services models config core utils examples
.venv/bin/python examples/agent_usage.py
```
