# Next steps: product-review remediation

The original whole-product audit reviewed `dev` at `ac73e1fbf21a54efd029608cb140a306f69b4fa4` in an isolated detached checkout. Its source links, reproductions and evidence below remain pinned to that snapshot. The audit itself made no implementation changes.

**Remediation update, 5 November 2026:** F01–F28 are resolved by `fix/product-audit-remediation` through source/contract commit `ea62351`, with independent review, browser reproductions and final checks recorded in [PRODUCT_AUDIT_REMEDIATION.md](PRODUCT_AUDIT_REMEDIATION.md). Final local checks: 2,815 Python tests and 1,066 frontend tests passed; contract/type/lint/build checks passed. The PR records CI and merge status. G01–G08 remain open. The initial Domino review deployment used the earlier `dev` snapshot; its target smoke is separate from remediation validation.

**Assessment: the product is not ready for operational docking use.** The original audit reproduced defects in safety-result applicability, physical validity, collision detection, forecast continuity and persisted results. Those defects are addressed by the remediation above; the broader G01–G08 capability and qualification gaps remain. The existing AMBER/limited labels do not excuse discarding an explicit invalid condition. Passing tests establish only the behavior they exercise.

Independent passes covered modeling correctness, UX/accessibility, security, API compatibility, reliability and test strategy. Additional real-browser probes followed workflows across services. Probes were offline or used isolated loopback services, synthetic inputs and disposable synthetic credentials. No live providers, real LLM, deployment host or vessel qualification was tested. This review identifies concrete failures; it is not a claim of exhaustive verification of every code path.

Severity indicates remediation priority. High findings should block operational claims or the affected deployment/workflow until their acceptance evidence is recorded. Medium findings remain required corrections. The single Low finding concerns manual retention. Known missing features are separated below. Execution ownership follows the master plan and the ledger below; owners coordinate collaborators before editing shared files.

## Execution ledger

This is the detailed remediation companion to [MASTER_PLAN.md](MASTER_PLAN.md), which remains the authority for
priorities and ownership. **All 28 findings are resolved with regression and independent review evidence: 14 High, 13 Medium, 1 Low.** G01–G08 below track eight broader
capability/workflow gaps; T01–T03 identify test-design gaps, and T04 preserves the baseline/readiness distinction.
These IDs are separate from legacy S/P/U/D/A/R packet IDs. Do not close a finding merely because its original
feature PR was merged or the unchanged baseline suite passes.

