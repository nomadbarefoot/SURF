---
name: surf
description: Web search, page extraction, and direct HTTP fetch via the SURF service
---

# surf CLI

```sh
surf search "<query>" [--max-results N]   # find URLs
surf extract <url> [<url> ...]            # readable page content, parallel
surf fetch <url>                          # raw HTTP GET (JSON APIs etc.)
```

Requires `SURF_URL` (host:port); `SURF_API_TOKEN` when auth mode is token.

- Keep `--max-results` at 3–5; it only trims output — the service always
  searches a full candidate pool, semantically gates it, and returns the top N.
- Batch URLs into one `extract` call — they run in parallel.
- Prefer `fetch` over `extract` for structured/JSON endpoints.
