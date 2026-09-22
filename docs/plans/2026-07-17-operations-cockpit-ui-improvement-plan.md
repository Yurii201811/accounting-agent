# Operations Cockpit UI Improvement Plan

Status: Phases 1–5 implemented and verified
Date: 2026-07-17
Implementation actor: Kimi K3, one bounded task at a time
Orchestrator: Codex, responsible for preflight, task dispatch, verification, and rollback decisions

## 1. Scope and current evidence

This plan targets the current working tree, not only commit `aed4507d`. Existing unrelated edits must be preserved, including the current provider-label changes in `accounting_agent/operations_cockpit.py`.

The cockpit already has a strong foundation:

- semantic header, navigation, main sections, footer, skip link, headings, labelled controls, and a polite live result count;
- Guided and Expert modes, English and Swedish localization, local preferences, a keyboard command dialog, reduced-motion and forced-colors rules;
- 44 px minimum interactive targets, visible focus styles, local-only assets, print handling, and no remote runtime dependency;
- deduplicated risk-first review rows, no queue truncation, safe empty states, and explicit human-decision boundaries;
- tests that protect offline output, synthetic preview isolation, local-path secrecy, zero-required live counters, touch targets, and packaged assets.

The main problems are hierarchy and responsive navigation, not a missing design system:

1. At 390 px, `.section-nav-inner` uses `overflow-x: auto` for as many as eight links. Later sections are clipped, the thin scrollbar is a weak cue, and `_SCRIPT.markCurrentSection()` updates `aria-current` without ensuring the active link is visible.
2. At 1440 × 1000, the large `.header-copy` plus the collapsed settings column consumes a substantial part of the first screen. The user sees positioning copy before the work that requires a decision.
3. `_render_status_grid()` gives equal visual weight to priority work, fixture state, and three zero-required safety counters. The priority count is accurate but does not provide a direct, prominent route into `#review`.
4. The long linear page is appropriate for offline, printable evidence, but its shell should help users move between decision work, close work, and reference material without behaving like a marketing page.
5. UI HTML, roughly 600 lines of CSS, and roughly 240 lines of JavaScript live in one Python module. That is workable for the first UX pass, but extraction should be a separate mechanical checkpoint rather than mixed into visual changes.

Assumptions:

- The primary user is an accountant, controller, auditor, or supervised operator trying to identify the next human decision.
- The current warm-neutral, editorial, high-contrast visual language should remain.
- No new workflow capability, accounting authority, metric, client data, or live integration is required.
- The page remains useful without JavaScript; JavaScript may enhance navigation, filtering, localization, and preferences.

## 2. Approaches considered

| Approach | What changes | Benefits | Trade-offs |
| --- | --- | --- | --- |
| Minimal responsive patch | Reduce hero spacing; add scroll snapping, edge fades, and active-link auto-scroll to the existing horizontal navigation. | Smallest diff and fastest rollback. | Eight links remain awkward on mobile; priority work still competes with status chrome. |
| **Task-first editorial control desk** | Compact the masthead; provide a native section jump control below 60 rem; keep desktop links at larger widths; make priority work the primary Today action; group live counters as a safety heartbeat. | Solves both observed issues while preserving the static architecture, linear document, visual identity, localization, and print semantics. | Moderate HTML/CSS/JS and test changes; requires careful bilingual and keyboard verification. |
| Full application shell | Add a persistent sidebar, two-pane queue/detail view, and route-like panels. | Highest information density for expert operators. | Excessive for a static snapshot; harms print/no-JS behavior, increases state complexity, and risks hiding safety evidence. |

Recommendation: implement the task-first editorial control desk. Its memorable element should be a compact “decision first, safety always visible” hierarchy—not decorative motion or a generic card dashboard.

## 3. Non-negotiable safety and product invariants

Every task must preserve these assertions:

- The cockpit observes and explains; it never approves, posts, pays, sends, files, deletes, or changes settings.
- A non-zero live counter remains a visible danger state and is never reframed as progress.
- Changed bank details, duplicate risk, unknown suppliers, uncertain VAT, and policy conflicts remain review blockers.
- Guided and Expert views change disclosure only, never risk order, safety policy, or underlying data.
- English and Swedish expose the same facts and actions.
- The public preview remains synthetic-only, contains no source artifact links, and has no network, hosted-model, or ERP-write capability.
- No remote font, CDN, framework, analytics, real client data, secret, credential, or absolute workspace path enters generated output.

## 4. Dependency-ordered implementation plan

### Gate K0 — execution readiness

Before Kimi edits anything:

