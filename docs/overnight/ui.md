# UI agent log

Branch: `ui/frontend-updates` (off `dev` at `191a41a`). Not merged into `dev`: the owner asked to keep building on this
branch until they say otherwise.

## Log

- U0 baseline: `tsc`, `eslint` clean, 81 unit tests pass. `npm` is not installed on this host, so checks run through
  `node_modules/.bin/*`; `app.sh` downloads Node 20 itself.
- U0 fix: the dev proxy defaulted to `http://localhost:800x`, which resolves to `::1` here while the services listen on
  `127.0.0.1`, so every call returned 500. Defaults are now `127.0.0.1` (`app.sh` already set them explicitly).
- U0 fix: duplicate React keys in the agent panel (steps, rationale, assumptions) logged warnings on every plan.
- U2 motion view (2D): `src/apps/mooring/motion/`. Frame adapter for legacy and `rm0-v1` frames, controller for live
  sessions and recording playback, SVG plan canvas, badges, readouts and controls. Contract-consumer tests read the
  example frames from `contract/examples/modeling/`.
- Verified in headless Chromium against `make mock`: plan, apply, open motion view, start session, resume, tug command
  and recording replay, with no console errors.

- U3: data-source and capability panel (`status/`), standing "all results limited: seed data" banner.
- U5: berth-from-image panel (`vision/`): upload, detections overlay, confirmation gate, save and select.
- U6: `make demo-check` (`scripts/demo_check.py`, `scripts/demo_check_browser.py`): 20 checks on a fresh production
  build, including the WebSocket through the preview proxy. Screenshots in `docs/overnight/screens/`.
- U1 (partial): readable errors for 429/502/503/504/timeouts (`describeError`), duplicate React keys fixed in every
  text-keyed list (the safety sheet repeats rationale sentences).
- Findings worth knowing: safety-sheet creation can exceed the physics tool's 30 s limit when the CPU is busy
  (headless software WebGL does that); the UI now says so plainly and the check retries. The simulator allows 4
  sessions at once, shared by all clients.

## Decisions

- Motion view draws in an SVG panel fed by the motion store, not in the Cesium scene. The doc allows this fallback; the
  Cesium scene is a different coordinate setup and the SVG view is testable without WebGL.
- Live frames render through a latest-frame slot (one paint per animation frame), never a queue.
- Sessions are scarce (4 per principal, shared by all clients, held 30 min). "Restart session" resets the running
  session when the layout is unchanged; closing the view pauses and keeps the session.
- Legacy frames carry no scene, so the berth orientation is assumed (`090`) and flagged with a badge.
- Absent validity is `unknown`; absent components are `unavailable`; plain-text legacy alerts get no invented severity.

## Interfaces

- Proxy: `/api/modeling/*` and `/api/agents/*` (REST and WebSocket, `ws: true`). Targets from `MODELING_PROXY_TARGET` and
  `AGENTS_PROXY_TARGET` (default `http://127.0.0.1:8000` and `:8001`).
- Fixtures served from `./fixtures/` (copied from `contract/examples/modeling/` at build): `sim_recording_60s.json`,
  `sim_scene.json`.
- Contract fields the motion view consumes: `SimFrame` legacy fields, `schema_version`, `sequence`, `run_id`, `scene_id`,
  `motion.*`, `tug_states`, `line_states`, `fitting_loads`, `fender_states`, `environment.*`, `forces.*`, `validity`,
  `provenance`, `structured_alerts`; `SimScene` outline, fittings, fenders; `SimLifecycle.state`; `SimSessionCreated.scene_url`.

## Requests

- B 07:27 EST: User has now explicitly authorized integration of `ui/frontend-updates` only; ignore `frontend-exercise`. Integration in a separate owned checkout preserves your commits and all current dev fixes. Nine reproduced input/validation/race counterexamples are fixed, including motion snapshot reuse, creation/scene-loading changes, initial offsets and upload limits. Combined 1,734 Python / 191 UI tests pass; final scoped browser/API checks pass 20/20, plus the separate four-case initial-analysis browser probe. Explicit Intake/review UI controls remain open; this does not claim the complete acceptance gate. Original final report below is historical and predates real provider/vision/dynamics integration.

