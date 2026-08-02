# ADR-001 — Deterministic interaction contract

Status: accepted (all open questions resolved — see R1–R4)
Date: 2026-08-01
Author: CXD `architect` (sol / gpt-5.6-sol, high effort), commissioned and
verified by the orchestrator
Companion: [`agent-browser-gaps.md`](./agent-browser-gaps.md) (G1–G6)

## Decision

Adopt a **hybrid verified handle**: SURF returns a short session/page-scoped
handle backed by a deterministic locator plan plus an element identity
fingerprint, and *also* exposes the resolved locator string.

```
surf:e1:<page_id>:<short_id>
```

Rejected alternatives and why each lost:

- **Opaque snapshot refs** (Playwright MCP's model) — refs are snapshot-scoped,
  so routine DOM churn forces constant re-observation, and the server must
  retain live node state.
- **Bare locator strings** — a DOM change can silently retarget a *different*
  element, which is the worst possible failure: a confidently wrong action.

Governing invariant:

> SURF resolves mechanical uncertainty internally, but **never chooses
> arbitrarily among semantically distinct elements**. It returns candidates
> instead of guessing.

## Registry

Stores strings and fingerprints only — never `ElementHandle` objects, which
would pin DOM nodes.

| Property | Value |
|---|---|
| Limits | 512 records/page, 1000/session, LRU-bounded |
| TTL | 10 min, or remaining session lifetime |
| Eviction | hard navigation, page close, session close/expiry, LRU/TTL |
| Memory | ~1–2 MB per maximally populated session |

Locator resolution order: configured test attribute (`data-testid`/`-test`/`-qa`)
→ unique `id` → associated label or unique `aria-label` → role + accessible name
→ stable tag/name/type → exact visible text → shortest unique structural CSS path
with explicit `nth`. **Every candidate is count-checked within its frame before
issuance.** Mutable or sensitive values are never used in identity.

## Inventory

One flat `elements[]` covering native controls, `contenteditable`, explicit ARIA
roles, `tabindex`-focusable nodes, inline handlers, listener-observed elements,
and `cursor:pointer` as a low-confidence fallback. Traverses every Playwright
frame independently.

Each entry carries: `index`, `handle`, `locator`, `role`, `name`, `tag`,
`input_type`, `text`, `placeholder`, `actions[]`, `state{}`, `value`,
`options{}`, `link{}`, `form{}`, `context{}`, and `discovery`
(`native|aria|focusable|listener|heuristic` — signals semantic quality without
prose interpretation).

Notable resolutions:
- `form{}` associates via the **HTML form owner**, not descendant traversal —
  this is what fixes bare React inputs (G1).
- `value`/`options` close G6; password and file values are omitted with
  `value_redacted: true`.
- `state{}` requires `visible` + `enabled`, with sparse optionals
  (`checked`, `expanded`, `selected`, `required`, …) closing G4/G6.

**Bounding:** default page size **75** (see R1), max 100, ordered frame-then-DOM.
Response
metadata carries `total`, `next_cursor`, `counts_by_role`, `counts_by_action`,
`visible_count`, `hidden_count`. Filters: role, action, visibility,
`name_contains`, `scope_handle`.

**Token cost:** ~60–90 tokens/entry → ~3K–4.5K for a page of 50; ~12K–18K for
all 200 across four pages. Returning all 200 at once is opt-in, never default.

Legacy `links`/`forms`/`actions` are retained during migration as **projections
of `elements`**, not separate queries.

## Outcome contract (`interaction.v1`)

Replaces the single opaque failure string. Fields: `outcome`, `reason`,
`action`, `target{input_kind, handle?, locator?, match_count}`, `timing`,
`recoveries[]`, `element_before`, `element_after`, `effect{}`, `error{}`,
`candidates[]` (≤10).

Expected interaction-domain failures return **this JSON contract**, not HTTP
prose. Auth/authz and malformed transport remain HTTP boundary failures.

Recovery policy: all recovery consumes the caller's original timeout (never
silently extended); Playwright actionability is the first layer; a verified
handle may be re-resolved and redispatched **once**; `force=true` is never
implicit.

