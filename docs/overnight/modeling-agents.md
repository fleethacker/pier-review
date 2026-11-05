# Modeling and agents — overnight 4–5 November 2026

## Log

- 22:28 EST: DC7 integration PR #50 published: 1342 Python and 81 UI tests pass. Risk review found failed-solve cancellation bypass, omitted ship-fitting checks, endpoint omission and failed trajectories counted implicitly as safe. Added cancellation checks, rated ship fittings, endpoint-inclusive sampling, explicit horizon bounds/widened confidence interval and invalid all-failed state; 21 focused tests pass.

- 22:23 EST: selected forecast installation PR #49 merged after green CI (1310 Python, 81 UI). DC7 reviewed locally: measured-mode/coordinate guards and HTTP/WebSocket malformed-input regressions added; focused telemetry suite 68 passed. Optional ingest key remains local-demo-only when unset, and arbitration is not connected to environment selection.

- 21:11 EST: DC0 provider branch merged locally; fixed cache age after retry/backoff, age-bounded breaker fallback, shared-client serialization and invalid policy settings. No peer branch/worktree altered. Source/provider adapters remain data-team-owned.

- 21:08 EST: direct static tug assistance now invalidates unknown/duplicate/overrated assignments; invalid assistance produces no numeric wind limit, and tug records enter result manifests. Tide sweep accepts supplied water-level snapshots, evaluates their knots, and isolates/labels its legacy training fallback. Source and interpolation remain explicitly limited.

- 21:00 EST: auth packet PR #32 published, 1189 tests pass. Job client now enforces elapsed-time deadlines including submission/poll HTTP, handles cancelled remote jobs immediately, cancels accepted remote work on caller stop, and refuses untrusted status paths before forwarding credentials.

- 20:55 EST: agents auth integration implemented: caller credentials forwarded to modeling through worker context; plans/reports/reviews/sheets/vision jobs/ledger owner-scoped, body and per-principal rate caps. Authenticated real chain and adversarial cross-owner attempts pass. Shared confirmed berth catalog and unverified approval roles remain deployment blockers.

- 20:51 EST: integrated colleague branch ws-a/dc8-data-requests into the modeling branch, retaining its detailed asset/sensor inventory and adding our procedure, forecast-basis, propulsion and abort/replan requirements. Provider plumbing branch remains pending the stale-age review request. Jobs packet: 1179 Python and 81 UI tests pass.

- 20:48 EST: provider/intake PR #30 published with 1175 passing tests. Real agent task queue and live planner events implemented; 64 focused tests pass including gated work, saturation, cancellation, failure, and SSE resume. Persistence/authentication still separate work, not claimed.

- 20:43 EST: vision PR #29 CI green and merged. Intake now refuses to extrapolate ramp/replay snapshots as steady; missing scenario-series capability is explicit. Partial/malformed forecast coverage and future-sample quality flags propagate into safety findings. 204 focused tests pass.

- 20:41 EST: M4 PR #29 published, 1148 Python tests. M5 Anthropic Messages adapter implemented with official current protocol, explicit model/key, no network in tests, existing application guards unchanged. Full suite 1165 passed; contract-check clean; 177 provider/agent focused checks passed. Provider perception/narration quality remains unverified.

- 20:40 EST: safety PR #28 merged after green CI (1136 Python tests). Vision metadata/optional image pipeline implemented: modeling owns projection and estimated catalog capacities; confirmation uses logged toolkit and cannot replace catalog ids or promote provenance. Full suite 1147 passed before one additional confirmation regression; frontend 81 passed, typecheck/lint/build green.

- 20:30 EST: Safety basis corrections targeted 40 tests passed, including real supported demo through sheet. Explicit modeled gust limits replace mislabeled sustained limits; unsupported breaking-speed estimates removed (prior test expectation corrected accordingly). Sheet now carries validity and real source/forecast statements. OpenAI Docs skill applied to optional vision input adapter; claude-api and openai-platform-api-key skills not installed, so provider documentation will be checked directly; no live LLM dependency.

- 20:27 EST: PR #26 merged after both CI jobs passed. F24 full suite 1131 passed; frontend typecheck/lint/81 tests/build passed. No skips/xfails.

- 20:26 EST: public NWS grid AKQ/88,56 and hourly forecast downloaded (issue 23:38:07Z), plus 48h CO-OPS tide predictions. Temporary raw/provenance files only in /tmp/psp-public-data. M7 data-request inventory written. Found further safety basis defect: limiting wind is sustained but was labeled gust; breaking-speed square-root estimate also applied to fenders. Correcting via modeling-owned explicit gust limits, no fabricated breaking threshold.

