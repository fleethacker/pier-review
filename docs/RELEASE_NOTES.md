# v0.2.0-rc.1 — integrated mooring demonstrator

Release candidate prepared 5 November 2026 from `dev` at `83e9498` (PR #27), for promotion to `main` through a
merge-commit release PR. The GitHub release records the resulting `main` commit and tag. This is a demonstrator
release candidate; it does not establish operational qualification or completion of the deployment readiness gate.

## Included

- Tabbed mooring, mission and exercise workspace; two-axis ship placement, fitting drag/reconnect, cancellation,
  keyboard alternatives and class/loading capability gates.
- Public environmental availability and composed forecast acquisition with source/basis/age and missing-data
  states. Advance docking plans bind immutable revisions/content hashes, cover docking and holding, and require
  reassessment when inputs change. Training is a separate labeled choice.
- Intake, Planner, independent Safety review and printable sheets retain canonical forecast bindings. Reviewed
  sheets include frozen assessed SVG geometry and reference identities, independent of subsequent canvas edits.
- Rich rm0 berthing frames, lifecycle, simulation-time forcing, speed control, reconnect and recordings. Motion
  displays retain forcing provenance, coverage-stop reasons and unavailable degrees of freedom.
- Tug horsepower planning, explicit-capacity ultimate-gust assessment, bounded static sequence search and seeded
  wave surrogates. Missing qualification or engineering inputs remain unavailable or limited.
- Limited trajectory prediction, mission evidence/playback, authenticated media/downloads, and corrected source,
  track, asynchronous-selection and cross-application gesture handling.
- NOAA observation/forecast and offshore-wave adapters with coverage/provenance checks. Offshore evidence does not
  establish berth applicability; public-source configuration remains deployment-specific.

See [the master plan](MASTER_PLAN.md), [Kori's UI handoff](../frontend/KORI_UI_DELIVERY.md),
[Bixler's implementation handoff](BIXLER_IMPLEMENTATION.md) and
[Snyder's UI handoff](UI_HANDOFF_SNYDER_2026-11-05.md) for detailed behavior and remaining owners.

## Validation

The release source tree matches the locally validated PR #27 head `dd1a0b4` exactly. Reconciliation with `main`
retains both histories and the validated `dev` implementation; it does not restore the superseded #15/#17 UI revert.
Release preparation changes only this document relative to that source tree.

- Full Python suite: **2,690 passed**, no skips or xfails.
- Frontend: **1,039 passed in 69 files**, no skips or xfails; generated types, typecheck, ESLint and production build passed.
- Generated contract check passed.
- Integrated baseline demo: **38 passed, 0 failed, 3 declared readiness gaps**.
- Canvas browser: **7 groups passed**, including both sides-to, real analysis requests, cancellation,
  creation/reconnection and unsupported-class gates.
- Authenticated mission browser: **11 passed**, zero failures/skips, including image decoding, download,
  bearer headers, object-URL cleanup and no URL-token leakage.

Checks used offline loopback services, no LLM, labeled synthetic inputs and Chromium software rendering on macOS.
Local Node 26 JSDOM tests use `NODE_OPTIONS=--no-experimental-webstorage`; CI uses Node 22. Target-host/GPU/browser
acceptance and live-provider rehearsal are separate evidence. CI was skipped during the time-boxed UI delivery;
local results must not be described as a green GitHub CI run. The earlier #25 frontend CI failure was the mocked-map
test's missing token setup, corrected in #27. Release PR and GitHub release notes record the current CI state.

## Open release-readiness checks

The readiness profile treats these uncovered requirements as failures; the baseline profile declares them as skips.
They are retained for this release candidate, not counted as passing tests:

1. Complete component-availability and startup-rejection acceptance against D1 — Cruz/Kori/Bixler.
2. Complete independent-review browser chains for all four planning cases — Kori/Bixler. The API chains, supported
   browser chain and initial-outcome browser checks are covered.
3. Changing simulation-time forcing and source labels over a full browser flow — Snyder/Kori/Bixler.

There is no new clean-checkout Domino/target-host rehearsal for this candidate. Bixler owns that gate and the
remaining combined acceptance evidence. Server PDF availability must be tested on the target; printable HTML is
supported when native libraries are absent.

## Qualification and remaining work

Vessel, berth, fitting and rope inputs remain seed/demo data. AMBER/limited is not operational mooring approval.
Surrogate dynamics, synthetic waves, image-derived geometry and estimated capacities remain unqualified. Missing
hazard coverage and absent uncertainty stay explicit; predictions are demonstrator decision support, not navigation.
Approval role/name fields do not verify organizational authority.

Approved additional-class and structural data, calibrated trajectory uncertainty, complete hazard/own-ship inputs,
ultimate-capacity basis UI, sequence-proposal UI and further public-forecast/agent selection integration remain open.
Authentication/gateway operation, persistence, concurrency and recovery must be rehearsed on the intended host;
see [deployment readiness](DEPLOYMENT_READINESS.md). Local success is not live-use acceptance.
