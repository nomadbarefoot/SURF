# SURF Agent Guide

SURF exposes a local HTTP API for browser-backed browsing, observation, extraction, network capture, fetches, and sandboxed downloads.

## Endpoint

Use `SURF_BASE_URL` when present. Otherwise default to:

```text
http://127.0.0.1:17777
```

## Auth

Default local mode is `SURF_AUTH_MODE=loopback`; do not login and do not send a bearer token.

If `SURF_API_TOKEN` is present, send:

```text
Authorization: Bearer $SURF_API_TOKEN
```

`/auth/login` and `/auth/api-key` are disabled compatibility endpoints.

## Workflow

1. `POST /sessions/` with a stable `profile_id`.
2. `POST /browser/network/start` before navigation when XHR/API discovery matters.
3. `POST /browser/navigate` with `wait_until="domcontentloaded"`.
4. `POST /browser/observe`; omit `content_mode` to use the session default.
5. Use `/browser/interact` and `/browser/wait` for page workflows.
6. Use `/fetch/request` with `session_id` when an endpoint needs browser cookies.
7. Use `/browser/download/click` or `/fetch/request save_to_downloads=true` for files.
8. Use `/sessions/monitor` or `/sessions/{session_id}/touch` for long workflows.
9. `DELETE /sessions/{session_id}` when done.

## Payloads

Default silent session:

```json
{
  "config": {
    "profile_id": "agent-default",
    "persist_profile": true,
    "block_mode": "conservative",
    "content_mode": "compact"
  }
}
```

Visible session for protected or interactive sites:

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
  "url": "https://example.com/api/data",
  "backend": "browser",
  "session_id": "sess_xxxxxxxx",
  "timeout": 60000
}
```

Save fetch response:

```json
{
  "method": "GET",
  "url": "https://example.com/report.csv",
  "backend": "browser",
  "session_id": "sess_xxxxxxxx",
  "save_to_downloads": true,
  "download_filename": "report.csv"
}
```

## Constraints

- Only one active persistent session may use a given `profile_id`.
- Operations on a session are serialized; use separate sessions for independent parallel work.
- Silent mode is default. Use `"headed": true` or `"silent": false` when normal visible-browser interaction is needed.
- Leave `user_agent` unset unless the user requests an override.
- Back off on 403, 429, CAPTCHA, login-wall, or challenge warnings.
- Do not automate CAPTCHA solving, credential bypass, access-control bypass, or high-volume crawling.
