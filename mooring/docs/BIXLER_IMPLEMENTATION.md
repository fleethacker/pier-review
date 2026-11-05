# Bixler implementation and local acceptance — 5 November 2026

Branch: `agents/a1-bixler-plan-implementation`, based on `origin/dev` at `1f87522`.
Requested timebox: 18:24:37–19:24:37 UTC. Changes and tests run locally, offline with
`AGENTS_LLM_PROVIDER=none` and labeled mock/supplied training inputs. No Domino deployment or release is implied.
Combined validation completed at 18:51 UTC, approximately 27 minutes after starting.

## Implemented software and consumer handoff

| Prompt | Result | Remaining dependency |
| --- | --- | --- |
| A3 | Intake accepts canonical `forecast_request`; logged resolves preserve source/revision/content/binding through Planner, independent Safety and sheet. Changed selection requires explicit reassessment. Watch retains the saved source and rejects out-of-interval use. | Agent public-revision acquisition against merged D2 and Kori's explicit UI selection. Supplied source IDs are not lookup endpoints. |
| A7 | Logged prediction tools and `GET /api/v1/predictions/{result_id}/brief` explain immutable caller-owned S7 results, retain model warnings/citations and distinguish central breaches from uncalibrated sampled exceedance. Unknown hazards/corridor stay unavailable. | Camera UI consumption, S7 state/hazard/uncertainty work; no new physics or calibration. |
| A11 / R1 | Planner freezes assessed reference geometry, configuration, environment and solved offset. Sheets persist self-contained SVG with sheet/version/plan/review/result identity, immutable hashes, rationale and line/bollard margins. Invalid, legacy or mismatched evidence cannot produce a current-map substitute. | U13 sidebar integration and target PDF setup; the existing HTML preview already contains the diagram. |
| A8 / R3 | Ship-input validation and class-specific capability routes; geometry-based templates work with arbitrary fitting IDs and supported counts. Synthetic non-DDG cases cover both sides, equilibrium, recommendation and draft sequence. | Approved CG-47/LHD-1/CVN-68 records, loading-specific fitting heights, review metadata, controlled registration and U9 display. No additional real class is declared supported. |
| A1 / A10 | Expanded existing demo runner: four planning chains with checked saved-layout or unavailable states; forecast manifest handoff; immutable S7 narration; scene/recording/speed/reconnect assertions and existing real browser flows. | Remaining requirements and readiness gates below. |
| A6 | Master plan, README, capability ledger, data requests, deployment notes and contract handoff updated against this branch. | Keep evidence current at integration. |

A8's only solver-caller change passes geometry-selected template slots into the existing recommendation search;
it does not alter search or equilibrium algorithms. Snyder should review that adapter with the template changes.
The user explicitly authorized the small S1 runtime correction discovered during acceptance: speed/reconnect
restatements after reset now report the paused state instead of issuing a second reset with the same run ID.
The existing recording validator and true reset identity requirements remain intact.