1. Re-run the workspace preflight and record branch, HEAD, dirty fingerprint, and exact pre-existing changes.
2. Confirm the Kimi K3 route can complete a minimal Codex request without `413 Payload Too Large`.
3. Use a trusted/approved data route. This orchestrator must not send private repository contents through an untrusted custom endpoint or bypass Codex credential handling.
4. Assign one phase to one writer. Do not combine phases in a single Kimi turn.

Current state on 2026-07-17: the verified global `kimi-codex` route completed Phases 1–5 through bounded requests. The orchestrator reviewed each mutation against the dirty working tree and retained the original accounting and provider changes.

### Phase 1 — replace clipped mobile navigation

Primary files:

- `accounting_agent/operations_cockpit.py`: `_render_section_nav()`, `_CSS`, `_SCRIPT`
- `tests/test_operations_cockpit.py`

Change:

- Render one shared section definition into two controls:
  - a labelled native `<select id="section-jump">` below `60rem`;
  - the existing semantic link navigation at `60rem` and above.
- Include only sections present in the current document; preserve the existing conditional Start section.
- Localize the label and all options.
- On selection, update `location.hash` and move to the section.
- Extend `markCurrentSection()` to synchronize the select value and desktop `aria-current` state after hash changes and IntersectionObserver updates.
- Remove mobile dependence on horizontal scrolling. Do not build a custom ARIA menu.

Acceptance criteria:

- At 390 and 768 widths, every section is reachable through one visible native control with no horizontal page or navigation overflow.
- At 1024 and 1440 widths, all desktop section links are visible in English and Swedish without clipping.
- The active section stays synchronized after selecting, clicking, scrolling, using Back/Forward, and opening a command-dialog link.
- With JavaScript disabled, desktop anchors remain usable and the mobile select remains a harmless labelled control.

Tests:

- Extend HTML contract tests for the select, localized option data, conditional Start option, desktop link container, and breakpoint rules.
- Browser checks for `document.documentElement.scrollWidth === window.innerWidth` at all four widths.
- Keyboard checks: Tab to the select, choose with arrows, Enter/Space navigation, visible focus, and no focus trap.

Rollback: revert only `_render_section_nav`, its selectors, its synchronization code, and the matching test assertions.

### Phase 2 — compact the masthead and expose work sooner

Primary files:

- `accounting_agent/operations_cockpit.py`: `_render_header()`, `.app-header`, `.nav-edge`, `.header-copy`, `.workspace-preferences`, `.generation-stamp`, responsive rules
- `accounting_agent/static/tokens.css` and root `tokens.css` only if a reusable size/space token is genuinely needed; both copies must stay identical
- `tests/test_operations_cockpit.py`

Change:

- Keep the wordmark, h1, explanatory boundary copy, Find work control, settings, and generation time.
- Reduce desktop hero scale, vertical padding, and grid gap. Do not replace the interface with marketing copy.
- Keep settings collapsed by default and clearly discoverable, but prevent the collapsed right column from defining the header height.
- Preserve the warm paper background, strong editorial typography, rules, and restrained coral accent.
- Avoid new animation; existing micro-interactions and reduced-motion handling are sufficient.

Acceptance criteria:

- At 1440 × 1000, the Review section heading or explicit Review call-to-action is visible in the first viewport.
- At 390 × 844, the priority action is visible in the first viewport without hiding the wordmark, safety boundary, or settings entry point.
- H1 remains unique; body copy stays readable at 200% zoom; the layout does not overlap at 320 CSS px equivalent.
- English and longer Swedish copy do not collide with the command button or settings.

Tests:

- Retain existing minimum-target and token-only CSS assertions.
- Add Browser bounding-box checks for the first priority action at 390 and the Review entry point at 1440.
- Check 200% browser zoom and forced-colors mode manually.

Rollback: restore only the header CSS/markup checkpoint; no data code should change in this phase.

### Phase 3 — make Today decision-first and keep safety visible

Primary files:

- `accounting_agent/operations_cockpit.py`: `_render_status_grid()` and its CSS selectors
- `tests/test_operations_cockpit.py`

Change:

- Split the current equal-weight six-stat strip into:
  1. a primary decision summary containing priority-case count, local-run state, latest evidence, and a localized link to `#review` when work exists;
  2. a compact safety heartbeat containing live ERP, Microsoft 365, and email/payment/filing counters plus their “zero required” text;
  3. secondary synthetic fixture state.
- Derive all values from the existing data object; do not duplicate case rows or invent KPIs.
- When there are zero priority cases, show a truthful no-review-pending state and no fake action urgency.
- Keep the Observe and review only boundary visible, concise, and outside collapsible content.

Acceptance criteria:

