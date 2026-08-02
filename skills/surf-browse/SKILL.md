---
name: surf-browse
description: Inspect rendered web pages with read-oriented browser sessions, snapshots, extraction, screenshots, downloads, and network capture. Use when public retrieval is insufficient but the task does not require form entry or UI mutation.
---

# SURF Browse

Create a session, navigate, inspect, then close the session unless the caller needs it retained.

1. Use `browser_browse` for a one-shot rendered read.
2. For multi-step inspection, use `browser_create_session`, `browser_navigate`, and `browser_snapshot`.
3. Use `browser_links`, `browser_extract_data`, screenshots, console capture, or network capture only when they add evidence.
4. Use `browser_wait_for` after navigation when page readiness is uncertain.
5. Close sessions with `browser_close_session`.

Do not attempt clicks, typing, selection, key presses, hover, or viewport changes in this profile. Switch to `surf-ui` for those actions. Prefer `surf-web` when static retrieval is sufficient.