- B 06:40 EST: Final narrow validity-display fix: invalid, unknown or absent validity no longer supplies green line/fitting colors, percentages, drift or data-key metrics. Editing parts/dragging clears old map values immediately, including after a failed recheck. Sheet sidebar and canonical HTML withhold unusable margins/thresholds/tug requirements. Eight map/list/edit counterexamples, six summary/sidebar cases and three print cases failed before; positive valid/limited cases retained.128 UI tests/typecheck/lint/build pass; real Chrome with real APIs confirms all four saved cases and existing recommendation/risk/sheet probes without page errors. Full Python run finishing. Held UI branch/worktree untouched; preserve these shared fixes. Tide prose now states height/installation dependence instead of claiming all rising tides slacken lines.

- B 03:53 EST: Berthing-window request bounds now reject naive timestamps and reversed intervals, and normalize aware times to UTC before sampling. Five counterexamples reproduced (three invalid bounds plus spring/fall clock-change sampling);37 focused tests pass, full gates running. Schema-only behavior change; no provider, simulator or clock edits. Please send ISO timestamps with explicit offsets/Z from date controls. Contract/types descriptions regenerated.

- B 03:49 EST: Fleet semantics corrected across tug plans/windows: omitted/null available_tug_ids means catalog, [] means explicitly none, duplicate IDs reject422. Do not default an empty selection back to catalog. Existing assigned holding tugs stay in the base solve; returned assignments remain additions. Seven cases cover this;1724 Python/106 UI tests and all gates pass. Contract/types descriptions regenerated.

- B 03:42 EST: Reproduced the earlier unbound sheet-map concern and a late-response race. Small shared fix withholds live/cached canvas captures (they are not bound to the immutable plan) and explains the missing diagram; pending sheet/approval responses cannot overwrite a new planning run. Three counterexamples failed before; additional late-approval success/error tests cover the guard. Future diagram should use persisted plan/result geometry and IDs, not current canvas. This does not implement the explicit Intake/review gate. Held branch untouched; preserve when integrating.

- B 03:38 EST: F24 now supports explicit `allow_short_lead=true` for a newer forecast inside 24h before the same arrival. Default 24h lead is unchanged; retain selected_config and submit fresh supplied snapshots, never transfer old approval. Generated `mooring_forecast_reassessment.json` shows four-hour synthetic guidance. Observations at as-of cannot be held as future forecasts. 1717 Python/101 UI tests and all gates pass. See docs/FORECAST_DOCKING.md and optional UI recommendations; public composer remains unavailable. #95 merged with sustained-wind ring/unknown-bearing display fixes. Please continue watching dev and both colleague inboxes; no held branch/worktree edits.

- Modeling B, 03:24 EST: Follow-up narrow dashboard/chart fix: sustained wind ring matches limit_wind_kt; invalid/unknown envelope plots withheld; missing bearings are not bridged by filled polygons; all-zero plots avoid NaN. Five regressions reproduced;101 UI/1709 Python gates pass. Actual Chrome with real local APIs/external network blocked confirms the wind basis and prior risk/training labels, no page errors. Current shared files only; held branch untouched. Preserve when integrating.

- Modeling B, 03:20 EST: Small shared dashboard correction in progress: withhold risk percentages for invalid/unknown validity or n_valid<=0/unknown; absent MBS shows n/a; pointwise statistics and synthetic timeline labels are explicit. Six UI counterexamples reproduced before/pass after. Backend fender risk percentiles now report reaction lbf, not energy mislabelled as lbf; energy exceedance comparison unchanged. Please retain these fixes when adapting your held branch. No feature branch/worktree edit. A separate wind-limit display concern remains: current dashboard compares a gust ring against sustained-wind limits; next narrow fix will match sustained to sustained.

- Modeling B, 03:14 EST: Risk endpoints now reject aggregate work above25,000 solves with422 before queueing. Current UI requests remain supported. Preserve sample/horizon controls on rejection; never silently downsample. Contract/types regenerated (descriptions only).1707 Python/90 UI gates pass. A separate longer frozen-export TCP soak remains running; no completion claim.

- Modeling B, 03:05 EST: Ship-specific Intake is required to establish MST suitability. Unknown ship_mst now leaves MST-WITHIN-SHIP failed/AMBER, so a berth-only report cannot yield ready_for_signature. Aggregate expired/out-of-range forecast intervals now produce RED quality findings even on nonpeak samples. No wire changes;1695 Python/90 UI gates pass. Continue to use scenario_id or explicit ship/berth/side for the normal Intake flow.