- 20:22 EST: M0 PR #25 merged green. M1+M2+intake/safety fixes full suite 1121 passed. Supported scenario traversed real HTTP intake/planner/safety in 3.34s: plan AMBER, review ready_for_signature with AMBER validity floor. UI generated-type check exposed scalar-default requiredness; changed new design_basis to optional null (absent keeps MST+forecast), preserving callers.

- 20:17 EST: baseline 1108 Python tests, contract-check, frontend typecheck/lint/81 tests/build passed. Branch watcher /tmp/psp-modeling-watch.py polls every 5m until 08:00 EST; snapshots/inbox copies in /tmp/psp-watch-*. M1 tests verify all four actual outcomes.

- 20:12 EST: started from origin/dev 191a41a in ../psp-agents, agents/overnight. Main contains the same release plus its release merge. Read shared instructions and ownership. Baseline suite running.
- UI audit: planner bypasses explicit intake; sheet creation bypasses explicit safety-review selection; target defaults to 70%. Forecast risk requests 24h but saved scenarios freeze weather. Recommendation includes MST design cases regardless of moderate forecast.

## Decisions

- Integrate green PRs into dev; leave main and colleagues’ worktrees alone.
- Deliver demonstration within assumptions; seed data and unreviewed sequence rules prevent operational qualification.
- Expanded plan: [MODELING_OVERNIGHT_PLAN.md](../MODELING_OVERNIGHT_PLAN.md).

## Interfaces

- Vision: same upload/job/confirm endpoints, now real deterministic catalog drafts by metadata berth_id; no-LLM path does not claim image extraction. Optional image proposals require scale plus pier_face_start_px/end_px. POST /berth-drafts computes unsaved geometry; confirmed berths are registered via toolkit POST /berths. Drafts stay estimated/unqualified.

- F24: POST /mooring/forecast-plan (job → ForecastDockingResponse) and POST /data-simulation/forecast (ForecastSeries). Documentation docs/FORECAST_DOCKING.md; full request fixtures in contract/examples/modeling. Ten new tests cover coverage, interior peak, issue-time leakage, cancellation/budget and real API jobs.

- /mooring/recommend additive design_basis=forecast_only requires forecast_env; absent retains MST checks. Optional tugs and standoff_ft preserve assisted geometry. Candidate.tugs identifies assistance actually evaluated. Actual forecast tides retained. New forecast docking endpoint in progress.

- M1: GET /api/v1/demo/docking-cases returns four typed request bundles (ddg-supported-limited, ddg-overloaded, ddg-invalid-data, ddg-undetermined). POST environment_request to /env/scenarios, substitute returned id into scenario_request.env_source.env_scenario_id, then POST /scenarios. Direct analysis_request and optional envelope_request reproduce the named outcomes. Contract examples demo_ddg-*.json are generated.

- /intake/reports supports horizon_hours 1–120 (24 default); pass intake_report_id to /agent/plans to preserve forecast conditions.
- /mooring/recommend checks MST alternatives plus forecast_env; failed bounded search is not proof of infeasibility.
- Additive forecast-planning contract to follow; agent C owns NOAA acquisition.

## Requests

## Tomorrow

- Qualified vessel/pier data and pilot/deck-officer review remain prerequisites for live use.

## REVIEW_NEEDED

NSTM references, line/pier capacities, wind averaging conversions, tug estimates, sequence durations and intermediate handling assumptions.

- 21:15 EST: PR #34 merged after both CI jobs passed. DC0 provider branch integrated locally with cache-age/breaker/policy fixes; 1231 Python tests pass, no skips/xfails. Five complete local supported chains median 3.09 s; real TCP make-mock smoke passed intake/planner/review/approval/HTML/SSE/vision confirmation. PDF honestly returns 501 without renderer. Both temporary servers stopped.

- 21:19 EST: opt-in agent persistence now retains completed chains and audit/ownership without serializing credentials. Service-scoped job recovery prevents cross-service interruption. Durable chain, cross-owner reads, terminal SSE replay and concurrent approvals tests pass; full regression underway. Watcher found DC1 CO-OPS and DC2 NWS branches, queued for integration review.

- 21:25 EST: PR #36 pushed (1237 Python/81 UI tests, no skips/xfails). Safety hardening preserves original plus supplemental conditions and every check failure, refuses unresolved RED plans, and takes the lowest/unknown solver limit across conditions. Forecast planning now rejects poor/suspect or expired-interval inputs. Focused 31 tests pass; full suite underway.