- Priority work is the first status content in DOM and visual order.
- The Review link announces its destination and count in both languages.
- All three live counters remain visible without entering Expert mode.
- Status meaning is conveyed by text and structure as well as color.
- Existing non-zero-live-counter behavior still renders danger styling and safety-violation language.

Tests:

- Add fixture cases for priority count greater than zero and equal to zero.
- Assert DOM order, bilingual action text, absence of a review action at zero, and preservation of all live counters.
- Retain the existing non-zero counter regression test and offline-output checks.

Rollback: revert the Today renderer and related selectors; review data collection remains untouched.

### Phase 4 — improve review-row scanability without changing priority logic

Primary files:

- `accounting_agent/operations_cockpit.py`: `_render_review_queues()`, `.review-filters`, `.attention-*`, `.severity`
- `tests/test_operations_cockpit.py`

Change:

- Keep one deduplicated row per case and the existing strictest-stop-condition ordering.
- Add a small localized “Next human decision” label before the guided reason so the action is scannable.
- Maintain the current severity, source, title, reason, evidence state, and Expert technical context.
- Tune row spacing and alignment for dense desktop scanning while keeping a single-column mobile reading order.
- Do not truncate the queue, hide low-priority items by default, or add approval buttons.

Acceptance criteria:

- Each row answers: severity/source, what happened, what a human must decide, and whether evidence exists.
- Filters still update the polite result count and zero-result recovery action.
- At 390 px, rows have no horizontal overflow and all controls retain at least 44 × 44 CSS px targets.
- At 1440 px, rows align consistently without forcing long Swedish reasons into narrow columns.

Tests:

- Assert one “Next human decision” label per generated row in both localization attributes.
- Preserve the no-truncation count and ordering tests.
- Keyboard-test search, priority select, clear filters, Expert details, and evidence links.

Rollback: revert review markup/CSS only; `_prioritized_review_items()` must not change.

### Phase 5 — accessibility, localization, and interaction quality gate

Primary files:

- `accounting_agent/operations_cockpit.py`: `_SCRIPT` and any ARIA/localization attributes changed above
- `tests/test_operations_cockpit.py`
- `docs/operations_cockpit.md`

Checks and fixes:

- Apply WCAG 2.2 AA POUR checks: semantic structure, text alternatives where applicable, contrast, keyboard operation, predictable state, and robust accessible names.
- Verify the page title, `<html lang>`, meta description, navigation label, select label/options, result announcements, table mobile labels, and dates in both locales.
- Verify tab order, skip link, section jump, settings, Guided/Expert radio controls, review filters, `<details>`, command dialog, Escape, arrow navigation, Enter activation, and focus return.
- Use automated checks for detectable issues, but require manual keyboard and macOS VoiceOver passes because automation cannot validate the whole experience.
- Document the new shell/navigation behavior and keep the safety contract unchanged.

Acceptance criteria:

- No critical or serious automated WCAG 2.2 A/AA findings in the synthetic preview.
- Normal text contrast is at least 4.5:1; large text and UI boundaries are at least 3:1.
- Every interactive control has a visible focus indicator and an accessible name in both locales.
- Reduced motion, forced colors, 200% zoom, and print remain usable.
- `python3 -m unittest tests.test_operations_cockpit -v` and `python3 -m unittest` pass.
- A fresh synthetic preview reports zero broken links, zero source artifact links, and unavailable network/hosted-model/ERP-write capabilities.

Rollback: each earlier phase is independently revertible; do not accept accessibility fixes that alter accounting authority or risk priority.

### Optional Phase 6 — extract UI assets after the visual design is accepted

Do not combine this mechanical refactor with Phases 1–5.

Possible files:

- new `accounting_agent/static/cockpit.css`
- new `accounting_agent/static/cockpit.js`
- `accounting_agent/operations_cockpit.py`
- `pyproject.toml` package-data rules
- public-preview copy/allowlist and manifest logic
- `tests/test_operations_cockpit.py`

Goal: move `_CSS` and `_SCRIPT` into packaged local assets with byte-for-byte equivalent behavior. Preserve offline links, clean-install packaging, preview refusal rules, and the exact public-preview capability contract. This phase is accepted only if DOM behavior and all Phase 5 visual checks remain unchanged.

## 5. Verification matrix

Run every row with synthetic data only.

| Width | Navigation | Guided mode | Expert mode | English/Swedish | Required evidence |
| --- | --- | --- | --- | --- | --- |
| 390 × 844 | Native section jump; no horizontal overflow | Priority action and plain-language decision visible | Technical details readable in one column | No clipping or untranslated dynamic labels | Screenshot, accessibility snapshot, keyboard trace |
| 768 × 1024 | Native section jump; touch targets at least 44 px | Today hierarchy and filters usable | Tables/cards reflow without overflow | Long Swedish labels fit | Screenshot and overflow assertion |
| 1024 × 768 | Desktop section links all visible | Review entry point visible early | Dense rows remain readable | Active section synchronized | Screenshot, hash/back-forward test |
| 1440 × 1000 | Desktop section links and command dialog | Review heading or CTA in first viewport | Three-column row alignment stable | No masthead collision | Screenshot and bounding-box assertions |

