# SURF Agent Guide

SURF gives agents a local Playwright browser through stdio, plus web search and parallel content extraction. Use it for one-off browsing, observation, interaction, network capture, browser-cookie fetches, sandboxed downloads, search-then-extract research, and typed financial data (`finance_*`).

## Interface

Preferred:

```bash
./surfctl.py mcp
```

Fallback for scripts:

```bash
./surfctl.py stdio
```

Do not use the manual HTTP daemon for agent workflows. Do not use localhost curl, TCP/UDS fallback, `ensure`, `status`, or `stop`.

## Workflow

1. `browser_create_session` with a stable `profile_id`.
2. `browser_network_start` before navigation when XHR/API discovery matters.
3. `browser_navigate` with `wait_until="domcontentloaded"`.
4. `browser_observe`; keep the default compact output unless more detail is needed.
5. Use `browser_links` for full DOM link/PDF discovery on disclosure pages.
6. Use `browser_click`, `browser_type`, and `browser_wait` for page workflows.
7. Use `browser_fetch` with `backend="browser"` and `session_id` when an endpoint needs browser cookies.
8. Use `browser_download` for files; pass `output_dir` when downstream tooling must read the artifact directly.
9. `browser_close_session` when done.

### Web research (no session required)

1. `search_query` — SearXNG metasearch; returns ranked URLs with snippets and relevance scores.
2. `search_extract` — parallel full-page extraction from selected URLs. Pass `refine_query` to filter sections by topic. Pass `relevance` from step 1 to prioritize headed retries.

SearXNG must be running (default `http://localhost:8888`). SURF can autostart Docker when configured.

### Finance Pack

For recurring market-data needs, prefer `finance_*` over generic search:

- `finance_consensus`, `finance_insider`, `finance_corp_actions`
- `finance_macro`, `finance_erp`, `finance_snapshot_us`

Each returns structured markdown with source, as-of, and explicit `MISSING` lines for absent fields. See `FINANCE_PACK.md`.

Downloads return `absolute_path`. Existing files in `output_dir` are refused unless `overwrite=true`.

## Defaults

`browser_create_session` defaults to silent/headless browsing:

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

Use `headed=true` only when a protected or interactive site fails in silent/headless mode. Headed sessions default to an off-screen window.

## JSONL Fallback

Keep one `./surfctl.py stdio` process open for the workflow and send one JSON request per line:

```jsonl
{"id":"health","method":"GET","path":"/health/live"}
{"id":"create","method":"POST","path":"/sessions/","data":{"config":{"profile_id":"agent-default","persist_profile":true,"block_mode":"conservative","content_mode":"compact"}}}
{"id":"quit","method":"QUIT"}
```

## Constraints

- Only one active persistent session may use a given `profile_id`.
- Operations on a session are serialized; use separate sessions for independent parallel work.
- Leave `user_agent` unset unless the user requests an override.
- Back off on 403, 429, CAPTCHA, login-wall, or challenge warnings.
- Do not automate CAPTCHA solving, credential bypass, access-control bypass, or high-volume crawling.
