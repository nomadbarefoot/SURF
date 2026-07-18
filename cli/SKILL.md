---
name: surf
description: Web search, page extraction, and direct HTTP fetch via the SURF service
---

# surf CLI

From a checkout, use `./surf` (or `.venv/bin/python cli/surf_cli.py`). Set
`SURF_URL` to the HTTP service address.

```sh
surf search "<query>" [--max-results N]   # find URLs
surf extract <url> [<url> ...]            # readable page content, parallel
surf fetch <url>                          # raw HTTP GET (JSON APIs etc.)
surf preflight                             # service/dependency probes
```

Requires `SURF_URL` (host:port); `SURF_API_TOKEN` when auth mode is token.

All commands accept `--timeout SECONDS`; `search`, `extract`, and `fetch` also
accept `--json` for machine-readable output. `extract` exits non-zero when any
requested URL fails, including partial batches.

- Keep `--max-results` at 3–5; it only trims output — the service always
  searches a full candidate pool, semantically gates it, and returns the top N.
- Batch URLs into one `extract` call — they run in parallel.
- Prefer `fetch` over `extract` for structured/JSON endpoints.
