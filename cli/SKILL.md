---
name: surf
description: Web search, page extraction, and direct HTTP fetch via the SURF service
---

# surf CLI

Use `surf` to search the web, extract page content, and fetch URLs from within
agent sandboxes. The CLI talks to a running SURF HTTP service over localhost.

## When to use which subcommand

| Subcommand | Use when |
|------------|----------|
| `search`   | You need to find relevant URLs for a topic |
| `extract`  | You have URLs and need their readable content |
| `fetch`    | You need a raw HTTP response from a specific URL |

Typical pipeline: `search` to find URLs → `extract` to read them.
Use `fetch` for direct API calls, JSON endpoints, or when extract is overkill.

## Command syntax

```sh
# Web search — returns numbered results with title, URL, snippet
surf search "<query>" [--max-results N]

# Extract readable content from one or more pages (parallel)
surf extract <url> [<url> ...]

# Raw HTTP GET of a single URL
surf fetch <url>
```

## Configuration (env vars)

```sh
export SURF_URL=localhost:17777        # required — host:port of the SURF service
export SURF_API_TOKEN=<token>          # required when SURF_AUTH_MODE=token
```

## Output format

- **search**: numbered list — `N. Title`, `   URL`, `   snippet`, blank line between results
- **extract**: per-URL sections — `=== <url> ===` header then page text
- **fetch**: raw response body (text or JSON)

Errors go to stderr; non-zero exit on failure.

## Guidance

- Keep `--max-results` small (3–5) to reduce token load; SURF already ranks by relevance.
- Pass multiple URLs to `extract` in one call — they run in parallel.
- If `search` returns `success: false`, it still prints the top results; review them.
- `extract` uses SURF's reader mode by default — clean article text, low noise.
- For structured data (JSON APIs), prefer `fetch` over `extract`.
- 30-second timeout per request; long pages may be truncated at `max_text_length`.