See [contract consumer notes](../contract/README.md#optional-forecast-binding-layout-and-prediction-consumers),
[prediction narration](../agents/mooring_agents/prediction/README.md), and the focused regression suites
`test_forecast_binding.py`, `test_prediction_brief.py`, `test_sheet_layout.py`, `test_a8_ship_inputs.py` and
`test_s1_session_regressions.py`.

## Validation

Commands were run with Python 3.12, Node 22.17.0, isolated temporary test/service data and installed locked dependencies.
`make contract` regenerated the OpenAPI files; `npm run types` regenerated both UI type files. No contract files
were edited by hand.

| Check | Observed result |
| --- | --- |
| `make test` | 2,293 passed in 246.94 s; no skips or expected failures. The two subsequently added consumer-fixture tests passed separately below. |
| Fixture consumers plus `test_loads_ufc.py::test_f_shallow_beam_current_to_wind`, `pytest -q -rx` | 3 passed; the conditional expected-failure path did **not** trigger |
| `make contract-check` | Contract up to date |
| `npm run typecheck`, `npm run lint`, `npm test -- --run`, `npm run build` in `frontend/packages/web` | All passed; 365 UI tests. Typecheck repeated after the final schema-description regeneration. |
| `make demo-check DEMO_CHECK_ARGS='--skip-build --browser-timeout 600 --logs /private/tmp/pier-review-bixler-final-logs'` | 35 passed, 0 failed, 3 explicit readiness skips; actual HTTP/SSE/WebSocket proxies and Chromium |
| `make demo-check-readiness DEMO_CHECK_ARGS='--skip-build --browser-timeout 600 --logs /private/tmp/pier-review-bixler-readiness-logs'` | 35 passed, 3 failed, 0 skipped. Expected nonzero exit for D1/U3 source/startup checks, complete four-case browser review chains, and S2/U5 changing forcing; these closure gates remain open. |
| Actual native `render_pdf` on the consumer fixture | Explicit `PdfUnavailable`: Pango/GObject absent; server PDF support is not established |
| Chromium print of the same saved sheet; actual PDF page inspected | Six-page PDF with frozen diagram, identifiers, margins and limited labels; browser fallback demonstrated |

The demo commands used `PYTHONPATH=modeling:agents:/private/tmp/pier-review-browser-tools`,
`PLAYWRIGHT_BROWSERS_PATH=/private/tmp/pier-review-browsers`, a temporary `DEMO_CHECK_SCREEN_DIR`,
and the installed Node/uv directories on `PATH`. The full Python command used
`PYTEST_ADDOPTS='-p no:cacheprovider --basetemp=/private/tmp/pier-review-bixler-full-tests'`.
These local tool paths are environment setup, not repository requirements.

Saved evidence: [Python suite log](evidence/bixler-2026-11-05/python-tests.log),
[baseline log](evidence/bixler-2026-11-05/demo-check.log),
[readiness log](evidence/bixler-2026-11-05/demo-check-readiness.log),
[browser-exported sheet PDF](evidence/bixler-2026-11-05/reviewed-sheet.pdf),
[PDF page one](evidence/bixler-2026-11-05/reviewed-sheet-page1.png), and the
[immutable consumer fixture/provenance](../agents/tests/fixtures/reviewed_sheet.README.md).
The PDF corresponds to `sheet_0548edb7c7084428`, with its printed plan/review/analysis IDs; it is not a fielding brief.

The first expanded browser rehearsal found a real S1 recording error after reset → speed change → reconnect:
`reset must use a new run_id`. Its other 33 checks passed. This prompted the authorized runtime fix and two
focused regression cases (speed update and evicted-history resync); the protocol/regression suite then passed 28 tests.
The original failing check stays enabled.

Existing engineering/input behavior remains covered by the full suite:

| Behavior | Regression evidence | Limit of the claim |
| --- | --- | --- |
| Displacement/loading, berth depth, wind/current vectors and lateral environmental forces | `test_loads_ufc.py`, `test_s03_load_validity.py`, `test_environment_analysis_validity.py` | Algorithm/input checks; seed coefficients and source applicability remain unqualified |
| Solved line geometry, loads, margins and envelope outcomes | `test_solved_line_geometry.py`, `test_s07_envelopes.py`, `test_s14_phase1_chain.py` | Working-load/rating checks; R4 directional rule verification and R8 structural strain remain open |
| Tide/installed line lengths and supplied forecasts | `test_supplied_tide_forecast.py`, `test_forecast_binding.py`, real advance-planning demo chain | Synthetic/supplied evidence; no public source-discovery or simulation-time forcing claim |
| Tug assignment/capacity and draft line sequences | `test_s08_s09_tugs.py`, `test_tug_assignment_validity.py`, `test_s13_sequence.py` | Existing constrained allocation and draft sequencing; R5 global horsepower objective and R7 feasible-order search remain open |
| Class capability and selection | `test_a8_ship_inputs.py`, browser named-case loading | DDG seed demonstration and synthetic non-DDG software tests; actual additional-class fitting data unavailable |

## Requirements still open

### PR preparation against newer dev

After the implementation and its original evidence above, `dev` advanced to `684db99` with provider PR #13 and
exercise/UI PR #21. Those commits are merged into this branch. The demo-runner conflict was resolved by preserving
package-aware imports and all four planning helpers. Contracts/types were regenerated, including the expanded
canonical forecast sample limit. The original 35-check browser run remains evidence for `205a7f6` before this merge.

Combined verification after the merge:

- `make test`: **2,473 passed in 267.98 seconds**, with no skips or expected failures;
  [log](evidence/bixler-2026-11-05/pr-python-tests.log).
- `make contract-check` and `npm run lint`: passed; generated types refreshed.
- macOS `npm run typecheck` and `npm run build`: blocked by existing dev exercise filenames
  `Library.tsx`/`library.ts` and `Storyboard.tsx`/`storyboard.ts`. The case-insensitive filesystem resolves the
  capitalized imports to the lowercase `.ts` modules (TS1149/TS2305).
- macOS `npm test -- --run`: **818 passed, 45 failed** across four exercise UI suites (`library`, `storyboardUi`,
  `sensorsUi`, `ui`), with undefined-component/rendering failures. Those exercise sources, package configuration and
  TypeScript configuration are unchanged from `origin/dev`. This does not replace the earlier passing 365-test result.

Linux CI uses a case-sensitive filesystem and remains the pending verification for the combined UI. No current-head
browser pass is claimed while the local build is blocked. The source/startup readiness gate now refers to missing
combined acceptance against the merged D1 interface, rather than a missing provider implementation.

### Remaining requirement gates

| Requirement | Evidence/gate still needed | Owner |
| --- | --- | --- |
| R1 | U13 sidebar consumption and actual deployment PDF support; supported HTML/saved SVG is available | Kori, Bixler hosting |
| R2 | Two-axis ship drag and fitting-to-fitting line reconnect browser proof | Kori |
| R3 | Approved additional-class fitting inputs and metadata; no DDG layout substitution | Bixler input coordination, Snyder review, Kori display |
| R4 | Verified NSTM edition/rules and approved directional fitting-rating method | Snyder; Bixler source intake |
| R5 | Fleet horsepower objective, placement contract and independently enumerated optima | Snyder |
| R6 / A9 | Supported ultimate-load law, capacity evidence and P6 threshold contract before review/watch consumers | Snyder, then Bixler/Kori |
| R7 | Feasible sequence search/intermediate-state proof and UI review-state display | Snyder, Kori |
| R8 | Structural specification and approved geometry/material/foundation properties | Snyder, Bixler input coordination, Kori display |
| R9 | All preceding requirement evidence, complete four-case independent-review browser chains and physical qualification | Bixler integration; named owners |
| D1/U3, S2/U5 | Component availability/startup rejection, changing simulation-time forcing and source labels | Cruz, Snyder, Kori |

A0 branch protection needs repository-administrator confirmation. A2 actual target rehearsal remains pending;
the user directed this work to local tests. A4 release is gated on acceptance and target evidence; no merge to
`main` or tag is performed. A5's guarded fake-provider and no-LLM paths remain in the test suite; no real-provider
or hosted-image extraction claim is made. These blockers are not marked complete by synthetic tests, an importer,
an unavailable label or a passing baseline.