- Modeling B, 03:00 EST: Timing fix pending integration: Intake returns UTC sample times and labels Z correctly; source interval/issuance comparisons handle named-zone repeated hours. No wire fields or provider behavior changed. 1691 Python/90 UI tests pass. One-hour slow-reader soak found no stall of other streams; this is not a latest-frame guarantee—keep warning timestamp/age visible. Watcher now watches local and remote refs; please continue to check dev and both peer inboxes.

- B 02:48 EST: Additive Candidate.resolved_config now exposes the installation behind analysis_result_id; existing config remains assignment-only for F24 arrival-specific installation. Contract/types regenerated. Shared controller uses resolved_config when present, forwards standoff/tugs, rejects assistance changes in flight and stale geometry on apply. Four UI regressions failed before;90 UI tests/typecheck/lint/build and1678 Python tests pass. Preserve these small integration corrections when merging your UI work; no held-branch/worktree edits. Modeled spans remain reproducibility inputs, not cutting instructions.

- B 02:39 EST: Small shared controller integration fix: applyCandidate now sets candidate.tugs (including empty) before lines, so subsequent analysis does not retain the previous fleet. Two regressions failed before;86 UI tests/typecheck/lint/build pass. Separate code-review concern for your flow: createSheet/loadSheet currently captures the present map without verifying it still depicts the plan’s geometry; preserve plan-matching imagery or omit a stale capture when the user changes ship/berth/lines while viewing an old plan. This latter concern is inspection-only, not a reproduced browser failure.

- B 02:32 EST: Published provenance is not rating verification: unverified tug records now remain demonstration/limited in qualification responses. Static assumptions/capabilities explicitly say wind/current only, wave/wake loads not evaluated. No schema/physics changes. UI suggestions now start with current dev gaps: explicit Intake/independent review remain priorities; do not infer included wave forces from a wave-height display.

- B 02:28 EST: Safety source_unavailable now also covers malformed modeling JSON/schema responses; same terminal RED event shape, no substituted weather or percent. UI should end the active-monitoring state and show reconnect/recheck rather than retain a fresh-looking limit. 1671 Python/84 UI tests and contract-check pass; no wire changes.

- B 02:23 EST: Confirmed shared berths now persist with file-backed MOORING_DB and its backup/restore; default storage stays ephemeral. POST /berths remains identical-retry201 / conflicting-ID409, reads remain shared, and schema is unchanged. Changed geometry needs a new ID; saved does not mean engineering-approved. Separate-process/restart/restore checks pass. UI guidance updated in docs/MODELING_UI_RECOMMENDATIONS.md. Please retain immutable-ID behavior when wiring vision confirmation or reference generation.

- 02:05 EST, B: Added optional warning-age guidance to MODELING_UI_RECOMMENDATIONS. Display at_utc age separately from receipt time; delayed SSE messages must not appear fresh. Source continuity and temporal guards are merged into dev. A real TCP slow-reader probe is underway, alongside reconnect testing; no latest-frame delivery guarantee is being claimed. Explicit Intake/review selection remains the outstanding UI gate; backend chain, approvals, persistence and restart failure states are verified.

- 01:35 EST, B: Safety SSE watch now follows the plan saved-source endpoint, matching Intake/Planner/UI. Source failure ends with existing source_unavailable event; it never switches to generic weather. Future observations/later-issued inputs suppress old gust-limit percentages with RED recheck. No schema/endpoint changes; preserve these unavailable/recheck states in the UI.

- B 01:27 EST: Intake now shares F24 temporal availability checks from core/forecast_provenance.py. Future observations, future-issued guidance and public forecasts lacking availability provenance are excluded from windows/MST/planning conditions and optional narration, with RED missing-data findings. Invalid current temporal provenance returns422. Intake created_at_utc is the availability cutoff captured after retrieval; actual issuance versus retrieval distinction preserved. No source substitution or physical arithmetic added.


- B 01:21 EST: Berth confirmation/registration requires nonempty depth_profile, unique x stations, unique fitting/fender IDs and bounded lat/lon; malformed data returns422 without poisoning the catalog. Single-point and unordered unique profiles remain supported. Current vision fixtures pass. Preserve field errors rather than substituting a depth or merging duplicate assets.

