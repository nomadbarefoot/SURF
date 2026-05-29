# SURF Usage

Agent MCP bridge:

```bash
.venv/bin/python surfctl.py mcp
```

Script JSONL bridge:

```bash
.venv/bin/python surfctl.py stdio
```

Manual HTTP development server:

```bash
.venv/bin/python start_surf.py
```

Default auth is loopback-only for the manual HTTP server and does not require login. If `SURF_AUTH_MODE=token`, send `Authorization: Bearer $SURF_API_TOKEN`.

## Agent Flow

Use MCP tools:

1. `browser_create_session`
2. `browser_network_start` when XHR/API discovery matters.
3. `browser_navigate`
4. `browser_observe`
5. `browser_fetch` with `backend="browser"` and `session_id` when cookies matter.
6. `browser_download` for files.
7. `browser_close_session`

Default session:

```json
{
  "profile_id": "agent-default",
  "persist_profile": true,
  "headed": false,
  "background_headed": true,
  "block_mode": "conservative",
  "content_mode": "compact"
}
```

Set `headed=true` only when a protected or interactive site fails in silent/headless mode. Headed sessions default to an off-screen window.

## JSONL Example

Keep one process open for the full workflow:

```jsonl
{"id":"health","method":"GET","path":"/health/live"}
{"id":"create","method":"POST","path":"/sessions/","data":{"config":{"profile_id":"agent-default","persist_profile":true,"block_mode":"conservative","content_mode":"compact"}}}
{"id":"nav","method":"POST","path":"/browser/navigate","data":{"session_id":"sess_xxxxxxxx","url":"https://example.com","wait_until":"domcontentloaded"}}
{"id":"observe","method":"POST","path":"/browser/observe","data":{"session_id":"sess_xxxxxxxx","max_text_length":4000,"max_items":50}}
{"id":"close","method":"DELETE","path":"/sessions/sess_xxxxxxxx"}
{"id":"quit","method":"QUIT"}
```

Use `README.md` for the canonical API overview and `AGENTS.md` for agent protocol.

Close sessions when work is done. SURF stdio exits when the MCP/JSONL process closes, and Playwright/Chromium is released after browser idle.
