# SURF Usage

Start:

```bash
.venv/bin/python start_surf.py
```

Agent-friendly start/discovery:

```bash
.venv/bin/python surfctl.py ensure
```

Default base URL:

```text
http://127.0.0.1:17777
```

Default auth is loopback-only and does not require login. If `SURF_AUTH_MODE=token`, send `Authorization: Bearer $SURF_API_TOKEN`.

Create a session:

```bash
curl -s http://127.0.0.1:17777/sessions/ \
  -H 'Content-Type: application/json' \
  -d '{"config":{"profile_id":"agent-default","persist_profile":true,"block_mode":"conservative"}}'
```

Navigate and observe:

```bash
curl -s http://127.0.0.1:17777/browser/navigate \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SESSION_ID'","url":"https://example.com","wait_until":"domcontentloaded"}'

curl -s http://127.0.0.1:17777/browser/observe \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"'$SESSION_ID'","max_text_length":4000,"max_items":50}'
```

Fetch with browser cookies:

```bash
curl -s http://127.0.0.1:17777/fetch/request \
  -H 'Content-Type: application/json' \
  -d '{"method":"GET","url":"https://example.com/api/data","backend":"browser","session_id":"'$SESSION_ID'"}'
```

Close:

```bash
curl -s -X DELETE http://127.0.0.1:17777/sessions/$SESSION_ID
```

Use `README.md` for the canonical API overview and `AGENTS.md` for agent protocol.

Close sessions when work is done. The daemon remains resident, and Playwright/Chromium is released after browser idle.