- B 01:19 EST browser evidence: all four named saved scenarios loaded through canonical source resolution with no page errors (AMBER/limited supported, RED/limited storm, RED/invalid inadequate depth and underconstrained). 84 UI/1608 Python tests pass. Explicit Intake/review flow is still open. ResultPanel also prints diagnostic numerical metrics for invalid results (e.g. underconstrained 0%); recommend suppressing or clearly marking these unusable rather than presenting them as a usable margin. Shared saved-source change only; held feature branch unchanged.

- B 01:15 EST: Small shared integration correction underway in controller.loadScenario: use GET /scenarios/{id}/environment, not generic /env/now. The latter bypasses explicit mock versus configured public source, so map and agents can assess different forcing. No feature-branch edit; testing canonical source selection and failure-without-substitution. Also the current UI objective selector still offers storm_prep/berthing, which the agent explicitly rejects; recommend disabling/labeling those until implemented.

- B 01:12 EST: MooringConfig now rejects duplicate line_number IDs with422; empty layouts and numbering gaps remain allowed. Reproduced analysis previously returned duplicate rows [1,2,3,4,5,6,1], making commands/results ambiguous. No automatic renumbering. Shared schema/contract/type update in progress; ensure imported/duplicated line objects get distinct IDs.


- B 01:08 EST: Shared catalog audit found POST /berths could overwrite seed/runtime geometry behind other scenarios. Registration now accepts identical retries but returns409 for changed data under an existing ID; revisions need a new ID. Vision first-confirm behavior is unchanged; edits after confirmation need a new draft. Writes/reads are locked and copied; no role/admin system or persistence claimed. Generated contract/type update underway; do not retry a conflicting overwrite.


- B 01:01 EST verification: exact Makefile and app.sh PDF_LIBRARY_PATH launchers both pass full TCP chain and PDF200, plus app.sh UI proxy. Standalone default Vite proxy also passes on this Node26 host; no vite.config.ts edit made. Your localhost/IPv6 fix may still be needed on your runtime. Temporary services stopped; 1599 Python/82 UI tests pass.

- B 01:01 EST: The same optional PDF_LIBRARY_PATH is also forwarded inside shared app.sh, so the combined launcher can render PDFs after protected-shell startup. Small additive startup edit only, no UI feature branch change. Investigating the already-reported localhost→IPv6 default proxy mismatch on dev; app.sh itself sets IPv4 targets.

- B 00:59 EST: Fresh `make mock` TCP smoke reproduced PDF501 despite an outer DYLD_FALLBACK_LIBRARY_PATH. Small shared Makefile change adds optional `PDF_LIBRARY_PATH`, assigned to DYLD_FALLBACK_LIBRARY_PATH inside the agents recipe. New documented invocation: `make mock PDF_LIBRARY_PATH=/opt/homebrew/lib` (Intel: /usr/local/lib). Default remains explicit501 when native libraries are unavailable. Exact command smoke underway; no UI/provider changes.

- B 00:54 EST: Intake headlines retain input-quality qualifications even with no physical concern windows. HTML/PDF sheets now print assessment assumptions and limits; ordinary Intake selects representative snapshots, whereas `/mooring/forecast-plan` assesses an arrival/holding interval. Preserve this scope in UI labels. DDG has a seed fitting layout; CG/LHD/CVN remain hull/load-only with explicit missing-layout errors. 1594 Python/82 UI tests pass, no skips/xfails. Shared handoff updated; held UI branch remains untouched.


- B 00:50 EST: Intake data_quality and Safety watch now propagate declared component quality/validity independently of the aggregate flag. Poor/out-of-interval is RED, suspect AMBER; unknown issue/quality and provider limitations remain visible INFO. A quality-only change can require recheck with no stale utilization percentage. No wire changes; render existing data_quality/recheck_reasons. 1587 Python/82 UI tests pass.


- 00:38 EST, modeling agent: Printable-sheet HTML/PDF now includes forecast assessment, current toward bearing, MLLW water level and recorded wind/component provenance. Retrieval is explicitly not issuance/freshness; unknown basis stays unknown. Repeated table headers improve multipage print. Existing endpoints; no wire/schema change or UI source edit. Supported-case native PDF smoke passes with AMBER/limited and ready_for_signature, not operational qualification.

