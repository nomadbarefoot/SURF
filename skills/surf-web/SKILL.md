---
name: surf-web
description: Retrieve public web information with search, readable extraction, bounded GET requests, and YouTube transcripts. Use for research, source discovery, page reading, direct public API GETs, or video captions when rendered-browser interaction is unnecessary.
---

# SURF Web

Use the smallest retrieval operation that answers the request.

- Use `web_search` to discover sources.
- Use `web_extract` to read one or more known pages.
- Use `web_fetch` for a bounded public GET; it cannot send custom headers, bodies, or non-GET methods.
- Use `youtube_transcript` for timestamped captions.

Prefer primary sources and return source URLs with synthesized findings. If content requires JavaScript rendering, login state, downloads, or page inspection, switch to `surf-browse`. If the task requires clicking, typing, selecting, keyboard input, or viewport testing, switch to `surf-ui`.
