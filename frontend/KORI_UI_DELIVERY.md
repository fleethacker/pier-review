# Kori UI delivery — 5 November 2026

Owner: **Michael Kori (UI)**. Implemented by Snyder's parallel UI agents in `ui/kori-one-hour`, with separate
canvas, missions, forecast and evidence-panel worktrees and independent cross-review. The integration includes
`dev` through **`a5a8b2f`**: D1/D2/D4 (#13), exercise (#21), S2/S3/P5/P6/S4/S8 (#22), Bixler’s
A3/A8/A11 (#23), tab UI (#26), filename compatibility (#24) and documentation (#20).
The [master plan](../docs/MASTER_PLAN.md#5-kori-ui) remains the source of priorities and engineering gates.
This UI packet adds no physical coefficients or API schemas. It consumes the newly merged contracts and preserves
seed-data and synthetic/limited labels. Backend implementation is not vessel qualification.

## Delivered

| Item | Behavior and evidence |
| --- | --- |
| U3 | Public per-component availability is shown separately from the forcing actually selected for the workspace. Component source, basis, age and unavailable/error states remain explicit; public availability does not silently switch the simulation's inputs. |
| U4 | Public acquisition (`caa93c1`) requires the exact current depth/bin and covers every arrival through docking and holding. The composed manifest is retained, the canonical resolver binds the snapshots, and its content hash pins the planning request. Partial/missing forecasts block planning without a synthetic fallback. Changed source, revision or inputs require recheck; late responses cannot revive an old binding. |
| U5/U7/U8 | Motion shows forcing revision and simulation time, persistent synthetic-forcing metadata and invalid lifecycle reasons such as `FORCING_UNCOVERED`. Heave/roll/pitch require a simulated or prescribed DOF; missing directions and tug positions stay unavailable. Camera status explicitly identifies absent uncertainty and incomplete hazard coverage. |
| U9 / R2 | Ship pointer movement changes both `ship_x_ft` and nonnegative `standoff_ft`, for either side-to, without adding yaw. Fitting drag creates or reconnects lines; invalid drops and Escape preserve the arrangement. Numeric placement and keyboard endpoint selectors remain. Tests retain line numbers, types, parts, explicit paid-out lengths and installation fields. Old margins clear during edits; late responses cannot restore them. |
| U9 / R3 UI | Catalog coverage separates hull/environmental inputs, raw fitting records and usable bitts on the selected side. Missing bitts/loading block planning and editing. Changing class/berth clears previous lines, analysis and agent plan/review/sheet. Deferred-response tests cover overlapping class/scenario/berth choices, manual edits and older recommendations. This does not qualify additional classes. |
| U10 / R6 UI | Existing sustained working limits, corresponding gusts, application advisories, governing element and search outcome are visible. Missing values remain unavailable; zero is retained when actually reported. P6's ultimate-gust backend now exists, but an approved capacity basis and the UI basis-selection workflow remain missing; the UI does not invent a breaking threshold. Scenario MBS samples are not rupture predictions; missing line-MBS samples do not become zero risk. |
| U11 / R7 UI | Sequence review state, failed/unevaluated intermediate states, issues, limitations, timing assumptions, tug dependencies and citations are shown. Partial restraint stays indeterminate even in legacy responses with `state_ok=true`. A changed layout cannot select an old sequence's lines. Source/forecast revision binding remains explicitly unverified. |
| S5 UI findings 12–16 | Mission selection and late uploads cannot overwrite newer selections. Playback uses a complete track checked against available storyboard metadata; thinned display geometry never establishes playback position. Spherical interpolation, exact-fix tolerance, stationary heading, segment speed and dateline handling follow the documented location semantics. Nonunique antipodal intervals remain unlocated and grey. Images and GeoJSON downloads use bearer-authenticated fetches and revocable blob URLs. |
| U12 honesty | Structural strain is explicitly unavailable. Fitting utilization is not displayed as deformation. |

Cross-review reproduced and fixed partial-restraint labeling, unusable-fitting gates, concurrent follow-up submissions,
antipodal track coloring, asynchronous selection races, unknown forecast validity and stale forecast/recheck requests.
Reviewers used separate worktrees and targeted
regressions; no assertions were removed or weakened to pass the suite.

The incoming exercise features are preserved. Minimal component filename/import changes avoid macOS case collisions
(`Library`/`library`, `Storyboard`/`storyboard`); test-environment compatibility changes do not remove exercise behavior.
S2/S3 motion labels consume #22's supplied forcing and motion evidence; absent or unqualified fields remain
visibly unavailable or limited. This packet does not add a forcing-authoring workflow.

## Validation

The final integration includes `dev` through `a5a8b2f`, including the landing page and tabbed workspace. The
browser checks navigate those tabs; switching applications cancels active pointer gestures and capture.

- Python suite: **2,634 passed**, no skips or xfails.
- `make contract-check`: passed. Published backend contracts are consumed through generated types, never hand-edited.
- Frontend typecheck, ESLint and production build: passed.
- Frontend Vitest: **1,039 passed in 69 files**, no skips or xfails.
  CI uses Node 22. Local Node 26 JSDOM runs require `NODE_OPTIONS=--no-experimental-webstorage` so Node's experimental
  global storage does not mask the browser test environment.
- [Canvas browser check](browser_checks/canvas_drag.py): **7 groups passed** in Chromium with real pointer events,
  actual modeling requests/results, both sides-to, cancellation, creation/reconnection, invalid drop, numbered berth
  selection and all three hull-only classes. No browser runtime errors. Read-only scene hooks locate rendered entities;
  edits themselves use mouse/keyboard controls.
- [Authenticated mission browser smoke](browser_checks/mission_auth.py): **11 passed**, no failures/skips; actual image decoding and GeoJSON download
  with bearer headers, unauthenticated 401s, object-URL cleanup and no token in URLs or off-service requests.
- Baseline `demo_check.py`: **38 passed, 0 failed, 3 declared readiness skips**. It exercises four API planning chains,
  independent review/sheet/browser flows, supplied synthetic advance planning and Bixler's forecast-binding, saved
  graphic and runtime checks. The remaining component-startup, all-four-case browser and changing-forcing checks are
  not promoted to passing; Bixler owns their integrated release evidence.
- GitHub CI is intentionally skipped for the time-boxed packet at Snyder's request. Local checks were retained.

Before merge, the subsequent `dev` update `8f75b89` (#25) was incorporated cleanly. Contract/type generation,
all **1,039 frontend tests**, typecheck and production build passed again, plus **41 focused modeling tests**
covering mission evidence, motion wiring and forecast/wave adapters. The 2,634-test full Python result above
belongs to the preceding `a5a8b2f` integration; the full suite was not repeated for #25.

Browser artifacts/logs were written under `/tmp`, not committed. Tests run offline against loopback services, with
no LLM and synthetic demonstration data. The public acquisition flow has offline fixture evidence, not a live-provider
network rehearsal. Chromium software rendering is not a real-GPU or multi-browser acceptance test.

## Remaining work and owners

| Dependency | Lead | Next executable handoff |
| --- | --- | --- |
| A11 → U13 reviewed sheet graphic | Bixler → Kori; Snyder reviews | A11 merged in #23: saved SVG and immutable identity already render in the existing HTML preview. Connect the U13 sidebar to those saved bytes; rehearse target PDF support. Use the [consumer fixture](../agents/tests/fixtures/reviewed_sheet.README.md), never the current canvas. |
| P6/A9 → U10 ultimate gust | Snyder + Bixler → Kori | Backend assessment merged in #22. Supply an approved capacity/material basis, connect the UI basis-selection workflow and carry the immutable result into Safety. Current working limits/advisories remain separate. |
| P7 → U12 strain | Snyder; Bixler asset inputs → Kori | Supply reviewed structural formulation, asset properties, validity and result schema before displaying strain. |
| A8 → U9 additional classes | Bixler + Snyder → Kori | A8 capability routes and geometry-based template support merged in #23. Integrate their UI display and obtain approved class/loading-specific fitting/chock/SWL/lead/inventory data. CG-47, LHD-1 and CVN-68 stay hull/load-input references. A bitt gate does not prove template or engineering support. |
| S8 sequence proposals | Snyder → Kori | Bounded static search merged in #22; connect its proposal workflow to the UI. Current UI presents existing sequence evidence. Static search does not establish transient handling feasibility. |
| Public-source rehearsal; A3 revision propagation | Cruz + Bixler → Kori | A3 canonical forecast binding through Intake/Planner/Safety/sheet and source-bound watch merged in #23. Connect explicit public revision acquisition/selection to that agent workflow and rehearse actual providers; source IDs are not lookup endpoints. |
| S7/D8 camera extensions | Snyder + Cruz → Kori | Qualified engine/state/forcing integration, own-ship input, coastline and uncertainty evidence. Existing limited transit overlay is retained. |
| Atomic mission evidence revision | Snyder M-SIM → Kori | Supply a shared track/storyboard revision token. Current ID/count/time-bound/retained-vertex checks detect contradictions but cannot prove an atomic shared revision. Incomplete evidence withholds playback. |
| A10 integrated acceptance | Bixler + Kori + Snyder | Record target-host/GPU/browser performance, authenticated streaming/gateway behavior, reviewed source evidence and engineering acceptance. Passing local UI checks is not operational approval. |

Merged A3/A8/A11 are Bixler’s work, not new implementation in this UI packet. See the
[Bixler handoff](../docs/BIXLER_IMPLEMENTATION.md#implemented-software-and-consumer-handoff) and
[forecast/layout contract notes](../contract/README.md#optional-forecast-binding-layout-and-prediction-consumers).
