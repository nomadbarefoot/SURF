# SURF as a deterministic browser agent — gap analysis

Status: living document
Last verified: 2026-08-01, `main` @ 4feb2e3 (+ two fixes landed, see "Fixes already applied")

## Goal

SURF should be a *smarter Playwright*: **mechanical work resolved by code, the LLM
consulted only when genuine judgement is required.**

The test for every item below is a single question:

> Does this force the model to think about something a deterministic code path
> could have decided?

Every "yes" is a defect, even when the tool call technically succeeded.

## How these findings were produced

Real workflows, not synthetic probes:

1. Web research via `search_query` (Playwright MCP locator strategy).
2. A full UI test flow on `https://demo.playwright.dev/todomvc` — add two todos,
   toggle one complete, filter to Active, assert the remaining count.
3. A form fill + submit round trip on `https://httpbin.org/forms/post`.
4. Header/fingerprint inspection via `https://httpbin.org/headers`.
5. A UI pass over **artofayan-site**, both the public deploy
   (`https://artofayan.com`) and the local Astro dev server
   (`http://localhost:4322`), including the category-filter interaction,
   a screenshot visual check, and a mobile-viewport (390x844) run.
6. A Cloudflare-protected target (`https://ko-fi.com/artofayan`).

The functional core held up throughout. SPA hash routing, state transitions,
form POST round trips and viewport config all behaved correctly. The problems
are almost entirely in **what SURF reports back**, not in what it does.

---

## Fixes already applied

### F1. `conservative` block mode silently blocked fonts and media — FIXED

`services/adblock_service.py:139` hardcoded `{"media", "font"}` for
`conservative` (the default mode) regardless of the session's
`block_resources: []`. On artofayan.com both webfonts
(`questrial-latin.woff2`, `zeyada-latin.woff2`) were dropped, so every
screenshot rendered fallback typography. Visual regression testing was
silently invalid on a design portfolio.

`conservative` now applies filter lists only. `token_saver` still blocks
`{image, media, font}` for callers who want the bandwidth savings.

Verified: artofayan.com local build now loads with `requests_blocked: 0`, and
the Zeyada script logo renders correctly in the screenshot.

### F2. Local dev servers were unreachable — FIXED

`OutboundPolicy` rejected every private/loopback address, so
`http://localhost:4322` failed with `Outbound target resolves to a non-public
address`. Local UI testing — the primary use case — was impossible.

`SURF_OUTBOUND_ALLOW_PRIVATE_NETWORKS=true` added to `.env`. Reversible; the
guard code is untouched.

**Follow-on hardening (also applied):** enabling this broke six SSRF tests in
`tests/test_outbound_policy.py`, because they asserted "is it blocked?" while
reading the operator's live `.env`. An operator config change silently disarmed
the security suite. Added a `deny_private_networks` fixture in
`tests/conftest.py` and an autouse fixture pinning the guard shut for that
module. The security invariants are now env-independent — strictly stronger
than before. 21/21 pass.

---

### F3. Observation layer implemented — G1, G2, G4, G5 CLOSED

ADR-001 migration steps 1–3 and 6 landed 2026-08-01 (CXD `work`, sol/medium).
New modules `services/element_registry.py` and `services/observation_script.py`;
`elements[]` inventory, verified handles, `content_mode=ui`, live-tree
extraction, legacy projections, runtime-configurable budget.

Independently verified by the orchestrator (not taken from the handoff):

- **G1** — on TodoMVC with two items, the inventory returns 14 entries including
  the bare `.new-todo` input (not inside a `<form>`, previously invisible), both
  per-item toggles, both Delete buttons, both Edit fields, `#toggle-all` and
  Clear completed.
- **G2** — 14 of 14 locators unique, zero empty. Resolution order is respected:
  `#toggle-all` uses the id; ambiguous siblings fall to structural nth
  (`li:nth-of-type(1) > div > input`). Uniqueness holds under ambiguity
  pressure, which was the real test.
- **Handle round trip** — clicking a returned handle unchanged toggled exactly
  one checkbox (checked delta +1) and no other.
