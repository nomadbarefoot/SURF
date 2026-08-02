# SURF Usage

Keyless web MCP bridge:

```bash
.venv/bin/python surfctl.py mcp
```

Specialist stdio bridges use `--profile browse`, `--profile ui`, or
`--profile finance` and require the matching `SURF_*_KEY`. Remote MCP is
available at `/mcp/web`, `/mcp/browse`, `/mcp/ui`, and `/mcp/finance`.

Script JSONL bridge:

```bash
.venv/bin/python surfctl.py stdio
# Browser requests require the browse profile and key:
SURF_BROWSE_KEY=… .venv/bin/python surfctl.py stdio --profile browse
```

Manual HTTP development server:

```bash
.venv/bin/python start_surf.py
```

HTTP CLI:

```bash
./surf preflight
./surf search "Python official documentation" --max-results 3
./surf extract https://docs.python.org/3/
./surf fetch https://example.com
./surf transcript https://www.youtube.com/watch?v=VIDEO_ID
```

Use `--json` for raw response output and `--timeout SECONDS` for longer-lived
requests. `extract` returns a non-zero exit status if any URL in the batch
fails.

Public web retrieval is keyless on loopback. Browser, UI, finance, and operations routes accept only their dedicated bearer keys; unset specialist keys disable those profiles.

## Agent Flow

SURF MCP tools are split across `web` (4), `browse` (16), `ui` (22), and `finance` (6) profiles. No client receives the combined 32-tool inventory.

### Browser

1. `browser_create_session`
2. `browser_network_start` when XHR/API discovery matters.
3. `browser_navigate`
4. `browser_snapshot`
5. `web_fetch` for a bounded public GET.
6. `browser_download` for files; pass `output_dir` when another tool needs to read the file directly.
7. `browser_close_session`

### Web search and extraction

No browser session needed — SURF manages ephemeral sessions internally.

1. `web_search` with your research question.
2. `web_extract` on the best URLs; pass `refine_query` to trim irrelevant sections.

Provider 429s can be transient and may recover through search fallback. Extraction uses a browser path and can fail on a page that `web_fetch` can still retrieve as bounded raw content, so handle their errors independently.

### YouTube transcript

Call `youtube_transcript` with one public YouTube video URL. It returns bounded,
timestamped text and saves the full Markdown transcript in SURF downloads.
Optional ordered `languages` choose a preferred caption language;
`allow_auto_captions=false` requires a manual track. Audio transcription,
translation, playlists, and summarization are not part of this version.

### Finance Pack

Use `finance_analyst_consensus`, `finance_insider_transactions`, `finance_corporate_actions`, `finance_macro`, `finance_equity_risk_premium`, or `finance_us_snapshot` for structured market data instead of manual search-and-read workflows.

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
{"id":"transcript","method":"POST","path":"/youtube/transcript","data":{"url":"https://www.youtube.com/watch?v=VIDEO_ID","languages":["en"]}}
{"id":"quit","method":"QUIT"}
```

Finance Pack example:

```jsonl
{"id":"consensus","method":"POST","path":"/finance/consensus","data":{"symbol":"RELIANCE","market":"IN"}}
{"id":"macro","method":"POST","path":"/finance/macro","data":{"country":"IN"}}
```

Use `README.md` for the canonical API overview and `ARCHITECTURE.md` for system structure and data flows.

Close sessions when work is done. SURF stdio exits when the MCP/JSONL process closes, and Playwright/Chromium is released after browser idle.
