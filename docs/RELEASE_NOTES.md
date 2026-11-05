# Release draft: Bixler integration

**Unreleased.** This is a reviewable draft for A4, not a milestone tag or evidence that `main` is demo-ready. Release only after the master-plan milestone dependencies, approval, CI and target rehearsal pass.

## Changes prepared

- Repository instructions point to `fleethacker/pier-review` and explicitly target feature PRs at `dev`.
- Demo checks exercise all four Intake → Planner → independent review → HTML sheet chains, supplied training forecast planning and existing REST/SSE/WebSocket proxy behavior. CI retains logs and identifies the responsible workstream.
- The launcher requires a supported Node runtime, waits for both APIs and stops the app when a child service exits.
- Vision extraction rejects unusable proposals and preserves the catalog-fallback label; fixture-image tests use a fake LLM offline.

## Qualification and coverage limits

The vessel, berth, fitting and rope data remain seed/demo inputs. AMBER/limited results are not an operational mooring approval; synthetic dynamics, risk artifacts, image-derived geometry and estimated catalog capacities remain unqualified. Invalid results withhold usable loads. Human approval fields are declarations, not verified organizational authority.

The baseline uses explicitly labeled mock/training environment data. It does not establish live source coverage, physical accuracy or a composed public forecast. S1 live rm0 scenes/recordings/speed, D1 component availability and P1/D2 revision binding remain dependent on their owners. U1/U2/U4 browser acceptance remains separate. A successful baseline cannot satisfy `make demo-check-readiness` while these gates are open.

Domino HTTP/SSE/WebSocket and HTML/PDF behavior must be recorded from the actual running app. The local launcher and probe are preparation; no hosting rehearsal or milestone release is claimed here.

## Evidence required for a milestone release

Local branch evidence: 1,769 Python tests, 227 UI tests, contract/typecheck/lint/build and 27 API/browser checks
passed. Six readiness requirements remain uncovered. [Rehearsal details and screenshots](LOCAL_REHEARSAL.md) are
local evidence only; they do not satisfy the pending deployment/release gate.

Record the merged `dev` commit, CI run, Python and UI checks, readiness output, clean-checkout target URL and rehearsal result. List any deliberately deferred features with visible labels and the responsible owner. After an approved merge-commit PR from `dev` to `main`, record the resulting `main` commit and agreed tag here.