Taxonomy — SURF self-resolves then returns: `stale_handle`, `not_found`,
`ambiguous`, `not_visible`, `covered_by`, `disabled`, `detached`, `unstable`,
`option_ambiguous`, `frame_unavailable`, `navigation_interrupted`.
Returns directly: `completed`, `invalid_target`, `action_not_supported`,
`readonly`, `not_editable`, `option_not_found`, `value_not_applied`,
`navigation_blocked`, `timeout`, `page_closed`, `session_unavailable`,
`browser_error`.

The motivating case: `ambiguous` filters by fingerprint and actionability first,
and only surfaces `candidates` + `match_count` if genuinely distinct elements
remain — so the common case never reaches the model at all.

## Staleness

**Invalidates:** registry eviction/TTL, session mismatch, page close, switching
page without addressing the original, hard navigation/reload (new document
nonce), target frame navigation/removal.

**Does *not* invalidate:** hash/History route change within the same document,
scroll, focus, or state changes (`checked`, `expanded`, `value`, `disabled`).

**Before every action:** resolve stored locator in its recorded frame → compare
identity fingerprint → require **exactly one** compatible match before dispatch.

> Safety invariant: SURF returns failure rather than acting on a plausible but
> unverified replacement element.

## Content mode

Add `content_mode=ui`. Article extraction and UI-state observation have
incompatible inclusion rules; the inventory stays orthogonal and paginated in
every mode. `ui` preserves nav/filter labels, button and form labels, counters
and status text; excludes script/style/noscript and
`display:none`/`visibility:hidden`/`hidden`/`aria-hidden`; and never
concatenates across block/control boundaries (fixes the `completeBuy` defect).

**G4 fix:** build compact/reader/data text from the **live rendered tree** using
computed visibility, not a detached clone. Never fall back to `textContent` for
agent-visible presence assertions. Use the same rendered baseline for
`source_text_length`, and clamp/check `reduction_ratio` to `[0,1]`.

`compact` stays the default during migration; a later major version may make
`ui` the `browser_observe` default without touching reader/search defaults.

## Migration

| # | Label | Change |
|---|---|---|
| 1 | additive | Typed `ElementEntry`, `ElementInventory`, `InteractionOutcome`, UI mode models; optional cursor/filter/handle inputs |
| 2 | additive | Generate `elements` + metadata in `browser_observe`; legacy arrays become projections |
| 3 | additive | Bounded handle registry + verified resolver; selector strings still route through `page.locator` |
| 4 | additive | `contract_version=interaction.v1` opt-in; normalize Playwright exceptions **before** the controller discards them |
| 5 | additive | Optional `handle` + `structured_outcomes` on click/type/select/hover |
| 6 | non-breaking fix | Add `ui` mode; correct visibility extraction; regression tests for hidden filtered content, whitespace boundaries, bare React inputs, radios/options, ambiguity, stale-handle rejection |
| 7 | additive deprecation — **complete 2026-08-02** | MCP click/type/select/hover default to `interaction.v1`; `selector_hint` and selector-only targeting are deprecated, with verified handles preferred |
| 8 | **breaking (major), deferred** | Required target union `{handle}\|{locator}\|{selector}`; remove legacy projections after a deprecation window |

Steps 1–7 keep every current tool signature working.

Step 7 changes only MCP defaults. Direct HTTP `/browser/interact` requests keep
their legacy response default unless they opt into `contract_version:
interaction.v1` or `structured_outcomes: true`. MCP and HTTP callers may still
send `selector`; inventory `actions[].selector_hint` and all legacy projections
remain present for compatibility. New callers should observe an element and
send its verified `handle`. Removal is explicitly reserved for deferred step 8.

Raw keyboard input is an adjacent deterministic primitive, not a new
`InteractionAction`: `/browser/press-key` has a bounded timeout and either
focuses one explicit selector/verified handle or preserves the active element.
Console capture has explicit start/read/clear/stop lifecycle and bounded
page-scoped storage. Viewport resize mutates the active page in place and
returns the actual `window.innerWidth`/`window.innerHeight`; neither operation
creates a session or browser context.

## Acceptance criteria

