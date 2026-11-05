# Agent 2: modeling and agents (`agents/` plus the physics, planning and readiness side of `modeling/`)

Read [README.md](README.md) (shared rules, do-not-stop, degradation ladder, acceptance gate) first. Worktree: `../psp-agents`,
branch `agents/overnight`. Log: `docs/overnight/modeling-agents.md`.

**You own** `agents/` and, in `modeling/`: `mooring/core`, `loads`, `mechanics`, `moored`, `tugs`, `rules`, `refdata`,
`qualification.py`, `templates.py`, `examples.py`, results/jobs, the optimizer and sequence code, `modeling_api/` routers for
those, and `docs/` for them. **Agent C owns** `modeling/mooring/environment`, `telemetry`, `approach`, `berthing`,
`modeling_api/ws.py` and `sim_sessions.py`. If you need a change there, append to `docs/overnight/data-sim.md` `## Requests`.

## What exists

Real: UFC loads, equilibrium, limiting wind and tide sweep, tug allocation, holding plans and windows, line-plan search,
sequence generation, risk sampling (unqualified uncertainty artifact), persistent results and jobs, qualification and
`/capabilities`. Agents: Intake, Planner and Safety are real deterministic loops with optional guarded LLM narration; Safety
sheet renders HTML/PDF; **Vision (Berth Map) is a mock** that returns the seed Pier 12 berth. The agents service still uses an
in-memory legacy job path. See `docs/MODELING_BUILDOUT_STATUS.md` for every packet's gaps. Baseline: 1107 tests pass and
1 fails: `test_architecture.py::test_old_mock_modules_for_replaced_capabilities_are_gone`.

## Work, in priority order

### M0. Baseline (first 30 minutes)
Fix the failing test: `modeling/mooring/moored/mock/` is an **untracked stale directory** (only `__pycache__`; nothing tracked
there). Delete it (`git ls-files` to confirm), confirm the test passes, and also make the test independent of stale bytecode
dirs if easy. Run `make test`, `make contract-check`; fix anything else. Tell the others in `## Interfaces` when `dev` is green.

### M1. A supported-safe demo path (gate item 2: the most important backend item)
The real equilibrium shows the template plan overloaded at the design condition, so the demo currently shows RED for everything.
Produce, with real modeling and honest labels:
1. **a scenario that ends in an acceptable plan** (for example DDG 51 at Pier 12 North, calm-to-moderate conditions where
   the physics truly supports it, found with the line-plan search plus tug allocation; carrier/other classes if cheap),
   `limited` because the data is seed data;
2. an **overloaded (RED)** scenario (design storm, where tugs or lines cannot hold);
3. an **invalid-data** scenario and 4. an **undetermined** scenario (the S14 cases already tested in `test_s14_phase1_chain.py`).
Publish them as named scenarios/example requests (`modeling/mooring/scenarios.py` / `examples.py`, regenerated contract examples)
and list their IDs in `## Interfaces` for the UI and the e2e check. Do not tune physics constants to force GREEN; choose
conditions and plans. If the real result will not go GREEN for any seed-data plan, an AMBER/limited accepted plan is fine,
labeled.

### M2. Planner agent that actually finds a plan (gate item 2)
The planner loop must, offline and deterministically: use S12 search and S08/S09 tug allocation through the Physics toolkit,
iterate toward `target_margin_pct_wll`, stop by code rules (budget, no improvement), cite `result_id`s for every number, emit SSE
`step`/`proposal`/`done` events, and report "no safe plan exists" with the governing element when true. Check it on the M1
scenarios. Include tug-assisted conditions (S12 notes "Tug-assisted conditions not searched"; add them, and let ranking
consider risk if cheap). Keep API shapes (additive changes only).

### M3. Intake and Safety on real inputs
- Intake: must handle the real environment endpoints (agent C: `coops`/`replay`/`auto`), including 503/stale/partial snapshots
  (current stale, forecast missing, waves unavailable) by reporting `data_quality` findings, never inventing values.
- Safety: independent review on the M1 results, gust warnings (SSE), thresholds, verdict `ready_for_signature`/`revise`/`reject`
  correct for the four scenarios. Sheet: HTML and PDF render, approvals lock on first approval, every number cited, `limited`
  validity and "seed data" prominently stated on the sheet. Test the no-LLM path and the guarded-LLM path (fake LLM).