- 00:30 EST, modeling agent: Line geometry reports/rules now use the solved span and ship-relative horizontal angle including yaw. `length_ft` is the current straight span; resolved config paid_out_unstretched_length_ft is the installed rest span. Optional line-detail labels should distinguish them. No UI source edits; generated types describe the distinction.

- 00:23 EST, modeling agent: Analysis now publishes optional result.resolved_config; the final Planner config retains its explicit paid_out_unstretched_length_ft and wet/dry fields. Existing apply/save paths that preserve all line fields can therefore keep the assessed installation without UI geometry calculations. Retain installation tide for provenance; legacy plans still need its explicit reanalysis handling. No hand-edited UI code in this change; generated types updated. Values are not cutting lengths/handling instructions.

- 00:14 EST, modeling agent: Additive GET /scenarios/{id}/environment resolves the saved source consistently with Planner/Intake and alerts. Explicit mock remains synthetic even when CO-OPS is configured; live retains its existing meaning of the configured default provider, which may be mock. Display actual snapshot.source and metadata, not the saved mode name as proof of a live measurement. Contract/types regenerated. Optional consumer improvement; no UI flow changes required.

- 00:08 EST, modeling agent: Optional source-panel interface: `metadata.components` separates wind/current/water-level source and timing; forecast-plan separates actual issue and retrieval lists. Show retrieval as retrieved, not issued/fresh. Types regenerated; legacy wire shape retained. The complete live composite provider remains unavailable. See docs/FORECAST_DOCKING.md and MODELING_UI_RECOMMENDATIONS.md.

- 23:55 EST (B): applying two small shared-file fixes on the modeling integration branch after the earlier unaddressed review: `AgentSession.applyPlan` uses `holding_tugs` (including empty), and `SceneRenderer.capture` reads the preserved canvas without forced render, with a zero-size guard. Holding tests use distinct berthing/holding fleets and check empty/undo. These changes do not merge or edit your held branch; merge dev to pick them up. Installation-tide consumption, stale motion scenario and vision/source-label changes still need UI work.

- 23:48 EST (B): isolated browser experiment removes forced `viewer.render()` from scene capture and uses the preserved canvas; sheet/approval/motion/replay now pass with no browser errors (19 pass, 1 fail, 0 skip). Remaining vision assertion expects BERTH DATA: VISION, but actual confirmed catalog draft correctly remains ESTIMATED. Saved berth is selected/displayed. Please expose `extraction_source`/`extraction_note`, avoid claiming image extraction in deterministic mode, and align the assertion with real provenance. `/ws/alerts` fix will document terminal close codes 1013/4404/4400; no invented alert is emitted on unavailable data.

- 23:39 EST (B): holding-tug search returns additions, not a replacement fleet. Preserve request assistance when applying `/tugs/hold-plan`; the final agent `holding_tugs` list is the combined assessed fleet. Result assumptions/tool description now state this explicitly.

- 23:35 EST (B): new plans/sheets expose optional `installed_at_water_level_mllw_ft`; retain it on map reanalysis alongside `holding_tugs` so later tides do not silently reinstall/retension lines. Missing legacy values remain unknown. Types/fixtures regenerated with the packet; see MODELING_UI_RECOMMENDATIONS.md.

- B 23:30 EST: F24 hardening rejects future replay without archived prediction/issuance provenance, reports invalid per-condition input rather than aborting other arrivals, and marks aggregate invalid/RED when no arrival has a complete usable assessment. Overloaded but assessed cases remain RED/limited. /capabilities now lists advance docking assessment and corrects stale provider/replay/telemetry descriptions; none are qualified.

- B 23:23 EST: isolated offline browser check reaches the sheet but Cesium raises “DeveloperError: Expected width to be greater than 0, actual value was 0” and stops rendering; its error modal then blocks approval and motion test locators. Repro: current dev merged locally into 6faddf0, local null-bbox/fixture fixes, Chrome 1600x1000, external requests blocked; Ask agent → Create sheet. Screenshot /tmp/psp-ui-review-screens/FAIL-phase-1-safety-sheet-approval-and-print.png. Root cause not yet established; do not count this browser run as passing. API/proxy chain and motion control passed.

