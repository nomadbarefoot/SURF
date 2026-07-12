# Finance Pack — Calibration & Test Report (2026-07-07)

Status: **all 6 MCP tools return structured markdown** on canonical test symbols. SearXNG autowake shipped.

## One-click tools (MCP / HTTP)

Each tool is a single call — SURF walks the source ladder, extracts fields, and returns fixed markdown.

| Tool | Test request | Primary rung | Output file |
|------|--------------|--------------|-------------|
| `finance_consensus` | `RELIANCE` / `IN` | Moneycontrol API | [consensus-reliance-in.md](finance-tools/20260707-104851-consensus-reliance-in.md) |
| `finance_consensus` | `AAPL` / `US` | Google Finance | [consensus-aapl-us.md](finance-tools/20260707-104851-consensus-aapl-us.md) |
| `finance_insider` | `RELIANCE` / `IN` | NSE PIT API | [insider-reliance-in.md](finance-tools/20260707-104851-insider-reliance-in.md) |
| `finance_corp_actions` | `RELIANCE` / `IN` | NSE corp actions | [corp_actions-reliance-in.md](finance-tools/20260707-104851-corp_actions-reliance-in.md) |
| `finance_macro` | `IN` | TradingEconomics 10Y | [macro-in.md](finance-tools/20260707-104851-macro-in.md) |
| `finance_erp` | `IN` / `US` | Damodaran ERP table | [erp-in-us.md](finance-tools/20260707-104851-erp-in-us.md) |
| `finance_snapshot_us` | `AAPL` | Google Finance | [snapshot_us-aapl-us.md](finance-tools/20260707-104851-snapshot_us-aapl-us.md) |

Machine-readable run log: [20260707-104851-summary.json](finance-tools/20260707-104851-summary.json)

### Re-run harness

```bash
# SURF must be running (start_surf.py)
.venv/bin/python scripts/run_finance_tool_harness.py
```

Writes timestamped markdown under `research/finance-tools/`.

## Health probes (2026-07-07)

| Endpoint | Result |
|----------|--------|
| `GET /health/live` | alive |
| `GET /health/searxng` | ready (9ms) |
| `GET /health/finance` | **healthy** — all primary rungs HTTP 200 |

Primary rungs hit; `search_fallback` rungs correctly skipped when not needed.

## SearXNG autowake (new)

When SearXNG is down, SURF can start it automatically:

- **Runtime:** `services/searxng_runtime.py`
- **Settings:** `SURF_SEARXNG_AUTOWAKE_ENABLED` (default `true`), container name `searxng`, config `~/searxng/config`, port `8888`
- **Flow:** probe `/healthz` → `docker start searxng` (or `docker run` if missing) → wait → retry
- **Health:** `GET /health/searxng?autowake=true` forces wake
- **Search:** `SearchService.search()` autowakes on `ConnectError` before failing

Verified: `docker stop searxng` → `GET /health/searxng?autowake=true` → container Up, probe OK.

## Calibration changes (prior session + today)

### `config/finance_sources.yaml`

| Endpoint | Change |
|----------|--------|
| consensus IN | Moneycontrol estimate APIs + `moneycontrol_sc_id` + FY27 EPS supplement; Google Finance NSE fallback |
| consensus US | Google Finance + Yahoo analysis regexes |
| insider IN | NSE PIT JSON fields; Moneycontrol broker-research |
| corp_actions IN | NSE/BSE JSON `subject` / `exDate` |
| macro IN | TradingEconomics 10Y yield; RBI reference rate for FX (partial) |
| erp | Damodaran index-based table cell regexes |
| snapshot US | Google Finance primary; Yahoo chart fallback; `% off 52w` computed from 52w high |

### `services/finance_service.py`

- `_resolve_moneycontrol_sc_id()` — NSE ticker → Moneycontrol `scId`
- `moneycontrol_supplements` — concatenate estimate API responses
- `snapshot_us` — post-process 52w high → % below high
- `_reload_sources()` — hot-reload YAML without restart

## Tool outputs (final)

### finance_consensus · RELIANCE · IN

```
source: api.moneycontrol.com · confidence: medium
PT mean ₹1694 | high ₹1910 | low ₹1510 | analysts 31 | FY EPS ₹64
```

### finance_consensus · AAPL · US

```
source: www.google.com · as-of: 2026-05-11 · confidence: medium
PT mean $324.40 | high $400 | low $250 | analysts 30 | FY EPS $8.27
```

### finance_insider · RELIANCE · IN

```
source: www.nseindia.com · as-of: 18-Feb-2026
transactions: Off Market | pledge % MISSING
```

### finance_corp_actions · RELIANCE · IN

```
source: www.nseindia.com · as-of: 05-Jun-2026
Dividend - Rs 6 Per Share
```

### finance_macro · IN (CDS/FX calibrated 2026-07-07)

```
source: tradingeconomics.com · as-of: 2026-07-07 · confidence: high
10Y yield 6.68% | CDS 87.67 bps | USD/INR 94.90 | implied vol 3.5%
```

Output: [macro-in.md](finance-tools/20260707-120815-macro-in.md)

### finance_erp · IN/US

```
source: pages.stern.nyu.edu · as-of: 2026-02-01 · confidence: high
ERP home 7.08% | mature 4.46% | default spread 2.85%
```

### finance_snapshot_us · AAPL (degraded)

```
source: www.google.com · price $312.66 | P/E 37.82 | % off 52w 1.49%
mktcap / shares outstanding MISSING
```

## Known gaps

1. **insider IN** — promoter pledge % not extracted from NSE payload
2. **snapshot US** — mktcap and shares outstanding selectors need Google/Yahoo HTML tune
3. **FX implied vol** — from SearXNG snippets (~3.5%); may be stale vs CCIL (403)

## Next steps

- Tune snapshot US mktcap/shares selectors
- Add US insider / corp_actions harness cases when ladders exist
- Optional: CCIL implied-vol browser rung if 3.5% snippet vol is too stale