- **G4** — `localhost:4322/?filter=studies` now returns only the 5 STUDIES items
  in compact (111 chars, was 2435 with all 55). No hidden-item leakage in any
  mode. `reduction_ratio` within `[0,1]` everywhere; `truncated` accurate.
- **G5** — "2 items left" survives extraction in `ui` mode; the `completeBuy`
  boundary smash is gone.
- Full suite: **214 passed, 3 skipped, 0 failed** (2 known hangers deselected,
  `surf-mkmr`), against a 209 baseline.

Accepted deviation: any frame navigation evicts the whole page registry rather
than only that frame's records. Stricter than specified — fails stale rather
than risking frame-index retargeting. Correct call.

### F4. Interaction layer implemented — G3, G11, G12 CLOSED

ADR-001 migration steps 4–5 landed 2026-08-01 (CXD `work`, sol/medium).
`interaction.v1` structured outcomes behind an explicit opt-in, the full reason
taxonomy with mechanical self-resolution, explicit `handle` targeting on
click/type/select/hover, sparse `state{}`, and top-level `persist_profile`.

Independently verified by the orchestrator:

- **G3 closed.** `.toggle` matching two elements returns `reason: ambiguous`,
  `match_count: 2`, and two candidates carrying usable handles — **in one call**.
  `.definitely-missing-xyz` returns `reason: not_found`, `match_count: 0`. The
  two are now trivially distinguishable; previously byte-identical.
