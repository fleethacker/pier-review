# Product-audit remediation record

This report records implementation for the 5 November 2026 whole-product audit of
`ac73e1fbf21a54efd029608cb140a306f69b4fa4`. [NEXT_STEPS.md](NEXT_STEPS.md) preserves the original pinned sources,
reproductions and evidence; [MASTER_PLAN.md](MASTER_PLAN.md) remains the authority for ownership and priorities.

**F01–F28 are implemented, pending independent review and final integrated checks. None is closed by this report.**
The implementation inventory below covers `fix/product-audit-remediation` through `ea62351`, based on its commit
history and changed regressions. Independent review identified two additional UI failures: paused backward seeking
could leave a prediction for the wrong input time, and custom transit inherited a hardcoded Norfolk berth. Commit `5c28b56` now forces
seek refresh/rejects late responses and leaves unbound pier/fender coverage explicitly unknown. The final reviewed
commit and integrated test results must still be recorded before acceptance.
G01–G08 remain open. All model, source, synthetic and demonstrator limitations continue to apply.

## Finding-to-implementation record

Each row has the same status: **implemented, pending independent review and final integrated checks**.
Links identify implementation commits and regression files, not a claim that every acceptance gate has passed.
F09/F10 include the additional review corrections in `5c28b56`.

| Finding | Implemented behavior | Implementation commits | Regression files |
| --- | --- | --- | --- |
| <a id="f01"></a>F01 | Stale reviews/sheets invalidated on assessed-input edits; late responses cannot restore them. | [62fea0b](https://github.com/fleethacker/pier-review/commit/62fea0b0c50992218fc4deb23ca25aa43992cf1e) | [agent.test.ts](../frontend/packages/web/src/apps/mooring/agent.test.ts) |
| <a id="f02"></a>F02 | Selected forecast identity, exact fractional operation/holding interval and direct-Planner preassessment retained. | [62fea0b](https://github.com/fleethacker/pier-review/commit/62fea0b0c50992218fc4deb23ca25aa43992cf1e), [5f7a09a](https://github.com/fleethacker/pier-review/commit/5f7a09a2238dcf376110ef0474bd2f63782e0d6d), [ac73139](https://github.com/fleethacker/pier-review/commit/ac73139cc64a22f7625f889ffcd1a67842756ac4) | [controller.test.ts](../frontend/packages/web/src/apps/mooring/intake/controller.test.ts), [test_forecast_binding.py](../agents/tests/test_forecast_binding.py), [public.test.tsx](../frontend/packages/web/src/apps/mooring/advance/public.test.tsx) |
| <a id="f03"></a>F03 | Every tide step, including internal steps, checks physical validity and withholds invalid load values. | [ae3131d](https://github.com/fleethacker/pier-review/commit/ae3131d9f29c75f38462b568182a0ddd80ad9bf5) | [test_audit_static_validity.py](../modeling/tests/test_audit_static_validity.py) |
| <a id="f04"></a>F04 | Ultimate search retains baseline/per-probe invalidity and numerical limitations. | [ae3131d](https://github.com/fleethacker/pier-review/commit/ae3131d9f29c75f38462b568182a0ddd80ad9bf5), [011d8e6](https://github.com/fleethacker/pier-review/commit/011d8e651431f2ce301cc05bf5b78538994f00a6) | [test_audit_static_validity.py](../modeling/tests/test_audit_static_validity.py) |
| <a id="f05"></a>F05 | Rich frames and recordings preserve resolved forcing availability, validity and provenance. | [9b0b9e3](https://github.com/fleethacker/pier-review/commit/9b0b9e37688a03e9174462b4a1dcfc244e9552d7) | [test_s2_forcing.py](../modeling/tests/test_s2_forcing.py) |
| <a id="f06"></a>F06 | Transit/prediction integrates and retains the final partial interval and checks its hazards. | [7b8e13d](https://github.com/fleethacker/pier-review/commit/7b8e13d0f0cc9f66ae29b93b9e3b37582f246eeb) | [test_audit_prediction_validity.py](../modeling/tests/test_audit_prediction_validity.py), [test_s6_fixes.py](../modeling/tests/test_s6_fixes.py), [test_s7b_forcing.py](../modeling/tests/test_s7b_forcing.py) |
| <a id="f07"></a>F07 | Contact at zero stand-off margin counts for central and sampled paths. | [7b8e13d](https://github.com/fleethacker/pier-review/commit/7b8e13d0f0cc9f66ae29b93b9e3b37582f246eeb) | [test_audit_prediction_validity.py](../modeling/tests/test_audit_prediction_validity.py) |
| <a id="f08"></a>F08 | Shared quality, wind-basis and validity intervals follow the actual prediction clock across the horizon. | [7b8e13d](https://github.com/fleethacker/pier-review/commit/7b8e13d0f0cc9f66ae29b93b9e3b37582f246eeb), [3c32f9a](https://github.com/fleethacker/pier-review/commit/3c32f9aacb6035661b67c0598959366811f606a4) | [test_audit_prediction_validity.py](../modeling/tests/test_audit_prediction_validity.py), [test_s7_prediction.py](../modeling/tests/test_s7_prediction.py) |
| <a id="f09"></a>F09 | Selection cancels obsolete predictions; rendered vessel/time identity and pending/lag states are visible. Seeking forces a fresh input and rejects late obsolete responses. | [02ba3e5](https://github.com/fleethacker/pier-review/commit/02ba3e52d03fa428e236ad044d476f10df301dba), [a193d47](https://github.com/fleethacker/pier-review/commit/a193d4784b8a743ca12d60956e69ab15834f0660), [f86359c](https://github.com/fleethacker/pier-review/commit/f86359ca78712276521f59cfc9b9586ca37b5f2b), [5c28b56](https://github.com/fleethacker/pier-review/commit/5c28b564f20b2bf58540dbec5e37f3e08a51ad8a) | [camera.test.tsx](../frontend/packages/web/src/apps/missions/camera.test.tsx) |
| <a id="f10"></a>F10 | Completed-run forcing and time-aligned traffic reach prediction; traffic horizon endpoints are retained. Unbound transit leaves pier/fender coverage unknown. | [02ba3e5](https://github.com/fleethacker/pier-review/commit/02ba3e52d03fa428e236ad044d476f10df301dba), [a193d47](https://github.com/fleethacker/pier-review/commit/a193d4784b8a743ca12d60956e69ab15834f0660), [5c28b56](https://github.com/fleethacker/pier-review/commit/5c28b564f20b2bf58540dbec5e37f3e08a51ad8a) | [camera.test.tsx](../frontend/packages/web/src/apps/missions/camera.test.tsx) |
| <a id="f11"></a>F11 | Safety and Intake narration select complete code-owned statements instead of accepting model-authored operational assertions. | [5d1576c](https://github.com/fleethacker/pier-review/commit/5d1576c29e97ff007078c5778027bc17bc41bc32), [6dd1b48](https://github.com/fleethacker/pier-review/commit/6dd1b48b7e0fa9828a12607e02a9c91cc9f2756f) | [test_safety.py](../agents/tests/test_safety.py), [test_intake.py](../agents/tests/test_intake.py) |
| <a id="f12"></a>F12 | Bundled backend key removed; per-tab runtime credentials cover HTTP/media and fetch-SSE; direct-key native-WS flows block explicitly. | [b22ea00](https://github.com/fleethacker/pier-review/commit/b22ea003e80c8686de4ecd61e733713afa596364) | [RuntimeAccess.test.tsx](../frontend/packages/web/src/shell/RuntimeAccess.test.tsx), [api.test.ts](../frontend/packages/web/src/apps/mooring/api.test.ts), [events.test.ts](../frontend/packages/web/src/apps/mooring/events.test.ts), [media.test.tsx](../frontend/packages/web/src/apps/missions/media.test.tsx) |
| <a id="f13"></a>F13 | Exercise controller retains draft baseline, origin and shared revision across navigation; stale shared saves remain conflicts. | [a1ec5dd](https://github.com/fleethacker/pier-review/commit/a1ec5dd26fa4b9a8fe82e21ca2d686c4e4ade936) | [library.test.tsx](../frontend/packages/web/src/apps/exercise/library.test.tsx) |
| <a id="f14"></a>F14 | Provider/numerical alert work runs in a bounded worker pool with caller context and timeout. | [a6b8b64](https://github.com/fleethacker/pier-review/commit/a6b8b64f09bc93dc903fc5c1fadb32693051346c) | [test_alert_stream.py](../modeling/tests/test_alert_stream.py) |
| <a id="f15"></a>F15 | With persistence enabled, success waits for durable terminal persistence; save failures expose failure without a result and retry the failure record. Async readers offload persistence checks. | [548879f](https://github.com/fleethacker/pier-review/commit/548879f29ce9fb5bc5f9130505831865fb4b4703), [c953a7a](https://github.com/fleethacker/pier-review/commit/c953a7a6442da60985e7bf46b98dd43aa2fab9a0) | [test_s02_jobs_store.py](../modeling/tests/test_s02_jobs_store.py), [test_job_stream_responsiveness.py](../agents/tests/test_job_stream_responsiveness.py) |
| <a id="f16"></a>F16 | Failed recording saves retain dirty state and retry before expiry/eviction, preserving owner context. | [a6b8b64](https://github.com/fleethacker/pier-review/commit/a6b8b64f09bc93dc903fc5c1fadb32693051346c) | [test_s1_review_fixes.py](../modeling/tests/test_s1_review_fixes.py) |
| <a id="f17"></a>F17 | Provider cache has entry/byte/age bounds with tested stale fallback and oversized-payload handling. | [62b2b38](https://github.com/fleethacker/pier-review/commit/62b2b3864908f790ae73c4a23dea376092c00e4f) | [test_dc0_providers.py](../modeling/tests/test_dc0_providers.py) |
| <a id="f18"></a>F18 | Final cancellation/deadline check rejects a late return even without status polling. | [548879f](https://github.com/fleethacker/pier-review/commit/548879f29ce9fb5bc5f9130505831865fb4b4703) | [test_s02_jobs_store.py](../modeling/tests/test_s02_jobs_store.py) |
| <a id="f19"></a>F19 | Manual purge cannot release capacity while a cancelled worker still runs, or evict dirty terminal records. | [548879f](https://github.com/fleethacker/pier-review/commit/548879f29ce9fb5bc5f9130505831865fb4b4703) | [test_s02_jobs_store.py](../modeling/tests/test_s02_jobs_store.py) |
| <a id="f20"></a>F20 | Composed replay and canonical resolution use consistent scenario-time retiming while preserving original provenance and finite coverage. | [71250b2](https://github.com/fleethacker/pier-review/commit/71250b2d823f8738ad90d20f41b1d73c02d5b646) | [test_d2_composed_forecast.py](../modeling/tests/test_d2_composed_forecast.py), [test_scenario_forecast.py](../modeling/tests/test_scenario_forecast.py) |
| <a id="f21"></a>F21 | Negative ramp targets reject before storage; a ramp to zero remains valid. | [71250b2](https://github.com/fleethacker/pier-review/commit/71250b2d823f8738ad90d20f41b1d73c02d5b646) | [test_d2_composed_forecast.py](../modeling/tests/test_d2_composed_forecast.py) |
| <a id="f22"></a>F22 | Telemetry authorizes vessel IDs before accepting input and scopes ordering/latest/history to principal and vessel. | [ffd1a17](https://github.com/fleethacker/pier-review/commit/ffd1a17a09937b2a74d39c1d3e98110a53c33da3) | [test_s20_telemetry.py](../modeling/tests/test_s20_telemetry.py) |
| <a id="f23"></a>F23 | Report forms clear only the successfully submitted draft; failures and edits during a request retain text. | [a1ec5dd](https://github.com/fleethacker/pier-review/commit/a1ec5dd26fa4b9a8fe82e21ca2d686c4e4ade936) | [forms.test.tsx](../frontend/packages/web/src/apps/missions/forms.test.tsx) |
| <a id="f24"></a>F24 | Fender impact uses pre-contact normal velocity at the contact point, including yaw. | [9b0b9e3](https://github.com/fleethacker/pier-review/commit/9b0b9e37688a03e9174462b4a1dcfc244e9552d7) | [test_s2_forcing.py](../modeling/tests/test_s2_forcing.py) |
| <a id="f25"></a>F25 | Rich line endpoint heights follow frame-time resolved tide while paid-out lengths remain fixed. | [9b0b9e3](https://github.com/fleethacker/pier-review/commit/9b0b9e37688a03e9174462b4a1dcfc244e9552d7) | [test_s2_forcing.py](../modeling/tests/test_s2_forcing.py) |
| <a id="f26"></a>F26 | Calm/tide-only forcing without an actual perturbation source leaves corridor/probability unavailable. | [7b8e13d](https://github.com/fleethacker/pier-review/commit/7b8e13d0f0cc9f66ae29b93b9e3b37582f246eeb) | [test_audit_prediction_validity.py](../modeling/tests/test_audit_prediction_validity.py) |
| <a id="f27"></a>F27 | Formula-leading exported text is neutralized before CSV quoting while numeric values remain numeric. | [a1ec5dd](https://github.com/fleethacker/pier-review/commit/a1ec5dd26fa4b9a8fe82e21ca2d686c4e4ade936) | [montecarlo2.test.ts](../frontend/packages/web/src/apps/exercise/montecarlo2.test.ts) |
| <a id="f28"></a>F28 | Vessel selection uses a keyboard-accessible semantic control. | [a1ec5dd](https://github.com/fleethacker/pier-review/commit/a1ec5dd26fa4b9a8fe82e21ca2d686c4e4ade936) | [views.test.tsx](../frontend/packages/web/src/apps/missions/views.test.tsx) |

## Material behavior and operating limits

- **Archived prediction validity changes intentionally.** The NOAA example's environment interval ends at
  16:54 UTC, before its 17:11 UTC prediction. It now returns RED/`invalid` with
  `ENVIRONMENT_OUTSIDE_VALID_INTERVAL`, retaining source, suspect-quality and wind-basis evidence.
  The updated fixture and `test_s7_prediction.py` assertions exercise the stricter validity rule; historical
  observations were neither retimed into current data nor relabeled as a qualified forecast.
  The first final Python rerun exposed six A7 narration tests that still used this now-invalid archived fixture
  while expecting a usable trajectory. [Commit a978b57](https://github.com/fleethacker/pier-review/commit/a978b57ff9db02bab3f370994c6ecb519226c078)
  now uses model-generated, explicitly synthetic limited input for those usable-trajectory assertions and adds an
  archived-invalid narration regression in [test_prediction_brief.py](../agents/tests/test_prediction_brief.py).
  All original behavioral assertions remain; the observed-source validity rule was not reverted. The focused suite
  passed 14 tests; the full rerun is pending. [Commit ea62351](https://github.com/fleethacker/pier-review/commit/ea62351bac9c2ded08b226b6214427b25fc7bd08)
  regenerates the input bounds and invalid prediction contract evidence and aligns the Safety narration README.
- **Safety meaning belongs to code.** Intake and Safety accept only validated selections of complete code-owned
  statements. The LLM does not compute physics, negate a finding or authorize movement. Offline behavior with
  `AGENTS_LLM_PROVIDER=none` remains supported.
- **Browser identity is runtime input.** **Access** stores a user-supplied credential only in tab memory, clears on
  refresh and supplies HTTP headers for REST, polling, media/downloads and fetch-based Planner SSE. Access changes
  restart workspaces, so drafts must be saved first. Native browser WebSockets cannot add those headers; direct-key
  mode blocks environment sockets and interactive motion-session creation. A trusted authenticated gateway is still
  required for those flows. Never put backend keys in browser builds, persistent browser storage or URLs.
- **Telemetry fails closed.** `MOORING_TELEMETRY_VESSELS` maps authenticated principals to allowed vessel IDs.
  When API authentication is enforced, ingestion rejects absent/malformed policy and unauthorized vessel identities before updating
  ordering, latest readings or history. The optional telemetry key remains an additional check. This does not
  connect or qualify a live own-ship feed for the camera.
- **Dirty recordings occupy capacity.** A failed save is retained and retried before expiry/eviction; it cannot
  silently free the session slot. Persistent storage failure can exhaust available slots. Unsaved in-memory frames
  still have no process-crash durability.
- **Alert work is bounded, not forcibly interruptible.** Four worker slots and a 30-second timeout isolate provider
  lookup and numerical alert work from the event loop. Timed-out running threads retain their slots until exit.
  Local responsiveness tests do not establish production throughput.
- **Failed durable completion never publishes a result.** With persistence enabled, a terminal-save error produces a failed job without a
  successful result, retains its dirty record and retries persisting that failure. It does not later promote the
  discarded result to success. Deadline checks precede success, and retention cannot free a live worker's capacity.

## Validation evidence

These are coordinator-observed local runs and retained evidence, not new measurements from this documentation edit.
The final integrated rerun and independent disposition are pending.

| Evidence | Observed result | Scope / remaining acceptance |
| --- | --- | --- |
| Earlier integrated Python suite | 2,776 passed | Historical implementation-stage result. |
| First final Python rerun | 2,814 tests: 2,808 passed, 6 failed | All six failures were A7 narration tests expecting a usable prediction from the now-invalid archived NOAA fixture. Corrected by `a978b57`; its focused 14 tests passed. A further full rerun is pending; this original run was not green. |
| Frontend suite and static/build checks | Latest pre-follow-up run: 1,065 passed in 72 files; typecheck, lint and build passed. An earlier run had 1,062 passed. | Final checks must use the reviewed integration commit after the remaining UI changes. |
| `scripts/demo_check.py --no-browser` | 21 passed, 0 failed, 4 skipped | Browser explicitly excluded, plus three existing readiness coverage blockers: D1/U3 component/startup acceptance, all-four-case independent browser review U1/U4, and varying-forcing UI S2/U5. This is not full readiness. |
| Focused independent review | Model timing: 65 tests plus 12 independent cases; Intake/Safety: 228 tests with no semantic bypass found; UI: 45 tests and the final seek probe passed | UI independent review is clear. Final integrated disposition and full rerun remain pending. |
| Local API integration | Four planning cases, supplied-forecast binding and runtime HTTP/SSE/WS checks passed | Real local services, offline/synthetic conditions; does not replace all-four-case browser or target-host acceptance. |
| Independent F01/F02 browser chain | Real Advance → Intake → Planner → Safety → sheet passed; forecast content hash survived selection, and Intake through sheet retained the identical full manifest. HTML retained the hash and review ID. After a 150 kt wind / 180 kt gust edit, active review/sheet actions cleared and the saved historical sheet stayed unchanged. Zero page errors. | Explicit synthetic forecast and no LLM; the selected operation narrows Advance's broader arrival window, so its binding hash changes at Intake. Safety retained an honest RED/revise outcome. This is one chain, not all-four-case readiness. |
| Independent direct-Planner and pending-review browser chain | Advance → direct Planner automatically assessed Intake with the selected content hash. A real Safety response was held unchanged while wind/gust changed to 150/180 kt; delivering it afterward restored neither review nor sheet. Zero page errors. | Real isolated services; response delivery was deliberately delayed. This verifies the pending-response race separately from edits after a completed review. |
| Browser report-save failure | Draft retained after synthetic HTTP 503 against the real mission workflow | Failure injection, not a production incident. |
| Browser exercise library | Draft location, unsaved-change guard, loaded revision and visible conflict retained | Synthetic shared-library API fixtures. |
| Browser camera | Real offline modeling API received explicit noncalm environment and other-vessel traffic; selection changed to CG-OUT with matching rendered identity; keyboard selection passed | Precedes the `5c28b56` seek/unbound-berth corrections; their final browser acceptance remains pending. |
| Browser refresh observation | Maximum observed gap 1,706.8 ms against the probe's 2,500 ms criterion | Local production browser build; this does **not** establish the master plan's ≥1 Hz target or a deployed-host SLA. |

The local browser artifacts are in
`/Users/michaelsnyder/repos/pier-review-audit-evidence-2026-11-05/`:
`ui-audit-fixes-browser-results.json`, `independent-f01-f02-browser-results.json` and
`independent-f01-f02-pending-browser-results.json`. The no-browser smoke log is
`/tmp/pier-product-fixes-smoke.log`. These are local evidence paths, not repository
artifacts or shared download links. The original audit bundle remains separate and unchanged.

Before closure, the coordinator records the reviewed integration commit, regression/reproduction disposition,
PR into `dev`, `make test`, `make contract-check`, and frontend
`npm run typecheck && npm run lint && npm test -- --run && npm run build`, including exact counts,
skips/xfails and unresolved readiness gaps. Schema/type generation must match the final source.
A passing test total alone does not close a finding.

## Separate Domino deployment

A new private [Domino demonstrator](https://pubsec-demo.domino-eval.com/apps-internal/6aed3ffcfbb42a578217356f/)
was deployed at the user's request **before these fixes**, using `dev` at
`35e0111257445d66a4d61c667a0fc0fe02472e1d`.
[CI run 42116088787](https://github.com/fleethacker/pier-review/actions/runs/42116088787) was successful.
App `6aed3ffcfbb42a578217356f`, version `6aed3ffcfbb42a5782173572`, instance
`6aed3ffdfbb42a5782173574` are private `GRANT_BASED` and undiscoverable.

Observed target checks: UI and both proxied health endpoints returned HTTP 200; a real browser reported no JavaScript
errors; an `rm0-v1` WebSocket frame arrived; Planner SSE emitted progress then succeeded `done`; anonymous access
returned HTTP 302 to login. The official `dominodatalab/domino-ai-plugin` skills and bundled MCP helpers performed
deployment; no credentials are included here.

This is a shared review demonstrator using the Domino gateway session with internal backend bearer auth unset.
The existing launcher installs dependencies and builds at startup. Target restart/recovery, native server PDF,
engineering qualification and clean-`main` release rehearsal were not tested. These checks establish neither
per-user resource isolation nor acceptance of the remediation branch. See
[DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md#a2-domino-demo-launch-and-rehearsal) for the operating boundary.

## Remaining acceptance

**G01–G08 remain open:** complete near-pier prediction/state/engine/hazards and calibrated uncertainty (G01);
real advancing-clock public acquisition and recovery through the browser (G02); coherent live own-ship and
changing-forcing continuity (G03); qualified vessel/berth/line/tug physics and references (G04); complete
ultimate-capacity/sequence/strain workflows (G05); map-independent exercise tools (G06); deployment identity,
native streaming, recovery, retention and qualification (G07); and immutable evidence through all remaining UI
handoffs (G08). Fixes to individual defects do not complete these broader capabilities.

T01 now has parameterized batch/legacy/rich forcing checks and an actual HTTP/WebSocket session regression in
`test_s2_forcing.py`. T02 has rendered vessel/time identity and local browser refresh evidence, with additional seek/unbound-berth regressions in `5c28b56`; final browser acceptance and the 1 Hz target remain unresolved. T03 has an advancing-clock composer
retry/cache regression plus UI cutoff-retry/default-lead tests; real public acquisition through the browser remains
G02 work. T04 remains in force: skipped readiness coverage, synthetic consistency and local smoke results are not
operational readiness or engineering qualification.