- 21:30 EST: DC1 CO-OPS integration plus provenance/cache fixes: 1253 Python tests pass, no skips/xfails; focused provider/replay 67 pass. Bundled synthetic replay is now explicitly scenario-basis; historical CO-OPS snapshots say replay. No forecast fallback introduced.

- 21:35 EST: all four named cases traversed real local HTTP intake→planner→review→HTML. Supported: AMBER/limited, ready_for_signature (3.34 s). Overload: RED/limited, reject (4.17 s). Invalid depth: RED/invalid, revise (4.35 s). Initially underconstrained: planner repairs arrangement to AMBER/limited, ready_for_signature (3.10 s); initial result remains RED/undetermined. Search hardening now rejects locked-line bypasses of inventory/fitting constraints and reports actual assessed case counts; focused search/equilibrium 55 tests pass.

- 21:36 EST: search fixes full suite 1265 passed, no skips/xfails; UI typecheck/lint/81 tests/build passed, contract regenerated unchanged. API nonpositive-depth requests now return 422. Corrected cases_evaluated expectation: candidates that stop early no longer claim every case was solved.

- 21:38 EST: repeated-review budget regression fixed: server-created operation scopes bound each review/agent request while preserving one plan audit. Legacy/direct gateway per-plan budgets stay intact; concurrent requests within an operation cannot overspend. Focused ledger/security/client suite 52 passed.

- 21:46 EST: user requested explicit cross-agent coordination and ongoing UI recommendations. Added docs/MODELING_UI_RECOMMENDATIONS.md with endpoint/example links, priorities and implemented/pending distinctions; notified both peer inboxes to watch each other and dev. Existing watcher checks remote refs/inboxes every two minutes.

- 21:50 EST: operation-scoped budgets plus DC2 integration pass 1286 Python tests, no skips/xfails; UI typecheck/lint/81 tests/build and contract generation pass. Eighteen NWS adapter tests cover interval intersections, active-period clipping, malformed/overlapping inputs, units and stale provenance. Recorded public grid smoke yields 30 intervals covering 48h without missing gust; not an operational qualification. Posted coordination/review comments on data PRs #43/#45/#46.

- 21:54 EST: explicit environment-quality gates and corrected applied wind-factor reporting pass 1298 Python tests (no skips/xfails). Published-geometry tests prove missing/poor input cannot look valid; search/envelopes preserve invalidity. PDF issue was macOS native-library discovery: supported full chain succeeds with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib, HTTP 200/26,175-byte PDF. Documented setup, no renderer rewrite or global environment mutation. PR #47 passed CI and merged.

- 21:58 EST: safety watch hardening compares current/tide/density/wind basis with actually reviewed conditions, emits explicit recheck reasons with no stale-limit percentage, and reports provider failures as terminal source_unavailable without invented measurements. Optional wire fields preserve legacy defaults; consumer handoff updated. PDF-enabled lifecycle test also passes (1 test, 16 deliberately deselected).

- 22:00 EST: watch/recheck packet passes 1306 Python tests with no skips/xfails; focused safety/API 37 passed before two additional watch regressions. Contract regenerated; UI typecheck/lint/81 tests/build pass. Provider outages produce an explicit terminal event, never a fabricated calm reading.

- 22:09 EST: printable sheets preserve prescribed holding assistance separately from berthing tugs, show analysis/threshold references and evaluated-time/source, and escape citation text. Legacy missing assistance remains unknown. Watch condition matching now mirrors the independent review exactly (no unassessed fallback acceptance). Full suite 1308 passed, no skips/xfails; focused safety/API 41, UI 81/typecheck/lint/build, contract regeneration passed. CBOFS matching regular-grid URL and a real 3x3 layer-missing example sent to peer PR #43.

- 22:13 EST: F24 selected_config now makes modeled paid-out lengths and wet/dry conditions explicit, with installation tide on selected result/window/condition and manifest. Rechecking at a later tide reproduces stored line tensions; no supported arrival means no selected installation. Full suite 1310 passed, no skips/xfails; focused F24 19, UI 81/typecheck/lint/build pass; contract regenerated. Browser audit uses isolated ports 18100/18101/18888 and temporary tools/data outside git.

- 22:14 EST: headless Chrome browser audit of built UI with external network blocked: initial map/analysis renders and Ask agent→real SSE→Create/Open sheet completes without page exceptions. Trace confirms intake/review selection still implicit/absent; sent actionable U1 and tide-explanation notes to UI inbox. PR #48 merged after green CI; F24 installation packet ready to publish.
