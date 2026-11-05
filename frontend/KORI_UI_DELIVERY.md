# Kori UI delivery — 5 November 2026

Owner: **Michael Kori (UI)**. Implemented by Snyder's parallel UI agents from `dev` at `1f87522` in
`ui/kori-one-hour`, with separate canvas, missions and evidence-panel worktrees and independent cross-review.
The [master plan](../docs/MASTER_PLAN.md#5-kori-frontend) remains the source of priorities and engineering gates.
This packet changes UI, browser checks and documentation; no physical coefficients, API schemas, dependencies or
reference assets change. Seed-data and synthetic/limited labels remain.

## Delivered

| Item | Behavior and evidence |
| --- | --- |
| U9 / R2 | Ship pointer movement changes both `ship_x_ft` and nonnegative `standoff_ft`, for either side-to, without adding yaw. Fitting drag creates or reconnects lines; invalid drops and Escape preserve the arrangement. Numeric placement and keyboard endpoint selectors remain. Tests retain line numbers, types, parts, explicit paid-out lengths and installation fields. Old margins clear during edits; late responses cannot restore them. |
| U9 / R3 UI | Catalog coverage separates hull/environmental inputs, raw fitting records and usable bitts on the selected side. Missing bitts/loading block planning and editing. Changing class/berth clears previous lines, analysis and agent plan/review/sheet. Deferred-response tests cover overlapping class/scenario/berth choices, manual edits and older recommendations. This does not qualify additional classes. |
| U10 / R6 UI | Existing sustained working limits, corresponding gusts, application advisories, governing element and search outcome are visible. Missing values remain unavailable; zero is retained when actually reported. Ultimate breaking gust is explicitly unavailable. Scenario MBS samples are not rupture predictions; missing line-MBS samples do not become zero risk. |
| U11 / R7 UI | Sequence review state, failed/unevaluated intermediate states, issues, limitations, timing assumptions, tug dependencies and citations are shown. Partial restraint stays indeterminate even in legacy responses with `state_ok=true`. A changed layout cannot select an old sequence's lines. Source/forecast revision binding remains explicitly unverified. |
| S5 UI findings 12–16 | Mission selection and late uploads cannot overwrite newer selections. Playback uses a complete track checked against available storyboard metadata; thinned display geometry never establishes playback position. Spherical interpolation, exact-fix tolerance, stationary heading, segment speed and dateline handling follow the documented location semantics. Nonunique antipodal intervals remain unlocated and grey. Images and GeoJSON downloads use bearer-authenticated fetches and revocable blob URLs. |
| U12 honesty | Structural strain is explicitly unavailable. Fitting utilization is not displayed as deformation. |

Cross-review reproduced and fixed partial-restraint labeling, unusable-fitting gates, concurrent follow-up submissions,
antipodal track coloring, and three asynchronous selection races. Reviewers used separate worktrees and targeted
regressions; no assertions were removed or weakened to pass the suite.

## Validation

- `make test`: **2,195 passed**, no skips or xfails. No Python implementation changes were made after this run.
- `make contract-check`: passed; generated contract and TypeScript API files are unchanged.
- Frontend typecheck, ESLint and production build: passed.
- Frontend Vitest: **498 passed in 51 files**, no skips or xfails.
- [Canvas browser check](browser_checks/canvas_drag.py): **7 groups passed** in Chromium with real pointer events,
  actual modeling requests/results, both sides-to, cancellation, creation/reconnection, invalid drop, numbered berth
  selection and all three hull-only classes. No browser runtime errors. Read-only scene hooks locate rendered entities;
  edits themselves use mouse/keyboard controls.
- [Authenticated mission browser smoke](browser_checks/mission_auth.py): **11 passed**, no failures/skips; actual image decoding and GeoJSON download
  with bearer headers, unauthenticated 401s, object-URL cleanup and no token in URLs or off-service requests.
- Baseline `demo_check.py`: **31 passed, 0 failed, 5 skipped**. It exercises four API planning chains, independent
  review/sheet/browser flows, motion and supplied synthetic advance planning. The five existing declared readiness
  checks are not promoted to passing; Bixler still owns reconciling their coverage with the integrated release gate.
- GitHub CI is intentionally skipped for the time-boxed packet at Snyder's request. Local checks were retained.

Browser artifacts/logs were written under `/tmp`, not committed. Tests run offline against loopback services, with
no LLM and synthetic demonstration data. Chromium software rendering is not a real-GPU or multi-browser acceptance test.

## Remaining work and owners

| Dependency | Lead | Next executable handoff |
| --- | --- | --- |
| A11 → U13 reviewed sheet graphic | Bixler → Kori; Snyder reviews | Freeze assessed geometry/reference revisions with sheet, plan, review and result IDs; publish immutable fixtures and rendered HTML/PDF contract. Kori then renders that snapshot. Never substitute the current canvas. |
| P6/A9 → U10 ultimate gust | Snyder + Bixler → Kori | Publish reviewed capacity/material basis, thresholds and alert result contract. Current working limits/advisories remain separate. |
| P7 → U12 strain | Snyder; Bixler asset inputs → Kori | Supply reviewed structural formulation, asset properties, validity and result schema before displaying strain. |
| A8 → U9 additional classes | Bixler + Snyder → Kori | Approved class/loading-specific fitting/chock/SWL/lead/inventory data plus a backend capability contract. CG-47, LHD-1 and CVN-68 stay hull/load-input references. A bitt gate does not prove template or engineering support. |
| S8 sequence search | Snyder → Kori | Feasible-order search and transient/handling constraints with reviewed contract fixtures. Current UI only presents existing static evidence. |
| D1/D2 public sources; A3 revision propagation | Cruz + current PR #13 reviewer; Bixler → Kori | Finish source review and immutable revision handoff through Intake/Planner/Safety, then rehearse public-source UI. This packet does not take over PR #13. |
| S7/D8 camera extensions | Snyder + Cruz → Kori | Qualified engine/state/forcing integration, own-ship input, coastline and uncertainty evidence. Existing limited transit overlay is retained. |
| Atomic mission evidence revision | Snyder M-SIM → Kori | Supply a shared track/storyboard revision token. Current ID/count/time-bound/retained-vertex checks detect contradictions but cannot prove an atomic shared revision. Incomplete evidence withholds playback. |
| A10 integrated acceptance | Bixler + Kori + Snyder | Record target-host/GPU/browser performance, authenticated streaming/gateway behavior, reviewed source evidence and engineering acceptance. Passing local UI checks is not operational approval. |