Also test:

- no JavaScript: readable linear document and working desktop anchors;
- keyboard only: Tab, Shift+Tab, Enter, Space, arrows where documented, Escape, and focus return;
- VoiceOver on macOS: title, landmarks, heading hierarchy, labels, status/result announcements, and dialog boundaries;
- 200% zoom, reduced motion, forced colors, coarse pointer, and print;
- zero items, several mixed-severity items, missing evidence, and a non-zero live counter.

## 6. Orchestration protocol and Kimi task prompts

For every task, prepend: “Read `AGENTS.md`, run the safe workspace preflight, treat the current dirty working tree as source of truth, preserve unrelated edits, use synthetic fixtures only, make no external calls, and stop before commit.”

1. **Responsive navigation prompt**
   “Implement Phase 1 only from `docs/plans/2026-07-17-operations-cockpit-ui-improvement-plan.md`. Replace clipped small-screen section links with a localized native section jump below 60 rem, retain desktop anchors above it, synchronize both with hash and scroll state, update focused tests, and report the exact diff and checks. Do not change header, Today, review rows, or accounting data logic.”

2. **Compact masthead prompt**
   “Implement Phase 2 only. Compact the existing editorial masthead so priority work appears sooner while preserving wordmark, h1, safety copy, settings, command trigger, generation time, tokens, bilingual behavior, touch targets, and reduced-motion support. Add only targeted tests. Do not change status data or navigation behavior.”

3. **Decision-first Today prompt**
   “Implement Phase 3 only. Recompose existing Today data into a primary decision summary, a visible safety heartbeat, and secondary fixture state. Add truthful review/no-review states in English and Swedish. Preserve every live counter and the non-zero danger invariant. Do not alter review prioritization or add executable actions.”

4. **Review scanability prompt**
   “Implement Phase 4 only. Improve review-row scanability and add a bilingual Next human decision label using existing data. Preserve deduplication, strictest-risk ordering, all rows, filters, Expert context, evidence states, and human-only authority. Update focused tests and do not touch `_prioritized_review_items()`.”

5. **Quality-gate prompt**
   “Run Phase 5 as a verification and narrowly scoped remediation pass. Test 390, 768, 1024, and 1440 widths in both modes and locales; keyboard, VoiceOver-oriented semantics, contrast, 200% zoom, reduced motion, forced colors, print, zero/mixed/missing/non-zero-danger fixtures, focused tests, full unittest, public-preview isolation, and broken links. Fix only failures caused by Phases 1–4 and produce an evidence table.”

6. **Optional extraction prompt**
   “Only after explicit approval, implement Optional Phase 6 as a mechanical asset extraction. Do not change DOM, styles, behavior, accounting logic, or safety wording. Update packaging, preview allowlists/manifests, and tests; prove equivalence with the Phase 5 matrix.”

The orchestrator should review and verify each phase before dispatching the next. A failed safety invariant, public-preview isolation check, localization parity check, or accessibility gate stops the sequence and triggers rollback to the last accepted phase.

## 7. Explicit non-goals

- No React, Vue, frontend build pipeline, server-side app, router, database, or API.
- No live Fortnox, Microsoft Graph, email, payment, tax, filing, or model invocation.
- No approval, posting, sending, payment, deletion, or settings controls.
- No real client data, invented metrics, analytics, telemetry, remote font, CDN, or decorative image dependency.
- No changes to accounting rules, review priority, provider capability contracts, execution permits, or evidence hashing.
- No combined UI redesign and asset-extraction mega-diff.

## 8. Implementation record

- Focused cockpit tests: 9 passed; full repository suite: 290 passed.
- Fresh synthetic preview: 22 links checked, zero broken links, zero source
  artifact links, and network, hosted-model, and ERP-write capabilities unavailable.
- Browser checks at 390, 768, 1024, and 1440 CSS px found no horizontal
  overflow, correct mobile/desktop navigation switching, and no interactive
  target below 44 × 44 CSS px in the tested surface.
- English/Swedish localization, review filtering and recovery, Expert
  disclosure, command-dialog arrows/Escape/focus return, reduced motion,
  forced colors, and print presentation were exercised on the synthetic preview.
- The semantic DOM audit found no duplicate IDs, missing form labels, unnamed
