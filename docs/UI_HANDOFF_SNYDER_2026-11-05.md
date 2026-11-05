# Note for the UI (Kori) agent: modeling changes landing in dev

Source: PR #22 (`ws-e/snyder-demo-sprint` -> `dev`, Snyder modeling lane) plus PR #13 (D1-D4, already on `dev`).
After you merge `dev`: run `npm run types` (contract changed; CI fails on `git diff --exit-code -- src/api`).
Nothing below changes existing request/response shapes: every change is additive and omitted from the wire when unset.

## A. PR #22 (modeling) - what you can now consume

1. **S2 simulation-time forcing** (U5 depends on this)
   - `POST /berthing/sessions` and the batch sim request accept optional `forcing` (`ForcingSpec`: kind steady | ramp | gusts | replay; replay carries `samples[]` with `t_s`, wind_speed_kt, wind_gust_kt, wind_from_true_deg, current_speed_kt, current_set_true_deg, water_level_mllw_ft; a channel is given in every sample or in none).
   - `SimSessionCreated` gains `forcing_revision` and `forcing_synthetic`. `SimFrame` / rm0 frames carry `forcing_revision`; show it beside sim time vs wall time. `forcing_synthetic=true` must show a persistent "synthetic / training" badge.
   - A channel the series does not supply is **unavailable in the frame (values absent), not zero**. Render "unavailable".
   - Run ends with reason `FORCING_UNCOVERED` (RED) when sim time leaves the series coverage (policy `stop`, default) or is marked invalid (`invalidate`). Surface this reason in the session status.
2. **S3 vertical/tug wiring** (U7 depends on this)
   - rm0 pose `heave_mllw_ft` is populated only when a forcing series supplies `water_level_mllw_ft`; the heave DOF is then `prescribed`. Otherwise heave is null and DOF `not_simulated`. Roll/pitch stay `not_simulated`; tug position stays null ("not modeled"). Do not draw roll/pitch or tug kinematics from these.
3. **New endpoints** (each with a typed response; all validity `limited`/unqualified, show it)
   - `POST /api/v1/tugs/horsepower-plan` (P5): minimum-horsepower tug assignment `HorsepowerPlan` with placements, margins, `infeasibility_reasons`.
   - `POST /api/v1/risk/ultimate-gust` (P6): without `capacity_basis` returns **200 with `outcome: "unavailable"`** (reason `ULTIMATE_CAPACITY_BASIS_MISSING`). Never present it as "safe". No sourced capacity data exists yet, so for the demo this is the common path; real thresholds only with a supplied basis. Keep WLL 80%/100% warnings distinct from ultimate margins.
   - `POST /api/v1/loads/wave-surrogate` (S4): seeded synthetic wave series, label "SYNTHETIC / UNQUALIFIED, not berth forcing". `state: "unavailable"` means no series (do not draw zero waves).
   - `POST /api/v1/mooring/sequence/search` (S8, U11): proposals with `outcome` feasible_static | indeterminate | infeasible, constraint checks, `bounds.truncated`, `review_status: draft_unreviewed`. Show intermediate-state results and the draft label.
4. **S7 prediction honesty changes** (U8 camera overlay)
   - New validity reasons: `HAZARD_COVERAGE_UNKNOWN` (no hazard layer checked: this is NOT an all-clear), `HAZARD_COVERAGE_INCOMPLETE` (lists unchecked kinds), `OTHER_VESSEL_PATH_SHORT`, `UNCERTAINTY_UNAVAILABLE` (corridor null: show "uncertainty unavailable", never a zero-width band).
   - Swept-hull checks now also report contacts between output ticks and overlap at t=0.
   - Non-finite or >60 kt speeds are 422.
5. **S5/S6 fixes**: simulated-track events are now `limited` with `SIMULATED_TRACK`; truncated JPEG uploads return 422; GGA quality 0/6-8 rejected; duplicate fixes dropped at parse but still counted in `duplicates` (expect different counts than before).

## B. PR #13 (D1-D4, already on dev) - make sure the UI accounts for it

- `GET /api/v1/env/availability`: per-component state (live / replay / prediction / mock / unavailable), source, age, basis (U3). Misconfigured source mode now fails loudly at startup; `auto` = live -> labelled recorded replay -> explicit failure. Never label recorded replay as current conditions.
- `POST /api/v1/env/forecast/compose` (D2): `ComposedForecast` with `manifest` (revision, content hash, as-of, horizon <=120 h), per-component series (wind intervals, current/water-level points). A component may be unavailable while others exist (e.g. CO-OPS predictions only, wind unavailable). Drive U4's coverage/provenance preview and "recheck required" from `manifest` revision/hash. Keep paid-out lengths and installation tide when applying `selected_config`.
- `POST /api/v1/env/waves/compose` (D4): offshore waves only (NDBC 44099 / GFS-Wave). Totals, partitions and spectra are alternatives, never additive. Label "offshore, not berth forcing"; berth exposure is `unavailable`; wake `unavailable`. Do not feed these into load displays.
- Exercise/storyboard app (`apps/exercise`) landed with #21: unrelated to the above but share `types.ts`. On macOS, `Library.tsx`/`library.ts` and `Storyboard.tsx`/`storyboard.ts` collide on case-insensitive filesystems and break local typecheck/tests (106 local test failures); this is pre-existing on dev, CI (Linux) is unaffected. Consider renaming to avoid it.
- Replay package: recorded-real replay is separate from the synthetic `replay_sample.json`; the offline demo and `make demo-check` use it.

## C. Incoming from Snyder next (modeling adapters, not yet merged)
A composed-forecast -> S2 replay-forcing adapter and an offshore-wave -> S4 surrogate adapter are being written; they add no wire changes. When they land, a composed forecast can drive a live session via `forcing`, and `forcing_revision` will trace to the forecast manifest revision.

## D. Checklist for you
1. Merge `dev`, `npm run types`, typecheck/lint/test/build.
2. U5: show sim time, `forcing_revision`, synthetic/training badge, `FORCING_UNCOVERED`.
3. U3/U4: bind to `/env/availability` and `/env/forecast/compose` manifest; unavailable components render as unavailable.
4. U7: heave only when present; no roll/pitch/tug kinematics drawing.
5. U8: render the new S7 coverage/uncertainty reasons; never imply all-clear from missing layers.
6. U11: sequence-search proposals with draft/unreviewed label.
