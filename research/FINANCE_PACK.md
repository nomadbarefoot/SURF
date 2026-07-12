# SURF Finance Pack — Design Draft

Status: draft (2026-07-07). Consumer: Touchstone (Contrarian Value runbook), which
routes its Indian book to PRISM-SHARD and everything PRISM doesn't hold to SURF.
Contract context: `Touchstone/docs/PRISM_AGENT_SERVER_REQUIREMENTS.md` (routing table).

## Idea

Today the runbook uses SURF as generic web search: query → pages → the agent reads and
extracts. That burns tokens and produces inconsistent ledger stamps. The finance pack
replaces the generic path for a known, small set of recurring data needs with **typed
endpoints that map curated, working websites to structured markdown** — one tool call,
one deterministic markdown block, source + as-of included. The agent stops doing
extraction; SURF does.

Principles:
- **Curated source ladders, not search.** Each endpoint has an ordered list of known-good
  URLs/selectors. Search is the last rung, not the first.
- **Structured markdown out.** Fixed per-endpoint template: a header line with
  `source · as-of · confidence`, then a table or key list. Never raw page text.
- **Fail explicit.** If no rung yields the field, return `MISSING: <field> — <reason>`
  lines; the runbook converts these to ledger flags. No silent absence.
- **Read-only, cache-friendly.** Same-day repeat calls serve cache; macro endpoints
  cache harder (daily), price-ish endpoints lighter.

## Endpoints

### `finance_consensus(symbol, market)`
Analyst price target (mean + range) and EPS estimates.
- IN ladder: Trendlyne → Moneycontrol → search fallback
- US ladder: stockanalysis.com → Yahoo Finance quote page → search fallback
- Fields: PT mean, PT high/low, analyst count, FY EPS estimates, as-of

### `finance_insider(symbol, market)`
Insider/promoter transactions and pledges, trailing 6–12 months.
- IN ladder: NSE corporate disclosures (insider trading + SAST filings) → Trendlyne
- US ladder: openinsider.com → SEC Form 4 index
- Fields: date, party, buy/sell, quantity, value, % of holding

### `finance_corp_actions(symbol, market)`
Buyback authorizations + execution pace, dividends declared, splits, delistings.
- IN ladder: NSE corporate announcements → BSE announcements → Moneycontrol
- Fields: action type, announce date, size/ratio, execution status

### `finance_macro(country)`
The runbook's frozen-ladder vintages, one call per home market.
- 10Y sovereign yield: TradingEconomics
- Sovereign CDS: WorldGovernmentBonds JSON API (`wp-json/cds/v1/main`)
- FX spot: Google Finance USD/INR → Frankfurter API fallback
- FX implied vol: SearXNG snippet search (1M implied vol)
- **Merge mode:** macro walks all rungs and merges fields (unlike single-rung endpoints)

### `finance_erp(home, foreign)`
Equity risk premia + country default spreads.
- Ladder: Damodaran country risk pages (pages, not the xls) → cached last-known with
  `stale` marker (Damodaran updates ~yearly; hard-fail is wrong here)
- Fields: ERP home, ERP foreign/mature, country default spread, vintage

### `finance_snapshot_us(symbol)`
Degraded US-book basics until a native yfinance tool exists in Touchstone:
price, mktcap, % off 52w/ATH, PE, shares outstanding, short interest if shown.
- Ladder: stockanalysis.com → Yahoo Finance
- Explicitly marked `degraded: true` in the header line so ledger rows carry the flag

## Output shape (all endpoints)

```markdown
## finance_consensus · RELIANCE · NSE
source: trendlyne.com · as-of: 2026-07-05 · confidence: high

| field | value |
|---|---|
| PT mean | ₹3,120 |
| PT range | ₹2,650 – ₹3,540 |
| analysts | 34 |
| FY27 EPS est | ₹142.5 |

MISSING: FY28 EPS — not published on any ladder source
```

`confidence`: high (primary rung, fresh) · medium (fallback rung or dated) ·
low (search rung — value present but unverified).

## Implementation notes

- One extractor module per endpoint under `research/` (or wherever search_extract's
  site adapters live) reusing the existing fetch/session/anti-bot machinery — this is
  a mapping layer on top of `browser_fetch`/`search_extract`, not a new engine.
- Selectors per rung live in a single YAML source map (`config/finance_sources.yaml`)
  so a broken site is a config edit, not a code change. Each rung: url template,
  extraction selectors/regex, freshness field.
- Ladder walk: try rung → validate required fields present + as-of parseable → else
  next rung. Record which rung answered (drives `confidence`).
- Expose as MCP tools alongside the existing `search_*` family (`finance_*` prefix).
- Health: extend `browser_health`-style checks with a nightly ladder probe on one
  known symbol per market, so dead selectors surface before a live run hits them.

## Non-goals

No options chains, no order/holdings data, no derived valuation math, no persistence of
fetched values (Touchstone's STATE.md is the record). If an endpoint's ladder dies and
can't be repaired cheaply, the runbook falls back to generic search — degraded, not
blocked.