- Candidates disambiguate identically-named elements via `context_text`
  (`"Alpha"` / `"Beta"` on TodoMVC's two "Toggle Todo" checkboxes).
- **Backward compatibility exact.** Without the opt-in, the same failing call
  still returns HTTP 500 with the literal `"Element interaction failed"`.
- **Safety invariant holds for the tested path.** After a hard reload, reusing a
  handle returns `reason: stale_handle`, `stale_cause: registry_unavailable`, and
  does **not** act on a replacement element. **This does not generalize** — see
  R-1 below; live-locator and frame-index retargeting remain possible.
- **Honest outcomes.** A click on TodoMVC's hover-hidden `.destroy` returns
  `not_visible` with a logged `wait_visible` recovery attempt — not a false
  `completed`.
- Effects are reported for the tested case: `element_before.checked: false` →
  `element_after.checked: true`, plus
  `effect.changed_fields.checked {before, after}`, so a caller confirms what
  changed with no follow-up observe. **Not complete in general** — password
  typing mutates the page and then reports `value_not_applied` (R-3).
- **G11** — textbox `state: {visible, enabled}`; checkbox retains `checked`.
- **G12** — two consecutive ephemeral sessions both start with **0** todos
  (previously 2 → 4 → 8 → 10).
- Suite: **223 passed, 3 skipped, 0 failed** (+9 tests, from a 214 baseline).

Accepted deviations: `navigation_interrupted` is not auto-redispatched, because
the first action may already have taken effect and a retry could duplicate a
consequential interaction — correct call. `navigation_blocked` is not
implemented, honestly reported, with the missing signal named.

## Review findings (independent architect review, 2026-08-01)

CXD `architect` (sol/gpt-5.6-sol, high effort), read-only static trace. Verdict:
*"directionally successful, but the implementation does not yet satisfy its
safety invariant or redaction requirement under DOM churn and
credential-patterned inputs."* Orchestrator spot-checked R-2, R-3 and R-7
against the code — all three confirmed.

A first review attempt timed out at 900s producing zero output; scope was too
large (review + three specifications). Re-run narrowed to review only, with
instructions to emit sections in priority order rather than perfect the whole
document. Lesson for future architect dispatches: **one deliverable per run, and
require incremental emission.**

| # | Sev | Issue |
|---|---|---|
| R-1 | **critical** | Verified-handle TOCTOU: fingerprint checked at `browser_service.py:1035-1037`, but dispatch re-resolves through the live locator at `:1067-1095`. DOM churn between the two can retarget the action. Frame identity is a mutable `page.frames` index; no `framedetached` eviction. |
| R-2 | high | Credential redaction inconsistent: `browser_service.py:1162` excludes only password/file, while `observation_script.py:136-147` has the full R4 predicate. A field named `token`/`cvc` leaks its value on interact but not on observe. |
| R-3 | high | Successful password fills report failure: value is omitted at `:1162`, then `:1119-1127` compares `after.value != value`, so `None != "secret"` → `value_not_applied`. Invites credential re-submission. |
| R-4 | high | Handles can be evicted before the response is sent: all elements registered at `:337-350` before pagination at `:353-379`, against a 512/page LRU cap. |
| R-5 | medium | Caller deadline not enforced across recovery/snapshot awaits. |
| R-6 | medium | `scope_handle` silently falls back to whole-document. |
| R-7 | medium | `force` truthiness-coerced: `bool(options.get("force", False))` makes `"false"` → `True`. |
| R-8 | low | Select preflight matches labels; dispatch passes the string as a value. |

**Registry bounds passed audit**: strings only, no DOM nodes, LRU 512/page and
1000/session, session+page verified on access. One caveat — TTL eviction is lazy.

### F5. All review findings fixed — R-1…R-8, G13, `navigation_blocked`, role CLOSED

Fix worker completed all 11 items 2026-08-01 (CXD `work`, sol/medium).
Suite: **235 passed, 3 skipped, 0 failed** (from 223).

Orchestrator-verified independently:

- **R-1 (critical)** — dispatch now resolves to a transient `ElementHandle`
  (`browser_service.py:1097`, `:1120`, `:1139`) and acts on that exact
  fingerprinted node, closing the resolve→dispatch race. `framedetached`
  eviction wired at `session_service.py:452`, closing frame-index shift. New
  `stale_cause: detached_after_verification`.
- **R-2 / R-3** — `password`, `cvc` and `token` inputs all return
  `reason: completed` with `value_redacted: true`, no `value` key, and the
  secret appears **nowhere** in the serialized response. A non-sensitive
  `username` field still returns its value, so the predicate discriminates
  rather than blanket-redacting. The false `value_not_applied` on password
  fills is gone.
- **R-7** — `options: {"force": "false"}` now returns HTTP 422 with a Pydantic
  `bool_type` error instead of silently coercing to `True`.
- **G13** — TodoMVC's hover-hidden `.destroy` now clicks and actually deletes
  (2 → 1 todos) via `recoveries: [hover_then_recheck, scroll_and_recheck]`. A
  genuinely `display:none` element still returns `not_visible` with both
  attempts recorded, so the ladder does not mask real invisibility.
- **`navigation_blocked`** — worker reports main-frame block returns
  `navigation_blocked` with `attempted_url` and `block_reason: outbound_policy`,
  while a blocked subframe during an unrelated click returns `completed`. The
  frame-matching attribution requirement held.
- **Role** — inventory and interaction outcome now both report `checkbox`.

### G14. Unretrieved asyncio future exception in the visibility ladder

Found during F5 verification. A click on a permanently hidden element returns
`not_visible` correctly, but also emits to stderr:

```
Future exception was never retrieved
future: <Future finished exception=Error('Timeout waiting for element to become visible')>
```

A background task's exception is never awaited. Not a functional failure — the
call returns the right answer — but it is unhandled-exception noise that can
mask genuine errors in logs and suggests a task spawned during the
`hover_then_recheck` / `wait_visible` ladder is not cleaned up on the failure
path. Low severity, worth tidying.

## Open gaps, ranked by determinism cost

### G13. Hover-revealed controls cannot be clicked at all

Found while verifying F4. **Pre-existing, not introduced by F4** — both the
legacy path and `interaction.v1` fail identically.

SURF gates every interaction behind an explicit `wait_for(visible)` before
dispatch. Playwright's own `click()` moves the mouse to the target first, which
fires `:hover` and reveals hover-gated affordances. SURF's pre-check runs
*before* that hover, so the element never becomes visible and the call times out:

```
14 × locator resolved to hidden <button class="destroy" aria-label="Delete">
```

This makes a whole class of UI unreachable: hover-revealed delete/edit
affordances, hover-opened menus, toolbars that appear on row hover. TodoMVC's
delete button is the canonical case — it cannot be clicked through SURF by any
route, though plain Playwright clicks it fine.

`interaction.v1` at least makes the failure legible (`not_visible` + a logged
`wait_visible` recovery) instead of an opaque HTTP 500, but the action still
cannot be performed.

**Wanted:** for click/hover, attempt a hover-then-recheck as part of the
`not_visible` self-resolution ladder before declaring failure, or delegate
visibility waiting to Playwright's own actionability rather than pre-gating it.

### G1. There is no interactive-element inventory — **highest leverage**

On TodoMVC, `browser_observe` returned `forms: []` and `actions: []`. The todo
input was invisible to the tool. The flow only proceeded because the model
already knew `.new-todo` from training data. **That is the failure mode in its
purest form: the tool returned success while the intelligence came from the LLM
guessing.**

Cause: `forms[]` walks `document.querySelectorAll('form')` and reads fields as
form *descendants* (`services/browser_service.py:373`). Bare React inputs — the
majority of modern UI — are never enumerated. `actions[]`
(`browser_service.py:387`) only matches
`button, input[type=button], input[type=submit], [role=button], [onclick]`,
so it misses text inputs, checkboxes, radios, selects, contenteditable, and
anything made interactive with a bare listener.

**Wanted:** a flat `elements[]` inventory of everything interactable,
independent of `<form>` ancestry, each with role, accessible name, state, and a
ready-to-use locator. This is the accessibility-snapshot equivalent, and it is
the single biggest step toward "smarter Playwright."

### G2. `selector_hint` is empty in practice

`services/browser_service.py:393`:

```js
selector_hint: el.id ? `#${CSS.escape(el.id)}` : ''
```

No `id` → empty string. Modern React/Tailwind output rarely carries ids, so the
field is almost always blank. Observed on both TodoMVC ("Clear completed"),
httpbin ("Submit order"), and all five artofayan category-filter buttons —
which are *the* interactive feature of that page.

The tool says "a button exists" and provides no way to press it. The model must
invent a selector.

**Wanted:** always emit a guaranteed-unique locator, resolved in priority order:
`data-testid` → `aria-label` → `role` + accessible name → structural nth-child
path. This is SURF's analogue of Playwright MCP's `ref`, and it is currently a
stub.

### G3. Errors are undiagnosable

`browser_click` returns the identical string `"Element interaction failed"` for
every failure. Demonstrated: `.toggle` (2 matches, strict-mode violation) and
`.this-does-not-exist-at-all` (no match) produced byte-identical errors. Later,
`text=PLEIN AIR` failed the same way — and the ambiguity of that message meant
it was impossible to tell whether the selector engine was unsupported or the
match was simply ambiguous. It cost an extra probe to learn that Playwright
selector engines *do* work.

Cause: `controllers/browser_controller.py:170-174` is a bare `except Exception`
that logs the real Playwright message and then raises HTTP 500 with the
hardcoded literal `"Element interaction failed"`. **The diagnostic already
exists** — Playwright's strict-mode violation text names the match count — it is
simply discarded at the controller boundary rather than returned.

Ambiguity in particular is mechanically recoverable: if the response said
`{reason: "ambiguous", match_count: 2}`, a code path could disambiguate with
`nth` and never involve the model. Today the only recovery is guess-and-retry.

**Wanted:** structured failure reasons — `not_found`, `ambiguous` (+
`match_count`), `not_visible`, `covered_by` (+ the covering element),
`disabled`, `timeout`, `detached`.

### G4. `compact` mode reports hidden DOM as visible — **correctness bug**

On artofayan-site, clicking the STUDIES filter correctly navigated to
`?filter=studies` and reduced the real DOM to 5 items.

- `content_mode: "full"` → 299 chars, the 5 STUDIES items. Correct.
- `content_mode: "compact"` (**the default**) → 2435 chars, still listing all
  55 items, i.e. the filtered-out ones.

The tell is `reduction_ratio: -5.1894` — negative, because
`selected_text_length (2435) > source_text_length (301)`.

Mechanism (`services/browser_service.py:329-338`): `content_mode: "full"` returns
`document.body.innerText` on the **live** tree, which respects layout and so
excludes `display:none`. Every other mode operates on
`document.body.cloneNode(true)` — a **detached** clone. A detached node has no
layout, so `innerText` degenerates to `textContent` semantics and hidden
subtrees leak in. The `(root.innerText || root.textContent || '')` fallback at
line 337 compounds it.

So the default mode reports hidden content as present. **Any assertion of the
form "X is hidden after filtering" silently passes when it should fail.** An
agent testing this UI would conclude the filter is broken.

(Original wording said compact "reads textContent". The clone-detachment path
above is the precise cause; corrected after code review.)

### G5. Content modes are tuned for reading articles, not driving UIs

`services/browser_service.py:363` strips
`form, button, input, textarea, select` from readable text. On TodoMVC, compact
emitted `"Mark all as completeBuy groceriesWater flowers"` — dropping
*"2 items left"* and the All/Active/Completed filters, which are precisely the
assertion targets. Note also the lost word boundaries (`completeBuy`), which
corrupts any text matching.

**Wanted:** a `testing` content mode that preserves interactive labels, control
state, and counts, and never concatenates across element boundaries.

### G6. `forms[]` omits values and control state

httpbin's three `size` radios came back as three entries all named `size` with
labels Small/Medium/Large — no `value`, no per-element locator. Selecting
"Medium" required guessing `input[name="size"][value="medium"]`. It happened to
be right; on a real app (`"M"`, `"size-2"`) it would not be.

Missing: `value`, `checked`, `selected`, `disabled`, `required`, `readonly`,
and for `<select>` the option list.

### G7. Missing tools that block whole categories of UI testing

- **Key press** — no tool. Blocks Enter/Tab/Escape/arrow flows.
  Undocumented workaround discovered by accident: a trailing `\n` in
  `browser_type` submits.
- **Console capture** — no tool. JS errors are invisible, so "does this page
  throw?" cannot be answered. Major for UI testing.
- **Viewport resize** — no tool. Viewport is fixed at session creation, so each
  breakpoint needs a *new session* = new browser context = all state
  (auth, cart, scroll) lost. Responsive testing cannot be done in one flow.
- Also absent (tracked in `surf-tdq2`): dialog handling, file upload, multi-tab,
  history back, drag/drop.

### G8. `extract_structured` does not structure

`content_type: "general"` returned `extracted_elements: {}` and raw text —
the same content `observe` already provides. `content_quality_score: 0.4` is an
unexplained magic number with no documented scale.

### G9. Diagnostics mislabel DNS failure as policy denial

`static.cloudflareinsights.com` was reported blocked with
`reason: "outbound_policy"`. It is not policy-blocked — `dig` returns no answer
(DNS-filtered upstream), so `_resolve` raises and the route handler attributes
it to policy. "Your egress policy forbade this" and "this name did not resolve"
are different operational problems and must not share a label.

Same root cause as item (5) noted in blackboard task `surf-lw6e`. Resolved as
benign, but the label is still wrong.

### G10. Cloudflare: SURF self-identifies as headless

Tracked in full detail in blackboard task `surf-lw6e`. Summary:

`utils/stealth.py:158` `setup_stealth_mode` only calls
`page.add_init_script(bundle)`. It patches JS-visible `navigator` properties but
never sets the **context-level** `user_agent`, which is fixed at context
creation and is what goes on the wire. Confirmed against httpbin.org/headers
with `stealth: true, stealth_strategy: "aggressive"`:

```
User-Agent: ...HeadlessChrome/148.0.7778.96 Safari/537.36
Sec-Ch-Ua:  "Chromium";v="148", "HeadlessChrome";v="148", ...
```

Setting `config.user_agent` fixes the UA header but **`Sec-Ch-Ua` still reports
HeadlessChrome** — UA and client hints then disagree, which reads as active
spoofing and is a worse signal than plain headless.

Consequence on ko-fi.com: the Turnstile pipeline fully executes
(`challenge-platform/orchestrate`, `turnstile/v0/api.js`, `/fo/` POST beacons
all return 200) but no `cf_clearance` cookie is ever issued, so the document
stays HTTP 403 "Just a moment...". Egress also exits a datacenter/VPN IP
(`146.70.142.138`), a second risk signal.

Additionally, the 403 interstitial is returned as `success: true` with a
generic warning string. Callers should get an explicit `challenge_state` field
to branch on, rather than an LLM reading "Just a moment..." out of HTML.

---

### G11. `state{}` is not sparse for irrelevant keys

Found during verification of F3. Text inputs come back with
`state: {visible, enabled, checked: false}` — `checked` is meaningless on a
textbox. The ADR specifies `visible`/`enabled` as required and the rest as
**sparse optional**, emitted only when meaningful.

Cost is twofold: wasted tokens on every text input across a large inventory, and
a mildly misleading signal (a reader could infer the control is checkable).
Emit `checked` only for genuinely checkable roles.

### G12. Profile isolation does not reset storage state — UI runs are not hermetic

Found during verification of F3. Repeated runs against TodoMVC accumulated todos
across sessions (2 → 4 → 8 → 10) despite each run passing a **distinct**
`profile_id`. `persist_profile` defaults to `true` and is not accepted as a
top-level field on session create, so there is no obvious way to ask for a
throwaway context.

For UI testing this is a correctness hazard: consecutive runs of the same test
observe different starting state, so assertions on absolute counts silently
drift. Any test asserting "2 items left" passes once and then fails forever.

Wanted: an explicit ephemeral/incognito session option that guarantees a clean
storage partition, and/or honouring `persist_profile: false` at create time.
Pre-existing, not introduced by F3.

## Smaller issues

- **`truncated: true` is always true**, even at 1.4% reduction with nothing
  meaningful removed. The flag carries no information.
- **Metrics can be internally inconsistent** — `selected_text_length` exceeding
  `source_text_length` (see G4) yields a negative `reduction_ratio`. Worth an
  invariant check; it is a useful bug detector.
- **Concurrency trap**: `max_sessions: 3`, but the default `agent-default`
  persistent profile serializes sessions —
  `Persistent profile 'agent-default' is already active`. Parallel sessions need
  an explicit distinct `profile_id`. Not documented.
- **`stealth_strategy: "full"`** is a natural guess and invalid; accepted values
  are `none|minimal|balanced|aggressive|legacy`.
- **Playwright selector engines work but are undocumented.** `text=`,
  `button:has-text(...)` all function; the tool schema just says "selector"
  (type string). This is a significant capability nobody would discover.

## What is already good — do not regress

- `blocked_samples` naming exact blocked URLs with reason and filter. Excellent
  diagnostics; it is how F1 was found.
- `blocker_delta` per-call accounting.
- `transition` with `readiness_reason` and `route_changed` — real SPA awareness.
- `browser_links`: index, text, href, resolved absolute url, visibility. The one
  inventory that is properly designed. **Use it as the model for G1.**
- `forms[]` label association (via `field.labels[0]`) is genuinely good where it
  applies — the problem is coverage (G1), not quality.
- JSON responses auto-surfaced as `document_body` with a nudge toward document
  extraction.
- Screenshot artifact indirection (id + `content_url`, no base64 in the
  response) keeps token cost near zero.
- Exa-backed `search_query` snippets are rich enough that extraction was often
  unnecessary.

## Suggested sequencing

1. **G1 + G2 together** — the element inventory and its locator. They are one
   feature and together remove most LLM guesswork.
2. **G3** — structured error reasons. Cheap, and converts retry loops into code
   branches.
3. **G4** — the hidden-content bug. Correctness, not ergonomics.
4. **G7** — console capture and key press. Each unblocks a whole test category.
5. **G5/G6/G8** — reporting fidelity.
6. **G10** — Cloudflare/fingerprint alignment, tracked separately in `surf-lw6e`.
