# SURF Agent Guide

SURF exposes a local HTTP API for browser-backed browsing, observation, extraction, network capture, and fetches.

## Default Endpoint

Use:

```text
http://127.0.0.1:6670
```

unless the user provides another `SURF_BASE_URL`.

## Recommended Agent Workflow

1. `POST /auth/login` with any local demo credentials that satisfy validation.
2. `POST /sessions/` with a stable `profile_id`.
3. `POST /browser/navigate` with `wait_until="domcontentloaded"`.
4. `POST /browser/observe` to get title, visible text, links, forms, buttons, tables, and warnings.
5. Use `/browser/interact` and `/browser/wait` for page workflows.
6. Use `/browser/network/start` before navigation when API/XHR discovery matters.
7. Use `/fetch/request` with `session_id` when an endpoint needs browser cookies.
8. `DELETE /sessions/{session_id}` when done.

## Safety Defaults

- Keep request volume low.
- Do not automate CAPTCHA solving.
- Back off on 403, 429, login walls, or challenge warnings.
- Prefer browser-backed sessions for protected or JS-heavy sites.
- Prefer direct fetch only after the browser has established cookies/session context.

## Useful Payloads

Create session:

```json
{
  "config": {
    "profile_id": "agent-default",
    "headed": true,
    "persist_profile": true,
    "stealth_strategy": "minimal"
  }
}
```

Observe:

```json
{
  "session_id": "sess_xxxxxxxx",
  "max_text_length": 4000,
  "max_items": 50
}
```

Fetch with browser cookies:

```json
{
  "method": "GET",
  "url": "https://www.nseindia.com/api/marketStatus",
  "backend": "curl_cffi",
  "session_id": "sess_xxxxxxxx",
  "timeout": 60000
}
```