- B 23:21 EST: compatibility review finds stale motion snapshots: controller.motion.ensureScenario reuses scenarioId, but setEnv/setLoading/setShipX/setStandoff/setTugAssignments do not clear it; layoutKey also omits environment. After saving then editing these inputs, a new/reused session can use old forcing/config. Save a fresh snapshot for a changed simulation input signature (include environment), and test each edit. Your demo-check API chain succeeds but its default plan is RED; it does not prove the required supported-limited case or independent intake/review flow. Please exercise GET /demo/docking-cases bundles and assert the intended outcomes.

- B 23:20 EST: detected ui/frontend-updates 6faddf0 and respect its owner-directed no-merge hold. In an isolated local compatibility worktree merged with dev: typecheck fails at BerthVisionPanel.tsx:166 (bbox_px can be null) and logic.test.ts:5 (generated Detection fixture needs center_px:null). Render no rectangle when bbox_px is null; keep confirmation table/limitations. Also UI accepts GIF/12MB but backend accepts PNG/JPEG/WebP up to 8MB. Local review patches only; your branch/worktree untouched. Holding-tug application bug from 22:15 remains in this branch.

- B 23:04 EST: DC5 integration serves the existing unqualified fitted artifact from /env/gust-model, with global-only sector display when no sector fits exist. Optional UncertaintyModel.sectors are exploratory, not used by the global risk sampler; do not imply per-direction qualified risk. No new observed artifact is included.

- B 22:55 EST: Live risk alerts now carry optional validity; invalid data/plan results are RED without usable utilization. Limited seed assessments are AMBER or RED with explicit wording. Observation-only alerts never assess mooring adequacy. Please show validity reasons beside severity/staleness; generated types follow.

- B 22:49 EST: sequence checks now honor scenario loading/MST, deployed parts, tug release, input quality/depth and rated assistance. AgentPlan/SafetySheet gain optional sequence_result_id; printable HTML/PDF carries per-step static state/note and source reference. Please preserve/display these in sequence views, including undetermined first-line restraint. All four demo chains still complete with expected outcomes.

- B 22:31 EST: Risk timeline now accepts supplied forecast snapshots and publishes exact per-step environment/validity, failed counts and bounds. Omitted series is explicitly synthetic_training regardless of provider settings. Details in FORECAST_DOCKING.md and MODELING_UI_RECOMMENDATIONS.md; additive contract/types follow.

- B 22:26 EST: risk hardening adds optional horizon p_event_bounds/effective_step_min; failed trajectories are unknown, and all-failed calculations are invalid/RED. Please show bounds and failed counts beside probabilities; p_event is a lower bound when failures occur. Updated docs/MODELING_UI_RECOMMENDATIONS.md. Risk job response models were also absent from OpenAPI because HTTP 202 only exposed JobAccepted; ExceedanceResponse/TimelineResponse are now explicitly registered. Generated types accompany the packet; no UI behavior edits.

- B 22:15 EST P1 confirmed browser mismatch: AgentSession.applyPlan in frontend/packages/web/src/apps/mooring/agent.ts uses plan.tug_plan?.assignments for holding reanalysis. Replace with actual plan.holding_tugs (explicit [] means no holding assistance); keep berthing tug plan separately visualized/labeled. Browser showed four berthing tugs applied and map line percentages different from the same plan’s safety sheet. This is the integration bug flagged at 20:14, now reproduced; backend already preserves actual holding_tugs. Add consumer regression for a plan with holding_tugs=[] but nonempty tug_plan.assignments, and one with nonempty holding assistance. No frontend code edited here.

- B 22:14 EST browser evidence: built UI works offline against isolated local services (Chrome, all external requests blocked), no page exceptions; Ask agent→SSE→Create/Open sheet completes. Request trace confirms no explicit intake or review selection (sheet triggers review implicitly), so U1 wiring is still needed for the supported forecast path. Also Data Key says falling tide always tightens and rising always slackens; this depends on relative fitting heights. Suggest “Tide changes line lead and tension; use the evaluated tide sweep to identify governing lines.” Screenshots/logs temporary under /tmp/psp-ui-*.png and /tmp/psp-browser-flow.log; no UI code edited.

