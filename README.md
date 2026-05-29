# SURF

SURF is a local browser substrate for agents and one-off scripts. It runs a FastAPI daemon, launches local Chromium through Playwright, exposes browser actions over HTTP, captures network responses, and provides fetch endpoints that can reuse browser-session cookies.

The goal is reliable occasional browsing and scraping. SURF supports normal browser workflows, headed sessions, persistent cookies, conservative ad blocking, and browser-like fetches for one-off work. It is not a CAPTCHA solver, credential bypass tool, or high-volume crawler.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Start SURF:

```bash
.venv/bin/python start_surf.py
```

Or let an agent/helper start or discover it:

```bash
.venv/bin/python surfctl.py ensure
```

Default base URL:

```text
http://127.0.0.1:17777
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

Create a default silent persistent browser session:

```bash
curl -s http://127.0.0.1:17777/sessions/ \
  -H 'Content-Type: application/json' \
  -d '{"config":{"profile_id":"agent-default","persist_profile":true,"block_mode":"conservative"}}'
```

Navigate:

```bash
curl -s http://127.0.0.1:17777/browser/navigate \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SESSION_ID'","url":"https://www.nseindia.com/","wait_until":"domcontentloaded","timeout":90000}'
```

Observe:

```bash
curl -s http://127.0.0.1:17777/browser/observe \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SESSION_ID'","max_text_length":4000,"max_items":50}'
```

Fetch with browser cookies:

```bash
curl -s http://127.0.0.1:17777/fetch/request \
  -H 'Content-Type: application/json' \
  -d '{"method":"GET","url":"https://www.nseindia.com/api/marketStatus","backend":"browser","session_id":"'$SESSION_ID'","timeout":60000}'
```

Close:

```bash
curl -s -X DELETE http://127.0.0.1:17777/sessions/$SESSION_ID
```

Add `-H "Authorization: Bearer $SURF_API_TOKEN"` to each request when `SURF_AUTH_MODE=token`.

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
- `persist_profile`: defaults to `true`.
- `stealth_strategy`: `minimal`, `none`, or `legacy`; default is `minimal`.
- `block_mode`: `off`, `conservative`, or `token_saver`.
- `content_mode`: `compact`, `reader`, `data`, or `full`.
- `locale`, `timezone_id`, `viewport`, `user_agent`.

Defaults are tuned for one-off agent work: silent browser, persistent local cookies, conservative blocking, stable browser identity, 3 active browser sessions, 1 headed session, 10 minute session idle timeout, 60 second browser-runtime idle teardown, and 2 hour hard TTL.

## Daemon Lifecycle

SURF is designed as a resident thin daemon. The FastAPI shell stays available on loopback, while Playwright/Chromium starts lazily on browser-session creation and stops after `SURF_BROWSER_IDLE_TIMEOUT_SECONDS` when no sessions remain.

Use `surfctl.py` for agent-friendly local supervision:

```bash
.venv/bin/python surfctl.py status
.venv/bin/python surfctl.py ensure
.venv/bin/python surfctl.py stop
```

Agents should close sessions when finished and leave the daemon running. Use `/health/runtime` to inspect pid, active sessions, browser-runtime state, limits, and process-tree RSS.

## Observe Modes

`/browser/observe` is the preferred first call for agents. It returns current URL, title, visible text, links, forms, action candidates, tables, warnings, token estimate, blocker stats, per-navigation blocker deltas, and optional screenshot path.

Modes:

- `compact`: general agent view with common noise removed.
- `reader`: article/main-content focused view.
- `data`: removes most navigation/forms/buttons and favors tables/text.
- `full`: raw visible body text.

## Fetch Backends

- `auto`: currently uses `httpx`.
- `httpx`: normal HTTP client.
- `browser`: Playwright browser-context request sharing cookies with the active session.
- `curl_cffi`: browser-like TLS/session fetches.
- `cloudscraper`: optional backend if installed.

Browser-context fetches are API calls made from the browser context; they reuse cookies but are not counted in page adblock metrics.

Set `save_to_downloads=true` to store a response body under `data/downloads/`.

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

## Agent Skill

This repo includes a compact agent skill at `.agents/skills/surf/SKILL.md`. Install or copy that skill into an agent environment when you want agents to discover and use SURF consistently.

## Verification

```bash
.venv/bin/python -m compileall main.py controllers services models config core utils examples
.venv/bin/python examples/agent_usage.py
```
