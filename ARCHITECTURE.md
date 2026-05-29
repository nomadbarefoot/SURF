# SURF Architecture

SURF is a local FastAPI service around Playwright Chromium. It is designed for agent-driven, occasional browsing and scraping workflows.

## Entrypoints

- `start_surf.py`: local startup helper with port checks.
- `surfctl.py`: local agent-friendly supervisor for status, ensure, and stop.
- `main.py`: FastAPI application, middleware, lifespan cleanup, router mounting.

Mounted routers:

- `/auth`: local auth introspection and disabled compatibility endpoints.
- `/sessions`: browser session lifecycle and monitoring.
- `/browser`: navigation, observation, interaction, screenshots, network capture, downloads.
- `/fetch`: one-off HTTP/browser-context fetches.
- `/downloads`: sandboxed file listing/content/deletion.
- `/health`: health, liveness, readiness, and metrics.

## Services

- `SessionService`: lazy Playwright startup, browser context creation, persistent profile leases, per-session operation locks, idle/hard-TTL cleanup, browser-runtime idle teardown, blocker counters.
- `BrowserService`: page navigation, compact observations, interactions, screenshots, network capture, click downloads.
- `FetchService`: `httpx`, browser-context, `curl_cffi`, and optional `cloudscraper` fetches.
- `DownloadService`: sandboxed download persistence under `data/downloads`.
- `AdblockService`: ABP-style filter loading and request-block decisions.

## Runtime Storage

- `data/profiles/`: persistent Chromium profiles.
- `data/downloads/`: sandboxed downloads and index.
- `data/filterlists/`: cached EasyList/EasyPrivacy filters.

These paths are ignored by Git.

## Auth Model

Default `SURF_AUTH_MODE=loopback` allows requests only when SURF is bound to a loopback host. `SURF_AUTH_MODE=token` requires `SURF_API_TOKEN`.

SURF refuses loopback auth on non-loopback hosts. Demo login and runtime API-key creation are disabled.

## Session Model

Sessions are persistent by default and silent by default. A persistent `profile_id` can have only one active session at a time. Operations on a single session are serialized to avoid races on the Playwright page.

Idle cleanup closes inactive sessions after `SURF_IDLE_TIMEOUT_SECONDS`. Hard TTL closes sessions after `SURF_HARD_TTL_SECONDS`. Busy sessions are not reaped until the active operation completes.

The daemon is resident but thin. Health checks and non-browser work do not start Playwright. Browser runtime starts when a browser session is created, then stops after `SURF_BROWSER_IDLE_TIMEOUT_SECONDS` once no sessions are active. Default limits are `SURF_MAX_SESSIONS=3` and `SURF_MAX_HEADED_SESSIONS=1`.

## Blocking And Observation

Request blocking happens through Playwright routing on page traffic. `conservative` mode preserves document/XHR/fetch/websocket/eventsource traffic and same-site scripts/styles. `token_saver` also blocks images.

`/browser/observe` returns compact agent-facing state: visible text, token estimate, links, forms, actions, tables, warnings, cumulative blocker stats, and the most recent navigation blocker delta.

Observe modes:

- `compact`: default noise-pruned view.
- `reader`: article/main-content view.
- `data`: table/text-focused view.
- `full`: raw visible body text.

Browser-context `/fetch/request` reuses cookies but is not part of page adblock metrics.

## Safety Boundary

SURF supports normal browser interaction, stable cookies, headed mode, conservative ad blocking, and browser-like one-off fetches. It does not automate CAPTCHA solving, credential bypass, access-control bypass, or high-volume crawling.