- B 22:12 EST: F24 result adds optional selected_config with explicit modeled paid_out_unstretched_length_ft and wet/dry condition, plus installed_at_water_level_mllw_ft on selected result/window/condition. Preserve selected_config when applying/rechecking at later tides; otherwise implicit defaults can retension every line. No selected_config when no supported arrival. Values are modeled spans, not deck cutting/handling instructions; see docs/FORECAST_DOCKING.md.

- B 22:08 EST: SafetySheet adds optional analysis_result_id, threshold_result_ids and holding_tugs (null/absent = unknown legacy record; [] = explicitly no prescribed assistance). Printable sheet separates holding assistance from berthing tug plan and labels evaluated-condition time/source and visible citations. Please preserve these distinctions in UI sheet views.

- B 21:58 EST: safety watch adds optional requires_recheck/recheck_reasons to GustWarning, clears percentages when current/tide/density/wind basis differs from reviewed conditions, and emits RED for unusable inputs. New terminal SSE source_unavailable (SafetyWatchUnavailable) carries no measurements and a retryable flag; show unavailable, reconnect with backoff if retryable. Generated types refreshed only. This requests reanalysis, not a recalculated threshold.

- B 21:54 EST: PDF renderer now verified via full local supported chain (HTTP 200, 26,175 bytes) with DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib supplied at stack startup. Libraries were installed but undiscoverable; no renderer rewrite needed. See agents/README.md setup. Keep 501→HTML/browser-print fallback for hosts without native libraries. Direct load/mooring input-quality gates now preserve poor/missing/interval reasons and null invalid wind limits; display those validity reasons.

- B 21:46 EST, user-requested coordination: please watch origin/dev and all active peer branches/inboxes throughout the night, read Interfaces/Requests at each integration point (at least every 5 minutes while active), and publish changed contracts plus green commits promptly. I am watching every 2 minutes and integrating reviewed work in my own worktree; never edit peer worktrees or auto-merge unchecked changes. Reply with blockers in docs/overnight/modeling-agents.md → Requests. New optional UI capability handoff: docs/MODELING_UI_RECOMMENDATIONS.md; choose/adapt/defer against your UI priorities. It covers forecast arrivals, line placements, tide tending, training scenarios, progress and provenance, with implemented vs pending explicitly separated.

- B 21:38 EST: ToolCall adds optional operation_id for server-created agent runs; plan_id still links the full audit. Repeated safety reviews now get separate bounded tool allowances. Generated type refresh only; no UI behavior required.

- B 21:35 EST: all four demo bundles run through complete real HTTP agents and HTML. The ddg-undetermined bundle describes its initial one-line analysis/envelope; planner may repair it to AMBER/limited. Preserve/display initial outcome separately from final plan. Storm remains RED/reject; below-draft case RED/invalid/revise; supported case AMBER/limited/ready_for_signature.

- B 21:25 EST: supplemental safety intake adds to original plan conditions; it cannot replace them. New PLAN-NOT-RED check preserves unresolved planner failures. Forecast windows reject poor/suspect or expired inputs. API descriptions regenerated (small generated-types refresh only).

- B 21:08 EST: tide-sweep adds optional water_level_forecast (EnvironmentSnapshot list). Absent = explicitly synthetic training tide; supplied incomplete/flagged/gapped data returns 422, never synthetic fallback. Endpoint now rejects invalid timezone/range/tending lengths and includes final partial report intervals. Tug-invalid wind envelopes have outcome=invalid_inputs with null limits.

- B 20:55 EST: agents now support opt-in bearer identity inherited from MOORING_API_KEYS (AGENTS overrides available), forwarding caller credentials to modeling and owner-scoping agent objects. Default stays open local-demo. UI credential entry/storage is not implemented here; keep auth off for offline demo. If enabled later, HTTP/SSE clients need Authorization headers; do not put tokens in URLs.

- B 20:48 EST: agent intake/planner/review/vision now return 202 before completion. Always poll the job/plan or consume terminal SSE; do not assume an immediate GET is succeeded. Planner step/proposal events are real-time; done adds optional state/error for failures/cancellation. DELETE /jobs/{id} cancels; queue 429 carries Retry-After. Keep displaying the final qualification warnings.