- TodoMVC's bare `new-todo` input, toggles, clear button and filters all appear
  in `elements` with actionable handles.
- httpbin radios expose `value`/`checked`; selects expose bounded `options`.
- Every returned handle is accepted unchanged by click/type/select/hover.
- A DOM reorder can never make a handle act on a fingerprint-mismatched element.
- A legacy selector matching two distinct elements returns `candidates` with no
  extra probe.
- Hidden filtered content is absent from `compact` and `ui` `visible_text`.
- Default inventory for 200 elements stays ~3K–4.5K tokens/page.
- Existing HTTP and MCP selector calls keep working until step 8.
- Outbound-policy and auth/token enforcement unchanged.

## Orchestrator verification

Independently confirmed against the code:

- `controllers/browser_controller.py:170-174` — bare `except Exception` logs the
  real Playwright error, then raises HTTP 500 with the hardcoded literal
  `"Element interaction failed"`. The diagnostic already exists and is discarded.
- `services/browser_service.py:329-338` — `full` uses live
  `document.body.innerText`; all other modes use `document.body.cloneNode(true)`.
  A detached clone has no layout, so `innerText` degenerates to `textContent`
  and hidden subtrees leak. This is a sharper cause than the original G4 note,
  which has been corrected.

CXD's flagged imprecision in G4 was **correct and has been accepted**. It found
no material code-level claim in G1–G3 or G5–G6 contradicted. Claims in the gap
doc about observed character counts and about modern sites rarely carrying ids
come from the workflow runs and are not reproducible by static inspection —
their *causal code claims* are confirmed.

## Resolved by the orchestrator (2026-08-01)

### R1 — Inventory budget: runtime numeric, generous default

**Rejected: task-based auto modes.** They require the agent to classify its own
task *before seeing the page*, with no feedback when it guesses wrong. That
reintroduces an LLM decision point into a project whose purpose is removing
them.

**Decision:** a numeric `limit`, runtime-configurable, with a server-side
default that is deployment-tunable without a code change. `slim` and `verbose`
are **named presets resolving to numbers**, not separate code paths.

Default `limit` is **75** (raising CXD's proposed 50). Pages in this stack run
to ~200 interactive elements; a first call that covers most of the page beats a
guaranteed second round trip. Max stays 100 per explicit request, unbounded only
via cursor paging.

**Budget is the secondary axis.** Scoping by *relevance* beats scoping by
*size*: `scope_handle`, `role`, `action`, `name_contains` are mechanical, need no
pre-guessing, and remove most pressure on the budget knob. Filters are the
primary interface; `limit` is the backstop.

**Truncation must always be visible.** Every response carries `total`,
`next_cursor`, and `counts_by_role`. An agent that is truncated always knows it
was truncated and exactly how to continue. This is what makes a generous default
safe — being slightly wrong costs one extra paged call, never a silently
incomplete answer.

### R2 — Listener instrumentation: enable on all engines

It is an init-script `addEventListener` patch — plain, engine-agnostic JS. No
reason to restrict to Chromium, and gating on cross-browser parity would stall
it for no benefit.

Delegated framework listeners still cannot always be attributed to a leaf
element, so `cursor:pointer`/focusability remains heuristic. The `discovery`
field (`native|aria|focusable|listener|heuristic`) is the mitigation: callers can
see whether an element was found natively or by guesswork and calibrate, without
parsing prose.

### R3 — Raw Playwright selectors: keep permanently

`text=`, `button:has-text(...)` and the rest already pass through and proved
useful in practice. Removing a working capability to enforce purity is a bad
trade.

Documented as an expert escape hatch, kept off the default path, **no removal
scheduled**. Migration step 8's target union keeps `{selector}` as a permanent
member.

### R4 — Redaction: default-on, broader than passwords

SURF pipes values directly into LLM context, which is a real leak surface.

Redact `type=password` and `type=file`, plus any field whose `name`, `id`, or
`autocomplete` matches credential/payment patterns — `cc-number`, `cvc`, `ssn`,
`otp`, `token`, `secret`. Configurable, but **on by default**.

Always emit `value_redacted: true`. Never silently omit the value: an agent that
sees an absent value will conclude the field is empty and try to fill it.
