---
name: surf
description: Use local SURF HTTP API for browser-backed browsing, observation, network capture, fetches, and sandboxed downloads.
---

# SURF

Use this skill when an agent needs a local browser substrate for one-off browsing, scraping, page interaction, browser-cookie fetches, or downloads.

## Endpoint

Use `SURF_BASE_URL` when set. Otherwise silently use:

```text
http://127.0.0.1:17777
```

If the endpoint is not reachable and `surfctl.py` or `surfctl` is available, run:

```bash
./surfctl.py ensure
```

Use the returned `base_url`. Do not ask the user to start SURF manually unless the helper is unavailable or fails.

## Auth

SURF normally runs in loopback mode and does not require login.

If `SURF_API_TOKEN` is set, include:

```text
Authorization: Bearer $SURF_API_TOKEN
```

Do not call `/auth/login`; it is disabled.

## Workflow

1. Check `GET /health/live`; if unavailable, run `surfctl ensure` if present.
2. Create a session with `POST /sessions/`.
3. Start `POST /browser/network/start` before navigation if API/XHR discovery matters.
4. Navigate with `POST /browser/navigate`, usually `wait_until="domcontentloaded"`.
5. Observe with `POST /browser/observe`; use the default `compact` mode unless the task needs `reader`, `data`, or `full`.
6. Interact with `/browser/interact` and synchronize with `/browser/wait`.
7. Fetch API endpoints with `/fetch/request`; use `backend="browser"` plus `session_id` when cookies matter.
8. Save files with `/browser/download/click` or `/fetch/request` plus `save_to_downloads=true`.
9. Close sessions with `DELETE /sessions/{session_id}`. Do not stop the daemon after normal work.

## Session Payloads

Default background browsing:

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

Visible browser for protected or interactive workflows:

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

## Safety

- Keep volume low and respect site terms.
- Use headed mode when a site expects normal visible-browser interaction.
- Leave `user_agent` unset unless explicitly requested.
- Back off on 403, 429, CAPTCHA, login-wall, or challenge warnings.
- Do not automate CAPTCHA solving, credential bypass, access-control bypass, or high-volume crawling.

## Notes

- One active persistent session can use a `profile_id` at a time.
- Default limits are 3 browser sessions and 1 headed session.
- Operations on one session are serialized. Use separate sessions for independent parallel work.
- Browser-context fetches reuse cookies but are not page adblock events.
- SURF keeps the API daemon resident and tears down Playwright/Chromium after browser idle.