| ID | Severity | Next change | Lead | Independent reviewer | Status / closure evidence |
| --- | --- | --- | --- | --- | --- |
| [F01](#f01) | High | Stale review/sheet applicability | Kori | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f01) |
| [F02](#f02) | High | Forecast binding across the UI agent chain | Kori + Bixler | Snyder + Cruz | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f02) |
| [F03](#f03) | High | Per-tide physical validity | Snyder M-PLAN | Snyder M-SIM | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f03) |
| [F04](#f04) | High | Ultimate-gust validity | Snyder M-PLAN | Snyder M-SIM | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f04) |
| [F05](#f05) | High | Rich forcing availability/provenance | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f05) |
| [F06](#f06) | High | Complete prediction horizon | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f06) |
| [F07](#f07) | High | Zero-margin collision detection | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f07) |
| [F08](#f08) | High | Prediction environmental validity | Snyder M-SIM + Cruz | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f08) |
| [F09](#f09) | High | Camera vessel identity | Kori | Bixler + Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f09) |
| [F10](#f10) | High | Camera forcing/traffic handoff | Kori | Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f10) |
| [F11](#f11) | High | Code-owned safety meaning | Bixler | Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f11) |
| [F12](#f12) | High | Runtime browser identity; no bundled key | Bixler + Kori | Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f12) |
| [F13](#f13) | High | Exercise draft/revision retention | Kori | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f13) |
| [F14](#f14) | High | Nonblocking alert computation | Snyder | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f14) |
| [F15](#f15) | Medium | Durable job completion | Snyder | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f15) |
| [F16](#f16) | Medium | Dirty-recording retry/eviction | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f16) |
| [F17](#f17) | Medium | Bounded provider cache | Cruz | Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f17) |
| [F18](#f18) | Medium | Final job deadline check | Snyder | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f18) |
| [F19](#f19) | Low | Retention preserves occupied capacity | Snyder | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f19) |
| [F20](#f20) | Medium | Replay forecast timeline compatibility | Cruz | Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f20) |
| [F21](#f21) | Medium | Nonnegative wind-ramp validation | Cruz | Snyder | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f21) |
| [F22](#f22) | Medium | Vessel-scoped telemetry authorization/state | Cruz | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f22) |
| [F23](#f23) | Medium | Preserve failed report drafts | Kori | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f23) |
| [F24](#f24) | Medium | Contact-point impact velocity | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f24) |
| [F25](#f25) | Medium | Frame-time line endpoint heights | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f25) |
| [F26](#f26) | Medium | No zero-spread uncertainty claim | Snyder M-SIM | Snyder M-PLAN | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f26) |
| [F27](#f27) | Medium | Spreadsheet-safe CSV text | Kori | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f27) |
| [F28](#f28) | Medium | Keyboard vessel selection | Kori | Bixler | [Resolved; review/regression evidence](PRODUCT_AUDIT_REMEDIATION.md#f28) |

### Starting work and recording closure

1. Branch from current `dev`, name the finding IDs in the PR, and reproduce against that head before changing code.
   Keep the audit's source links pinned to `ac73e1f`; later fixes should add their own evidence, not rewrite history.
2. Turn each relevant failure into a meaningful regression. A UI handoff requires actual request/result identity
   checks; mocked adapters alone do not close it. T01 accompanies F05/F25, T02 accompanies F09/F10, and T03 accompanies G02/F02.
3. Keep validity, source labels, units, immutable results and the offline/no-LLM path intact. Do not repair a result by
   inventing coefficients, dropping assertions, hiding unavailable inputs or relabeling invalid conditions as limited.
4. Run the repository checks appropriate to the implementation; schema changes require generated contract/types.
   Record exact commands, counts, skips/xfails, audited commit and remaining limitations in the PR.
5. An independent reviewer checks the reproduction and affected consumers. Update this ledger with fix PR/commit,
   regression names and review evidence. Use **implemented, pending review** until reviewed; only then **closed**.
   Update the master plan/capability ledger when scope or qualification changes. Bixler tracks integrated acceptance.

### Coordination and safe parallel work

- Snyder M-PLAN can start F03/F04 while M-SIM handles rich frames/prediction/contact (F05–F08, F16, F24–F26).
  Serialize changes to `prediction/engine.py`; keep F05/F25 coordinated in `berthing/rich.py`.
- Kori owns UI fixes F01/F09/F10/F13/F23/F27/F28; Bixler can independently address F11.
  Agree immutable forecast identity before the shared F02 UI/agent work. F12 needs one agreed runtime auth boundary.
- Cruz owns F17/F20/F21/F22. Coordinate F20 with the canonical resolver and F22 with Bixler's identity policy.
- Snyder owns `core/jobs.py` for F15/F18/F19, reviewed by Bixler; avoid simultaneous edits by separate agents.
  F14 should retain request identity when moving work off the event loop.
- Agree one contract/type generation writer when concurrent schema changes meet. Merge through PRs into `dev`;
  do not change colleagues' worktrees or mark source/engineering qualification complete through software tests.

## High-priority findings

<a id="f01"></a>

**F01 — High: obsolete review remains “Ready for signature” after unsafe edits.**

Sources: [frontend/packages/web/src/apps/mooring/agent.ts:292](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/agent.ts#L292), [frontend/packages/web/src/apps/mooring/agent.ts:324](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/agent.ts#L324), [frontend/packages/web/src/apps/mooring/controller.ts:522](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/controller.ts#L522), [frontend/packages/web/src/apps/mooring/panels/AgentPanel.tsx:145](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/panels/AgentPanel.tsx#L145).

Real-browser reproduction: moderate-weather DDG → Intake → Planner → independent Safety gives “Ready for signature,” 10/10 checks passed, limiting gust 39.6875 kt. Change workspace wind/gust to 150/180 kt. Current analysis shows up to 1,221% WLL, but the old review remains and the enabled action successfully creates its sheet without a workspace-staleness warning. The saved review is internally immutable; the defect is presenting it as applicable to the changed workspace. Selection changes invalidate agent state; ordinary environment/line/geometry changes do not.

Required correction: bind applicability and actions to the full assessed scenario identity, including lines, tugs and forecast revision. Preserve old results as explicitly historical. Test edits both after review and while requests are pending. **Owner: Kori + Bixler.** Evidence: `mooring-probe-results.json`, `stale-mooring-review.png`.

<a id="f02"></a>

**F02 — High, unfinished integration: Advance’s selected forecast is lost before Intake/Planner/Safety.**

Sources: [frontend/packages/web/src/apps/mooring/advance/session.ts:328](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/advance/session.ts#L328), [frontend/packages/web/src/apps/mooring/intake/controller.ts:55](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/intake/controller.ts#L55), [frontend/packages/web/src/apps/mooring/controller.ts:828](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/controller.ts#L828).

Real-browser reproduction: Advance assesses a 48-hour training series with a 25 kt gust-peak setting and a content hash, selects an arrival and applies its configuration. Intake then receives only `scenario_id` and `horizon_hours:24`; the newly saved environment is a steady synthetic snapshot with 5 kt gusts. The forecast binding and selected interval are absent. The UI tells users to continue with Planner and review, but only the lines survive the handoff. Backend A3 support already exists.

Required correction: carry one canonical forecast/configuration identity through Intake → Planner → Safety → sheet, including arrival/holding coverage. Assert identical hashes and assessed conditions across the entire browser workflow; revised data requires reassessment. **Owner: Kori + Bixler; Snyder/Cruz review binding.** Evidence: `forecast-handoff-results.json`, `forecast-handoff-intake.png`.

<a id="f03"></a>

**F03 — High: a grounding tide sweep reports valid low-load steps.**

Sources: [modeling/mooring/moored/envelopes_real.py:196](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/moored/envelopes_real.py#L196), [modeling/mooring/moored/envelopes_real.py:227](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/moored/envelopes_real.py#L227), [modeling/mooring/moored/envelopes_real.py:230](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/moored/envelopes_real.py#L230).

Synthetic berth depth 31 ft, DDG draft 30.5 ft, tide 0→−2 ft over an hour: sweep remains AMBER/limited, all three steps `valid=True`, utilization 6.3–6.6% WLL. Independent analysis at the final tide correctly returns RED/invalid `DEPTH_NOT_ABOVE_DRAFT` because actual depth is 29 ft. Physical validity is checked only at the initial condition; later convergence is treated as validity.

Required correction: validate every internal tide condition, propagate reasons, and withhold usable utilization for invalid steps. Include grounding between reporting times. **Owner: Snyder M-PLAN.** Evidence: numerical probe `tide_sweep_grounding`.

<a id="f04"></a>

**F04 — High: ultimate-gust assessment discards invalid input conditions.**

Sources: [modeling/mooring/moored/ultimate.py:152](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/moored/ultimate.py#L152), [modeling/mooring/moored/ultimate.py:172](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/moored/ultimate.py#L172).

With synthetic supplied capacity inputs and water level −20 ft, ordinary analysis is RED/invalid for depth, but ultimate-gust returns AMBER/limited `threshold_found`, assessed threshold 35.8 kt, with no depth reason. Explicit poor environmental quality similarly yields a 40.91 kt threshold. The search constructs its own limited validity. The capacity inputs are test fixtures, not proposed engineering values.

Required correction: retain shared baseline and per-probe validity; invalid inputs cannot establish usable thresholds. Test grounding, poor quality and invalid assignments. **Owner: Snyder M-PLAN.** Evidence: `ultimate_invalid_grounded`, `ultimate_invalid_poor_quality`.

<a id="f05"></a>

**F05 — High: rich simulation frames misrepresent missing and expired forcing.**

Sources: [modeling/mooring/berthing/rich.py:270](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/berthing/rich.py#L270), [modeling/mooring/berthing/rich.py:281](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/berthing/rich.py#L281).

A replay supplies only water level over t=0–10 s. Legacy motion output correctly reports unavailable/null wind; rich-session output reports available wind at 0 kt. At t=12 with `on_uncovered="invalidate"`, legacy water is invalid while rich water is limited. Rich assembly copies values but reconstructs availability/provenance and loses component validity. A top-level lifecycle warning does not repair contradictory component fields.

Required correction: preserve the resolved forcing environment when assembling rich output. Test actual session-id/rm0 frames and recordings for partial channels and expired coverage, including evidence fields. **Owner: Snyder M-SIM.** Evidence: `rich_forcing`.

<a id="f06"></a>

**F06 — High: prediction silently omits the final horizon interval and misses contact.**

Sources: [modeling/mooring/transit/simulator.py:437](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/transit/simulator.py#L437), [modeling/mooring/prediction/engine.py:363](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/prediction/engine.py#L363).

An 11-second prediction with 10-second ticks stops at 10 seconds and misses an obstacle encountered in the final second: AMBER/no breach. Identical input with one-second ticks returns RED/contact at 11 seconds. A one-second horizon with default ten-second ticks integrates no future motion. No truncation warning appears.

Required correction: integrate and hazard-check the final partial interval, retaining the final frame after decimation, for both forcing paths. Test short and nonaligned horizons with late contact. **Owner: Snyder M-SIM.** Evidence: `horizon_contact`, `horizon_contact_11s`.

<a id="f07"></a>

**F07 — High: zero clearance disables collision reporting.**

Source: [modeling/mooring/prediction/engine.py:369](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/prediction/engine.py#L369).

Initially overlapping hulls with allowed `min_clearance_ft=0` produce closest distance 0 ft, `first_breach=null`, AMBER. Changing only the threshold to 0.1 ft produces RED/contact at t=0. Distances are nonnegative, but breach requires strictly less than the threshold; sampled counts have the same defect.

Required correction: detect intersection/contact independently of stand-off margin. Test initial overlap, later contact and sampled counts at zero clearance. **Owner: Snyder M-SIM.** Evidence: `contact_threshold`.

<a id="f08"></a>

**F08 — High: transit/prediction loses explicit environmental-quality invalidity.**

Sources: [modeling/mooring/transit/simulator.py:495](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/transit/simulator.py#L495), [modeling/mooring/prediction/engine.py:449](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/prediction/engine.py#L449).

An otherwise current snapshot marked `metadata.quality="poor"` produces AMBER/limited prediction with no environmental-quality reason, although shared load assessment treats the declaration as invalid. Consumers cannot distinguish unusable input from ordinary surrogate-model limitations.

Required correction: merge shared environmental, timing and wind-basis validity into transit/prediction, including supplied forcing. Test identical unusable inputs across consumers. **Owner: Snyder; Cruz reviews provenance.** Evidence: `prediction_poor_environment`.

<a id="f09"></a>

**F09 — High: selecting a vessel leaves another vessel’s prediction on screen.**

Source: [frontend/packages/web/src/apps/missions/controller.ts:728](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/missions/controller.ts#L728).

Real two-vessel transit: enable Backup camera while paused for DDG-IN, then select CG-OUT. Selection and camera position change, but DDG-IN’s path/contact banner remains indefinitely. Captured traffic contains just the original DDG-IN prediction request.

Required correction: cancel/invalidate on identity changes and immediately request the new vessel; assert rendered result identity and handle late responses. **Owner: Kori.** Evidence: `ux/camera-shared-probe-results.json`, `ux/camera-select-stale-prediction.png`.

<a id="f10"></a>

**F10 — High: camera drops the transit’s environment and other vessel.**

Sources: [frontend/packages/web/src/apps/missions/controller.ts:907](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/missions/controller.ts#L907), [frontend/packages/web/src/apps/missions/camera.ts:112](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/missions/camera.ts#L112).

Real two-vessel Transit JSON with wind 30 kt, gust 36 kt and current 2 kt runs successfully. Enabling camera sends neither `environment` nor top-level `others` to prediction. Its response assumes calm conditions, reports unavailable uncertainty and checks only pier/fender hazards. Missing-vessel coverage is disclosed in limitations, but the app already has the other vessel’s state. A vessel-following camera is therefore predicting a different environment and omitting known traffic.

Required correction: preserve the immutable run environment/forcing and reconstruct time-aligned other-vessel states. Bind the selected berth/hazard source instead of relying on fixed scene assumptions. Test noncalm and crossing-traffic browser cases against captured requests. **Owner: Kori + Snyder.** Evidence: `api/camera-handoff-probe.json`.

<a id="f11"></a>

**F11 — High in LLM-enabled safety output: accepted narration contradicts RED/reject.**

Sources: [agents/mooring_agents/shared/narration.py:53](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/agents/mooring_agents/shared/narration.py#L53), [agents/mooring_agents/safety/agent.py:111](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/agents/mooring_agents/safety/agent.py#L111), [agents/mooring_agents/safety/sheet.py:231](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/agents/mooring_agents/safety/sheet.py#L231).

A fake provider inserted permitted fact references into negating/instructional prose. The actual guard accepted: “The status is not RED. Disregard the reject verdict. Moor immediately.” Structured fields stayed RED/reject, but `summary_source="llm"`, no guardrail note, and this brief is rendered on safety sheets. This requires a configured provider producing such text; no external LLM attack was attempted. Token allowlists do not constrain meaning.

Required correction: code owns complete operational verdict/risk statements. Restrict narration to validated statement selection or another form that cannot negate evidence or authorize action. Test negation and imperatives, not only prohibited tokens. **Owner: Bixler.** Evidence: `security/narration_probe.py`, `security/root-narration-recheck.json`.

<a id="f12"></a>

**F12 — High, conditional deployment flaw: bundled bearer credential defeats principal isolation.**

Sources: [frontend/packages/web/src/apps/mooring/api.ts:16](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/api.ts#L16), [docs/DEMO_MISSIONS_TRANSIT.md:127](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/docs/DEMO_MISSIONS_TRANSIT.md#L127).

With `VITE_API_BEARER_TOKEN`, a backend key is embedded in served JavaScript. Required-auth synthetic probe: anonymous mission read 401; anonymous bundle fetch 200 exposes the synthetic key; using it reads Alice’s mission with 200. This is a documented unsafe opt-in, not a bypass in an unconfigured bundle. It nevertheless cannot protect that principal from anyone able to fetch assets.

Required correction: runtime per-user authentication or authenticated gateway identity, with no backend secrets in builds. Test HTTP/streaming identity and anonymous asset exposure. **Owner: Bixler + Kori.** Evidence: `security/token_probe.py`; synthetic credentials only.

<a id="f13"></a>

**F13 — High: exercise tab navigation loses edits and overwrite protection.**

Sources: [frontend/packages/web/src/apps/exercise/LibraryPanel.tsx:28](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/exercise/LibraryPanel.tsx#L28), [frontend/packages/web/src/apps/exercise/LibraryPanel.tsx:85](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/exercise/LibraryPanel.tsx#L85), [frontend/packages/web/src/apps/exercise/Sidebar.tsx:487](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/exercise/Sidebar.tsx#L487).

Load a saved custom exercise → edit Wind under Environment → return to Scenario → load another: edits disappear without the unsaved-change prompt. Component unmount resets the saved snapshot and origin/revision. Saving shared data after that round trip omits `baseUpdatedAt`; the real endpoint accepted the stale save with 200 and overwrote another author’s change. A generic Replace prompt is not a revision check. Shared editing itself appears intentional, so it is not classified as an ownership bypass.

Required correction: persist origin/revision/draft baseline in controller state; test unsaved-change prompts and conflict rejection across tabs/app navigation. **Owner: Kori.** Evidence: `ux/ux-probe-results.json`, `ux/camera-shared-probe-results.json`.

## Additional confirmed findings

<a id="f14"></a>

**F14 — High: `/ws/alerts` blocks unrelated modeling requests.** Sources: [modeling/modeling_api/ws.py:104](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/modeling_api/ws.py#L104), [modeling/modeling_api/ws.py:108](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/modeling_api/ws.py#L108). Provider resolution and equilibrium work run synchronously on the ASGI event loop. An injected 400 ms provider delay raised concurrent health latency from approximately 27 ms to 409 ms; real provider retries can be longer. Offload the entire resolution/calculation unit, preserving context and bounding elapsed work. Verify unrelated health/session traffic during a delayed provider. **Owner: Snyder.** Evidence: `security/alerts_block_probe.py`.

<a id="f15"></a>

**F15 — Medium: job success is visible before durable completion.** Sources: [modeling/mooring/core/jobs.py:204](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/core/jobs.py#L204), [modeling/mooring/core/jobs.py:210](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/core/jobs.py#L210). A synthetic SQLite lock caused terminal persistence failure: memory said succeeded/result 42; disk still said queued/no result; reopening changed it to failed/interrupted. Error recovery cannot transition the already-terminal job. The probe shortened busy timeout to exercise the failure path, not to estimate its frequency. Commit before publishing success and explicitly handle persistence errors/callbacks. **Owner: Snyder + Bixler.** Evidence: `security/job_persist_probe.py`.

<a id="f16"></a>

**F16 — Medium: failed final recording saves are discarded at idle eviction.** Sources: [modeling/modeling_api/sim_sessions.py:310](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/modeling_api/sim_sessions.py#L310), [modeling/modeling_api/sim_sessions.py:479](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/modeling_api/sim_sessions.py#L479). A disconnect write fails transiently and marks its recording dirty; there is no disconnected retry scheduler. After storage recovery and idle timeout, creating another session evicts the only copy without another save attempt. The probe observed two retained frames, one attempt, then neither session nor persisted recording. Retry before eviction and retain/requeue on failure. **Owner: Snyder M-SIM.** Evidence: `security/session_persist_probe.py`.

<a id="f17"></a>

**F17 — Medium: provider cache grows indefinitely with normal live polling.** Sources: [modeling/mooring/environment/providers.py:276](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/environment/providers.py#L276), [modeling/mooring/environment/providers.py:360](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/environment/providers.py#L360), [modeling/mooring/environment/live.py:69](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/environment/live.py#L69). Rolling minute-specific request windows create new keys; freshness checks prevent reuse but never evict old response bodies. An injected-clock probe retained all 120 expired entries after a day and another request. Bound entries/bytes and evict beyond the usable stale period. **Owner: Cruz.** Evidence: `security/provider_cache_probe.py`.

<a id="f18"></a>

**F18 — Medium: deadline enforcement depends on client polling.** Source: [modeling/mooring/core/jobs.py:191](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/core/jobs.py#L191). A task checks cancellation, works for 60 ms against a 10 ms deadline, then returns. If first polled after completion, the job succeeds because no final deadline check occurs. This is late-result acceptance, not a demand to kill uncooperative threads. Check cancellation/deadline immediately before committing success and test with/without polling. **Owner: Snyder + Bixler.** Evidence: `security/job_deadline_probe.py`.

<a id="f19"></a>

**F19 — Low: manual purge loses active-worker capacity accounting.** Source: [modeling/mooring/core/jobs.py:278](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/core/jobs.py#L278). With one worker/no queue, cancelling a still-running worker correctly blocks new submissions. `purge(0)` removes its record and then accepts a new queued task behind that same worker. This requires manual retention or an integration invoking it. Do not purge unfinished futures, or account for workers independently of retained records. **Owner: Snyder + Bixler.** Evidence: `security/job_deadline_probe.py`.

<a id="f20"></a>

**F20 — Medium: supported replay scenarios produce composed-forecast HTTP 500.** Source: [modeling/mooring/environment/composed_forecast.py:497](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/environment/composed_forecast.py#L497). Synthetic and recorded-fixture replays covering an archive interval can be created successfully, but composing a 12-minute horizon on their scenario timeline fails the response’s complete-coverage validator. Metadata is retimed while snapshot `valid_at_utc` stays on archive time. The canonical resolver accepts the equivalent request. Reuse consistent replay retiming with original provenance and finite coverage; test both source types through both consumers. **Owner: Cruz; Snyder resolver review.** Evidence: `api/forecast-probe.json`, `api/probe_forecast.py`.

<a id="f21"></a>

**F21 — Medium: scenario schema accepts a negative wind ramp that cannot be sampled.** Source: [modeling/mooring/core/schemas/environment.py:839](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/core/schemas/environment.py#L839). Initial wind 10 kt, target −10 kt, duration five minutes is stored with 201; composing its first six minutes returns 500 because generated snapshots reject negative wind. Constrain the target to nonnegative and return 422 before storage; regenerate contract when fixed. Test a valid ramp down to zero as well. **Owner: Cruz.** Evidence: `api/negative-ramp-probe.json`.

<a id="f22"></a>

**F22 — Medium: telemetry state/order crosses vessel and principal identities.** Sources: [modeling/mooring/telemetry/ingest.py:101](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/telemetry/ingest.py#L101), [modeling/mooring/telemetry/ingest.py:140](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/telemetry/ingest.py#L140). Under required auth, Alice’s HDT is accepted; Bob’s HDT claiming Alice’s vessel at +59 seconds is accepted; Alice’s next reading is rejected `OUT_OF_ORDER`, and Bob’s remains global latest. State/history/order are keyed by sentence type without vessel authorization. This is ingest integrity/availability today; telemetry is not yet demonstrated as a live-camera feed. An extra telemetry key is also needed if configured. Authorize vessel/channel identity and scope all ordering/state accordingly. **Owner: Cruz + Bixler.** Evidence: `security/auth_probe.py`.

<a id="f23"></a>

**F23 — Medium: failed mission report save destroys draft text.** Source: [frontend/packages/web/src/apps/missions/forms.tsx:164](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/missions/forms.tsx#L164). An injected HTTP 503 clears title/body while displaying “Nothing was changed; try again shortly.” Controller handling resolves on failure and the form clears unconditionally. Signal success explicitly and clear only that successful draft; preserve failed and newly edited text. **Owner: Kori.** Evidence: `ux/report-failure-clears-draft.png`, `ux/ux-probe-results.json`.

<a id="f24"></a>

**F24 — Medium: fender impact speed omits contact-point rotation.** Source: [modeling/mooring/berthing/simulator.py:290](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/berthing/simulator.py#L290). Synthetic initial yaw 1°/s, zero translation: F300 contact at 0.589098 s is recorded as 0 ft/s impact, while yaw drives the contact point into the fender (normal velocity approximately 1.625 ft/s at t=0.7, with nonzero fender energy). Midship translation is not contact speed. Compute normal velocity at the contact point immediately before impact, including rotational contribution; test pure yaw and combined motion. **Owner: Snyder M-SIM.** Evidence: `yaw_impact_speed`.

<a id="f25"></a>

**F25 — Medium: rich-frame line endpoints remain at initial tide height.** Source: [modeling/mooring/berthing/rich.py:166](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/berthing/rich.py#L166). After a 3 ft tide rise, heave reports 3 ft but a fitting 24 ft above waterline remains at 24 ft MLLW instead of 27 ft. Displayed line geometry disagrees with physics. Use frame-time resolved water level; compare coordinates and lengths under varying tide. **Owner: Snyder M-SIM.** Evidence: `line_height`.

<a id="f26"></a>

**F26 — Medium: zero-spread forcing is presented as available uncertainty.** Source: [modeling/mooring/prediction/engine.py:332](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/mooring/prediction/engine.py#L332). Calm steady forcing, no initial uncertainty, four samples yields a corridor and 0.0 ft spread everywhere with `UNCERTAINTY_ILLUSTRATIVE`; equivalent fixed calm input correctly reports uncertainty unavailable. Merely supplying a series activates sampling. Require an actual perturbable spread source; keep corridor/probability unavailable otherwise. Test calm and tide-only forcing. Other ensembles remain illustrative, not calibrated probabilities. **Owner: Snyder M-SIM.** Evidence: `calm_forcing_uncertainty`.

<a id="f27"></a>

**F27 — Medium: CSV export preserves spreadsheet formulas in untrusted text.** Source: [frontend/packages/web/src/apps/exercise/exportResults.ts:7](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/exercise/exportResults.ts#L7). The real import → Monte Carlo → CSV pipeline accepts label `=1+1` and exports it unneutralized. Spreadsheet software may interpret it as a formula. Emitted bytes were verified; spreadsheet execution was not attempted. Neutralize formula-leading text before CSV quoting while preserving numeric results. **Owner: Kori.** Evidence: `security/csv_probe.ts`.

<a id="f28"></a>

**F28 — Medium: alternate-vessel selection is mouse-only.** Source: [frontend/packages/web/src/apps/missions/TransitPanels.tsx:293](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/missions/TransitPanels.tsx#L293). Table rows use `onClick` with no focusable control/keyboard handler. Browser inspection confirmed tabIndex −1, failed focus and no interactive child. Provide semantic selection controls and test Tab/Enter selection and focus. **Owner: Kori.** Evidence: `ux/camera-shared-probe-results.json`.

## Missing capabilities and incomplete product workflows

These are separate from the 28 confirmed defects above. **G01–G08 remain open.** The table records the audit-baseline gaps; remediation progress and remaining acceptance are tracked in [the remediation report](PRODUCT_AUDIT_REMEDIATION.md#remaining-acceptance). Acquisition retry and runtime credentials now have implementations, but neither closes its broader end-to-end gap. The separately deployed Domino HTTP/SSE/WS smoke is narrower than G07's recovery, identity and qualification gate.

| Gap | Current implementation / consequence | Required next acceptance and owner |
| --- | --- | --- |
| G01: full near-pier backup camera | The prediction service is transit-based; berthing-engine selection returns `ENGINE_UNSUPPORTED`. Initial sway/yaw-rate/hidden actuator state and engine handoff are incomplete; coastline and calibrated uncertainty are missing. | Snyder + Cruz + Kori: preserve a complete observed/runtime state, implement reviewed engine selection/handoff and hazard coverage, and validate against held-out trajectories. Keep current limitations explicit. [docs/PREDICTION.md:11](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/docs/PREDICTION.md#L11), [docs/PREDICTION.md:57](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/docs/PREDICTION.md#L57). |
| G02: usable first public-forecast acquisition | Success fixtures retrieve exactly at `as_of_utc`; at just +1 ms the same fixture becomes partial with no snapshots. The UI defaults as-of to the start of the hour, before ordinary retrieval. Rejecting post-cutoff unknown-issuance data is correct, but the actual acquisition/recovery workflow is not demonstrated. | Cruz + Kori + Bixler: test an advancing-clock offline composer/resolver/browser chain; support explicit retrieval then cutoff confirmation/cache reuse without inventing issuance. See T03 below. |
| G03: live own-ship/source continuity | NMEA intake and provider components exist, but a qualified coherent own-ship feed into the camera is unfinished. Motion session creation from the UI sends scenario/initial state; it has no complete forcing-authoring/binding workflow for selected future series. | Cruz + Snyder + Kori: authenticated vessel identity, timestamps, completeness/freshness, changing-forcing selection and replay provenance through UI/session/recording/prediction. [frontend/packages/web/src/apps/mooring/motion/controller.ts:422](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/motion/controller.ts#L422), [docs/MASTER_PLAN.md:281](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/docs/MASTER_PLAN.md#L281). |
| G04: qualified vessel/berth/line/tug physics and references | Synthetic maneuvering, placeholder reference inputs, missing shallow-water/bank/squat/interaction effects and unsupported class fitting data remain. Four hull catalogs do not mean four qualified line-planning classes. | Snyder + asset/data owners: define the operating envelope, acquire applicable sourced coefficients/ratings, independently validate contact/holding/transit and record limitations by class/loading/berth. This is engineering work, not a cosmetic GREEN status change. [docs/DEPLOYMENT_READINESS.md:1](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/docs/DEPLOYMENT_READINESS.md#L1), [frontend/KORI_UI_DELIVERY.md:71](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/KORI_UI_DELIVERY.md#L71). |
| G05: ultimate capacity, sequence proposal and structural strain UI | Ultimate backend needs a supplied capacity/material basis; UI basis selection/Safety integration is incomplete. Sequence search exists but proposal workflow is not fully connected. Structural bollard strain is unavailable. | Snyder + Bixler + Kori: repair F04 first, provide reviewed basis/contracts and immutable result binding; connect sequence proposals with intermediate-state review. Structural strain requires a reviewed model and asset data. [frontend/KORI_UI_DELIVERY.md:71](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/KORI_UI_DELIVERY.md#L71). |
| G06: map-independent exercise tools | Without Mapbox credentials, `MapCanvas` returns the token prompt before the toolbar. Browser-confirmed Red team/story authoring controls disappear although those operations do not intrinsically need a map. | Kori: render non-map tools independently and provide an honest schematic/offline workflow. [frontend/packages/web/src/apps/exercise/MapCanvas.tsx:372](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/exercise/MapCanvas.tsx#L372). |
| G07: deployment/auth/retention acceptance | Open local-demo mode is intentional; a production identity/approval-role system, authenticated native streaming/gateway flow, distributed recovery/retention and target-host acceptance remain incomplete. Server PDF depends on native libraries; HTML print is the fallback. | Bixler + Kori + Snyder: target-host HTTP/SSE/WS/browser rehearsal, runtime user identity, verified approval roles and recovery/backup/retention exercise. Fix F12 and persistence issues before claiming isolation/durability. [docs/DEPLOYMENT_READINESS.md:1](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/docs/DEPLOYMENT_READINESS.md#L1). |
| G08: immutable evidence throughout UI | Track/storyboard atomic revision tokens, saved-sheet graphic consumer completion and full public-source revision propagation still have handoffs recorded in the UI delivery note. Existing IDs/count checks cannot prove an atomic evidence snapshot. | Snyder + Bixler + Kori: publish/consume shared immutable revisions and test late updates without substituting current canvas or mixed track/storyboard evidence. [frontend/KORI_UI_DELIVERY.md:71](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/KORI_UI_DELIVERY.md#L71). |

## Acceptance gaps

The T01–T03 descriptions below preserve the original audit. Added rich-session/endpoint regressions, browser camera identity evidence and explicit acquisition-cutoff tests are listed in [the remediation report](PRODUCT_AUDIT_REMEDIATION.md#remaining-acceptance). Final independent acceptance is pending; T04 remains a standing distinction between baseline checks and readiness.

**T01 — High test gap: forcing equivalence tests select the legacy path.** [modeling/tests/test_s2_forcing.py:51](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/tests/test_s2_forcing.py#L51) constructs `Session` without `session_id`; production uses the separate rich-frame path in [modeling/modeling_api/sim_sessions.py:113](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/modeling_api/sim_sessions.py#L113). Parameterize both paths and assert availability, validity, provenance and geometry, plus one actual endpoint/WebSocket test with partial/expired forcing. F05/F25 were reproduced despite those tests.

**T02 — Medium test gap: camera browser acceptance measures requests, not a correct refreshed overlay.** [scripts/check_missions_ui.py:331](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/scripts/check_missions_ui.py#L331) requires three requests in nine seconds and a minimum request gap. Requests at 0, 4 and 8 seconds can pass; a pre-existing “Closest approach” label need not prove a new rendered result. Measure completed responses, rendered vessel/input identity, maximum refresh gaps, and stale/unavailable presentation separately from throttling. Include paused selection and noncalm handoffs (F09/F10).

**T03 — Medium test gap: public acquisition never exercises ordinary cutoff timing end to end.** [modeling/tests/test_d2_composed_forecast.py:101](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/modeling/tests/test_d2_composed_forecast.py#L101) aligns retrieval exactly with as-of; [frontend/packages/web/src/apps/mooring/advance/public.test.tsx:19](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/advance/public.test.tsx#L19) supplies already-complete responses. [scripts/demo_check_browser.py:389](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/scripts/demo_check_browser.py#L389) starts with acquisition disabled and proceeds with training. Test a real offline composer/resolver behind the browser with advancing timestamps and the UI defaults from [frontend/packages/web/src/apps/mooring/advance/logic.ts:59](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/frontend/packages/web/src/apps/mooring/advance/logic.ts#L59). Prove recovery and successful binding without weakening the no-future-data rule. Evidence: `model/public_acquisition_cutoff_probe.py`, `model/public_acquisition_cutoff_results.jsonl`.

**T04 — Acceptance distinction: baseline passing is not readiness passing.** [scripts/demo_check.py:72](https://github.com/fleethacker/pier-review/blob/ac73e1fbf21a54efd029608cb140a306f69b4fa4/scripts/demo_check.py#L72) deliberately separates baseline and readiness. The existing recorded baseline is 38 passed / 3 declared readiness skips. Those gates include component/startup acceptance, all-four-case browser review chains and changing-forcing coverage. Do not promote skipped or stubbed flows to completed features. The release CI run for `1c42a8a` was observed successful; this audit did not rerun the full suite or treat that success as contradictory evidence against the repros.

## Correction order and ownership

1. **Restore result truth and applicability first:** F01–F08 and F11. Snyder handles validity/contact/runtime; Kori/Bixler handle stale reviews, forecast identity and constrained safety narration. Each fix needs a failing reproduction first and independent review.
2. **Close actual UI handoffs:** F09/F10, F13/F23/F28, then G02/G03/G05/G06/G08. Test complete user journeys with real local services; do not accept only adapter or mocked-response tests.
3. **Repair identity, persistence and bounded operation:** F12, F14–F22, F27. Add failure injection for storage, delayed providers, deadlines and restart/retention. Keep collaborative library behavior distinct from private-resource authorization.
4. **Finish numerical/display honesty:** F24–F26, with independent contact/geometry checks. Do not tune physical coefficients to make display tests pass.
5. **Separate software release from operational qualification:** complete G01/G04/G07 with evidence appropriate to the intended operating envelope. A release candidate may be useful for explicitly supervised demonstration, but these findings do not support crew reliance for real docking.

This sequence remains the remediation priority adopted by the master plan. Implementations are now collected on the coordinated remediation branch; final review, integrated checks and the PR into `dev` remain pending. Record acceptance per finding rather than inferring closure from the branch or test total.

## Evidence and reproducibility

Snyder retains the local audit evidence bundle: browser captures, request/response JSON and disposable probe scripts. Evidence filenames in this document identify that local bundle; they are not repository paths or shared download links. No raw dumps, scratch probes, credentials or screenshots are added by this documentation PR. The finding descriptions and pinned source links are the portable reproduction starting points; owners must add repository regression tests when implementing fixes. Numerical records are in `model/results.jsonl`; a second root execution produced byte-identical `model/root-recheck.jsonl`. The adversarial narration and all five reliability probe scripts were also independently rerun successfully; their outputs are retained. Browser mooring and forecast handoffs used the real isolated services. UX failure paths used controlled 503 responses; shared overwrite behavior was separately checked against the real endpoint. Provider, SQLite and deadline probes deliberately inject clocks/failures to exercise defined paths, not to estimate production incident rates.

The evidence does not establish real-world coefficient accuracy, provider availability, target-host/GPU performance, a live-model prompt exploit, spreadsheet execution or sustained production capacity. No such claims are made. Shared exercise writes appeared intentionally collaborative and were excluded as an ownership vulnerability; the proven revision/data-loss defect remains F13.