- Do the agents' persistence and job path properly if time allows (S02 results in modeling are persistent; agents' jobs are
  in-memory). At minimum make restarts not corrupt anything and document the limit.

### M4. Berth Map (vision) agent, real (gate item 5)
Replace the mock with the pipeline in `agents/mooring_agents/vision/README.md`: deterministic geometry first (berth data from
`scripts/build_berths.py` and the OSM-derived real piers already in `refdata`, plus any chart geometry agent C publishes),
fittings snapped to the pier face, unknown capacities from NSTM Table 582-5-6 defaults marked `estimated`, `needs_confirmation`
on low-confidence items, `recommend_config` through the Physics toolkit. A vision-LLM extraction step only when an LLM is
configured; **without one, return a deterministic draft from the supplied metadata (lat/lon, berth id, scale) and say so in
the response**. Confirm endpoint creates a real berth in modeling (the runtime `add_berth` path) that the UI can then select and
analyze. Test with a fixture image and a fake LLM response.

### M5. LLM provider options
`agents/mooring_agents/shared/llm.py` supports only an OpenAI provider. Add an Anthropic Messages provider (env
`AGENTS_LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, `AGENTS_LLM_MODEL`; use the `claude-api` skill for current model IDs and
parameters) behind the same interface, with the same guards (numbers must come from cited results). Unit-test with a fake
transport. No network in tests. Default stays `none`.

### M6. Remaining modeling items that affect the product
Do the ones that move the demo, in this order, each with tests and honest status:
1. S03: UFC wind-duration/height conversions beyond 60 s to 30 s and 10 m, or keep them reported `limited` if a primary source
   is not at hand (do not invent factors).
2. S13 sequence: rule table coverage and validation endpoint behavior on real plans; durations flagged unreviewed.
3. S10 consumption: when agent C refits the uncertainty artifact (365+ days), wire the new artifact's provenance and
   qualification status through risk results; keep unqualified unless the policy is truly met.
4. S14 performance: measure the Phase 1 chain end to end, record numbers in `docs/MODELING_BUILDOUT_STATUS.md`.
5. S21: agents authentication integration (opt-in), request limits on the agents service, retention docs. Do not turn auth on
   by default.
6. S06/S07/S08 gaps that cause wrong or confusing outputs in the demo (read the status ledger's "What is not done" column).

### M7. Data request list (DC8, docs only)
Write `docs/DATA_REQUESTS.md`: for each thing that has no public feed and must not be invented (real pier fitting/fender layouts
and ratings, per-class fitting positions and loading drafts, line strength/stretch data sheets, tug fleet ratings, ship
mass/inertia/added-mass/maneuvering coefficients, fender force-deflection curves, wake/traffic feed): what is needed, format,
which module is blocked, who plausibly holds it.

### M8. Hardening (then keep going)
Randomized/property tests on the chain; contract drift; run the agents against modeling under load (concurrent plans, the
429/queue behavior); error paths (modeling down, job timeout); documentation: README status tables, `agents/*/README.md`
status lines, `docs/MODELING_BUILDOUT_STATUS.md` ledger kept truthful. A "REVIEW_NEEDED" section in your log listing every
rule table, coefficient or assumption a subject-matter expert must review tomorrow.

## Interfaces you depend on / publish

- Depend on agent C: `/env/*` behavior and source modes, forecast, uncertainty artifact, wave/sim endpoints (only if the Safety
  agent uses them; do not block on them).
- Publish to UI and C (in `## Interfaces`, within 45 minutes then kept current): scenario IDs and example requests from M1,
  agent endpoint changes, contract changes, the `dev`-is-green announcement.

## Done means

Gate items 2 and 5 pass through the UI on `dev` (you do not edit the UI; verify with the API flow and `make demo-check`), the four
scenario outcomes are demonstrable, the agents run with no LLM, `make test` is green with no skips you added, contract is
regenerated, final report written.

## Advance forecast expansion (user request, 4 November evening)

Execute [the expanded overnight modeling plan](../docs/MODELING_OVERNIGHT_PLAN.md) alongside M0–M8. It includes the existing-UI coverage audit, at-least-24-hour advance arrival planning with coverage past docking, explicit forecast provenance/gaps, reusable data_simulation generators, and cross-agent integration watches.