- 20:40 EST modeling: vision upload now accepts optional berth_id and pier_face_start_px/end_px, returns extraction_source/note, geometry_result_id and image hash. Without anchors/LLM, draft is explicitly catalog-derived, not image-derived. Confirmation registers a real selectable berth, preserving estimated provenance. Generated types refreshed only.

- B 20:30 EST: safety contract adds optional validity on review/sheet and limit_gust_kt/advisory_gust_kt on envelope points. limit_wind_kt remains sustained. Breaking gust is now null: old sqrt(WLL factor) estimate was unsupported for combined loads/fenders. Please show unavailable rather than zero. Generated types updated.

- B 20:25 EST: additive /mooring/forecast-plan job contract and generated mooring_forecast_plan.json example ready on my branch; /data-simulation/forecast provides labeled 48h training data. See docs/FORECAST_DOCKING.md. Supply as_of plus arrival >=24h later and operation/holding duration. Render unavailable/undetermined separately; selected arrival is limited/static, not maneuvering approval. Generated modeling.d.ts refreshed again; regenerate after merging.

- B 20:22 EST: Generated src/api/modeling.d.ts refreshed (small additive cross-boundary change for CI; no UI logic edited). Preserve/regenerate on your merge. Planner now searches actual intake conditions (explicit forecast_only basis) and stops when within target even if seed validity is limited; final status remains AMBER.

- B 20:17 EST: GET /api/v1/demo/docking-cases now published on agents/overnight with typed bundles and generated demo_ddg-*.json examples. Create env then scenario with returned env id. Supported case is honestly AMBER/limited, storm RED, below-draft invalid, one-line plan envelope undetermined.

- Agent B 20:14 EST: modeling on agents/overnight; expanded plan docs/MODELING_OVERNIGHT_PLAN.md. Please wire explicit intake_report_id into planner flow, distinguish steady saved weather from forecasts, and render independent safety review before sheet approval. Adding 24h-ahead docking planning with coverage beyond arrival; additive contract/fixtures will follow. Preserve holding_tugs (actual final analysis assistance), not just berthing tug_plan assignments. Four named scenario examples forthcoming.


- To the simulation agent: (1) the live frames are still legacy (no rm0 fields, no scene, no tug positions), so the
  live view shows lines, tugs and environment as unavailable. (2) The WS protocol has pause, resume and reset only; a
  speed control needs a new client message. Live speed is disabled and labeled until then.

## Tomorrow

- Cesium-scene version of the motion view (shared camera) and the 3D view (U4).
- Live speed control, once the protocol has it.

## Final report

**What works** (all verified by `make demo-check`, 20 of 20, plus 135 unit tests, `tsc` and `eslint` clean):
Phase 1 in the browser (plan with SSE steps, safety sheet, approval, print), the 2D motion view for live sessions and
recordings, the data-source and capability panel, berth from an image, Navy/Metric in the new views.

**How to run it:** `make install && make mock`, then `cd frontend/packages/web && npm install && npm run dev`; or
`make demo-check` for the headless run (set `DEMO_CHECK_BROWSER_PYTHON` to an interpreter with Playwright).

**Labeled limited, mock or synthetic:** every result (seed data); the motion fixture (mock, authored values); the vision
backend (mock: it copies the seed Pier 12 berth and says so); environment (mock, "live" mode still serves the mock);
waves, wake and telemetry (unavailable, never zero).

**Done since the first report:** Cesium map mode and 3D camera presets (U4), the intake agent in the UI, per-panel error
boundaries, reduced-motion support, narrow-width layout, a per-frame cost test, optional bearer token for REST.

**Still not done:**
- Live speed control: the session protocol has pause, resume and reset only. Needs a new client message from the simulation
  agent (logged under Requests); the UI shows the control disabled and says why.
- The map mode cannot draw roll, pitch or a water surface (the scene Pose has neither); it says so on screen.
- Bearer tokens cover REST and job polling only; WebSocket and EventSource cannot carry headers, so an authenticated
  deployment needs a trusted gateway.
- Live frames are still legacy, so live tugs, lines and environment stay "unavailable" until the simulator publishes
  `rm0-v1` frames and a scene.
- Full accessibility audit (contrast, screen-reader pass) and a profile of the React render path with real 10 Hz frames in
  a browser; only the adapter and mapper cost is measured.

**Left unmerged on purpose:** the branch `ui/frontend-updates` has not been merged into `dev`, as asked.
