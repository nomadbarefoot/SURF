# SURF

SURF is a local browser substrate for agents and one-off scripts. It runs a FastAPI daemon, launches a headed persistent Chromium profile through Playwright, exposes browser actions over HTTP, captures network responses, and provides a fetch endpoint that can reuse browser-session cookies.

The goal is reliable occasional browsing and scraping, not high-volume crawling or bypass tooling. SURF defaults to permissive local behavior: it warns on likely rate limits, login walls, and challenges, but does not solve CAPTCHAs or escalate around site protections.

## What It Does

- Launches headed Chromium sessions with persistent profile storage.
- Lets agents navigate, observe, click, type, wait, screenshot, and extract content.
- Captures document/XHR/fetch network responses for pages agents visit.
- Runs one-off HTTP fetches with `httpx` or `curl_cffi`.
- Reuses cookies from a browser session for fetches when a site needs browser context.
- Keeps default browser identity stable instead of rotating fingerprints randomly.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Start SURF:

```bash
SURF_HOST=127.0.0.1 SURF_PORT=6670 .venv/bin/uvicorn main:app --host 127.0.0.1 --port 6670
```

OpenAPI docs are available at `http://127.0.0.1:6670/docs` when `SURF_DEBUG=true`.

## Quick Agent Flow

Login:

```bash
curl -s http://127.0.0.1:6670/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"agent","password":"password123"}'
```

Create a headed persistent browser session:

```bash
curl -s http://127.0.0.1:6670/sessions/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"config":{"profile_id":"agent-default","headed":true,"persist_profile":true}}'
```

Navigate:

```bash
curl -s http://127.0.0.1:6670/browser/navigate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SESSION_ID'","url":"https://www.nseindia.com/","wait_until":"domcontentloaded","timeout":90000}'
```

Observe the page:

```bash
curl -s http://127.0.0.1:6670/browser/observe \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SESSION_ID'","max_text_length":4000,"max_items":50}'
```

Fetch with browser cookies:

```bash
curl -s http://127.0.0.1:6670/fetch/request \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"method":"GET","url":"https://www.nseindia.com/api/marketStatus","backend":"curl_cffi","session_id":"'$SESSION_ID'","timeout":60000}'
```

Close the session:

```bash
curl -s -X DELETE http://127.0.0.1:6670/sessions/$SESSION_ID \
  -H "Authorization: Bearer $TOKEN"
```

## Main API Surface

### Sessions

- `POST /sessions/` creates a browser session.
- `GET /sessions/` lists sessions.
- `GET /sessions/{session_id}` returns session state.
- `DELETE /sessions/{session_id}` closes a session.

Important session config keys:

- `profile_id`: stable local browser profile name.
- `headed`: defaults to `true`.
- `persist_profile`: defaults to `true`.
- `stealth_strategy`: `minimal`, `none`, or `legacy`; default is `minimal`.
- `block_resources`: defaults to `[]`.
- `locale`, `timezone_id`, `viewport`, `user_agent`.

### Browser

- `POST /browser/navigate`
- `POST /browser/observe`
- `POST /browser/wait`
- `POST /browser/extract`
- `POST /browser/interact`
- `POST /browser/screenshot`
- `POST /browser/network/start`
- `POST /browser/network/stop`
- `GET /browser/network/events/{session_id}`

`/browser/observe` is the best first call for agents. It returns current URL, title, visible text, links, forms, action candidates, tables, warnings, and optional screenshot path.

### Fetch

- `POST /fetch/request`

Supported backends:

- `auto`: currently uses `httpx`.
- `httpx`: normal HTTP client.
- `curl_cffi`: browser-like TLS/session fetches.
- `cloudscraper`: optional compatibility backend if installed.

Use `session_id` on fetch requests when you want SURF to export cookies from the active browser context.

## Corporate Actions Probe

Example RELIANCE checks that worked during verification:

NSE corporate actions:

```json
{
  "method": "GET",
  "url": "https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol=RELIANCE",
  "backend": "curl_cffi",
  "session_id": "<session_id>",
  "timeout": 60000
}
```

BSE corporate actions:

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

In the live verification run, NSE returned RELIANCE dividend and bonus records, and BSE returned `Table`, `Table1`, and `Table2` corporate-action JSON for scrip code `500325`.

## Python Client Example

See [examples/agent_usage.py](examples/agent_usage.py) for a minimal agent-style client that logs in, creates a profile-backed session, navigates, observes, fetches corporate actions, and closes the session.

## Operational Notes

- Keep request volume low and respect site terms.
- Prefer browser navigation first for protected or JS-heavy sites, then use fetch with browser cookies for specific API endpoints.
- Stop or back off on 403, 429, CAPTCHA, login, or challenge warnings.
- Do not use SURF to bypass access controls or scrape at scale.
- Runtime browser profiles are stored in `data/profiles/` and ignored by Git.

## Verification Commands

```bash
.venv/bin/python -m compileall main.py controllers services models config core utils
```

Optional live check:

```bash
.venv/bin/python examples/agent_usage.py
```
