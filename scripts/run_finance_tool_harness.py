#!/usr/bin/env python3
"""One-click finance tool harness — mirrors MCP finance_* tools via HTTP.

Runs each tool once, saves the markdown output to research/finance-tools/.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "research" / "finance-tools"

TOOLS = [
    ("finance_consensus", "POST", "/finance/consensus", {"symbol": "RELIANCE", "market": "IN"}),
    ("finance_consensus", "POST", "/finance/consensus", {"symbol": "AAPL", "market": "US"}),
    ("finance_insider", "POST", "/finance/insider", {"symbol": "RELIANCE", "market": "IN"}),
    ("finance_corp_actions", "POST", "/finance/corp_actions", {"symbol": "RELIANCE", "market": "IN"}),
    ("finance_macro", "POST", "/finance/macro", {"country": "IN"}),
    ("finance_erp", "POST", "/finance/erp", {"home": "IN", "foreign": "US"}),
    ("finance_snapshot_us", "POST", "/finance/snapshot_us", {"symbol": "AAPL", "market": "US"}),
]


def _slug(name: str, body: dict) -> str:
    sym = body.get("symbol") or body.get("country") or body.get("home", "x")
    mkt = body.get("market") or body.get("foreign", "")
    parts = [name.replace("finance_", ""), str(sym).lower()]
    if mkt:
        parts.append(str(mkt).lower())
    return "-".join(parts)


async def run_tool(
    client: httpx.AsyncClient,
    name: str,
    method: str,
    path: str,
    body: dict,
    bust_cache: bool,
) -> dict:
    headers = {}
    if bust_cache:
        headers["Cache-Control"] = "no-cache"
    resp = await client.request(method, path, json=body, headers=headers)
    resp.raise_for_status()
    return resp.json()


def _write_markdown(slug: str, name: str, body: dict, result: dict, ts: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{ts}-{slug}.md"
    md = result.get("markdown", "")
    meta = {
        "tool": name,
        "request": body,
        "success": result.get("success"),
        "cached": result.get("cached"),
    }
    content = (
        f"# {name}\n\n"
        f"**Run:** {ts} UTC\n\n"
        f"**Request:** `{json.dumps(body)}`\n\n"
        f"**Meta:** `{json.dumps(meta)}`\n\n"
        f"---\n\n"
        f"{md}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("SURF_BASE_URL", "http://127.0.0.1:17777"))
    parser.add_argument("--bust-cache", action="store_true", help="Send no-cache (server may ignore)")
    parser.add_argument("--probe-health", action="store_true", default=True)
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    summary: list[dict] = []

    async with httpx.AsyncClient(base_url=args.base_url, timeout=180.0) as client:
        if args.probe_health:
            for ep in ("/health/live", "/health/searxng", "/health/finance"):
                try:
                    r = await client.get(ep, timeout=120.0 if ep.endswith("finance") else 30.0)
                    summary.append({"probe": ep, "status": r.status_code, "body": r.json()})
                except Exception as exc:
                    summary.append({"probe": ep, "error": str(exc)})

        for name, method, path, body in TOOLS:
            slug = _slug(name, body)
            entry = {"tool": name, "slug": slug, "request": body}
            try:
                result = await run_tool(client, name, method, path, body, args.bust_cache)
                out = _write_markdown(slug, name, body, result, ts)
                entry["success"] = result.get("success")
                entry["cached"] = result.get("cached")
                entry["output_file"] = str(out.relative_to(ROOT))
                entry["markdown_preview"] = (result.get("markdown") or "")[:400]
            except Exception as exc:
                entry["success"] = False
                entry["error"] = str(exc)
            summary.append(entry)

    summary_path = OUT_DIR / f"{ts}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"summary_file": str(summary_path.relative_to(ROOT)), "tools": len(TOOLS)}, indent=2))
    for e in summary:
        if e.get("output_file"):
            print(f"  OK  {e['tool']} -> {e['output_file']}")
        elif e.get("probe"):
            print(f"  PROBE {e['probe']} -> {e.get('status', e.get('error'))}")
        else:
            print(f"  FAIL {e.get('tool')} -> {e.get('error')}")
    return 0 if all(e.get("success") is not False for e in summary if e.get("tool")) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
