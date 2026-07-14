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

SURF MCP tools fall into three families: `browser_*`, `search_*`, and `finance_*`.

### Browser

1. `browser_create_session`
2. `browser_network_start` when XHR/API discovery matters.
3. `browser_navigate`
4. `browser_observe`
5. `browser_fetch` with `backend="browser"` and `session_id` when cookies matter.
6. `browser_download` for files; pass `output_dir` when another tool needs to read the file directly.
7. `browser_close_session`

### Web search and extraction

No browser session needed — SURF manages ephemeral sessions internally.

1. `search_query` with your research question.
2. `search_extract` on the best URLs; pass `refine_query` to trim irrelevant sections.

### Finance Pack

Use `finance_consensus`, `finance_insider`, `finance_corp_actions`, `finance_macro`, `finance_erp`, or `finance_snapshot_us` for structured market data instead of manual search-and-read workflows.

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

Search-then-extract over JSONL (no session required):

```jsonl
{"id":"search","method":"POST","path":"/search/query","data":{"query":"India IPO pipeline 2026","max_results":5}}
{"id":"extract","method":"POST","path":"/search/extract","data":{"urls":["https://example.com/ipo-list"],"refine_query":"India IPO 2026","content_mode":"reader"}}
{"id":"quit","method":"QUIT"}
```

Finance Pack example:

```jsonl
{"id":"consensus","method":"POST","path":"/finance/consensus","data":{"symbol":"RELIANCE","market":"IN"}}
{"id":"macro","method":"POST","path":"/finance/macro","data":{"country":"IN"}}
```

Use `README.md` for the canonical API overview and `ARCHITECTURE.md` for system structure and data flows.

Close sessions when work is done. SURF stdio exits when the MCP/JSONL process closes, and Playwright/Chromium is released after browser idle.
