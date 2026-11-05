# Release draft: integrated demonstrator

**Unreleased draft for A4.** Bixler owns release coordination; Kori supplies browser evidence, Snyder modeling/runtime evidence
and Cruz provider evidence. Assignments and reviewers are in [master plan ownership](MASTER_PLAN.md#execution-ownership).
This document is not a milestone tag or evidence that `main` is demo-ready.

## Changes merged into dev

Status checked 5 November 2026 at `3ababad`:

- P1 canonical forecast resolution (#4) and P2 explicit revision reassessment (#8), with immutable results and coverage gates.
- S1 rich rm0 frames, scenes, lifecycle/speed/reconnect and saved recordings (#6).
- Agent/demo/launcher/vision baseline improvements (#7) and the printable fielding brief (#9).
- Mission storyboarding and limited port-transit simulation (#10), followed by S6 fixes and the limited S7/U8 prediction service/overlay (#14). Review-finding closure still needs the evidence recorded in the master plan.
- Kori's U1–U7 UI workstream (#18): explicit review selection, live protocol integration, component status/error displays,
  advance planning/recheck, source clocks, toolchain upgrade and conditional 3D motion display.
- Requirements-remediation prompts R1–R9 (#12) and the backup-camera demo script (#16). Merged prompts are planned work,
  not implemented capabilities.

D1–D4 environmental provider work is implemented in **open PR #13**, under separate review. Include it in release notes
only after merge and combined validation. The erroneous UI merge into `main` (#15) was reverted by #17; #18 is the intended
integration into `dev`. A feature PR to `main` is not a substitute for the milestone release process.

## Qualification and coverage limits

Vessel, berth, fitting and rope inputs remain seed/demo data. AMBER/limited results are not operational mooring approval;
surrogate dynamics, risk artifacts, image-derived geometry and estimated capacities remain unqualified. Invalid results
withhold usable loads. Human approval fields are declarations, not verified organizational authority.

The camera currently uses transit dynamics with approximate initial-state handling, an illustrative uncertainty spread
and explicit missing hazard coverage; see [PREDICTION.md](PREDICTION.md). Berthing prediction, changing simulation-time
forcing and live own-ship state remain separate work. Wave-provider evidence does not establish qualified berth forcing.
Agent-wide forecast-revision binding (A3), the complete readiness/browser gate and target hosting rehearsal remain open.

Domino HTTP/SSE/WebSocket and HTML/PDF behavior must be recorded from the actual running app. Local launcher, browser
and unit-test evidence do not establish that deployment gate.

## Evidence required for a milestone release

Historical Bixler-branch evidence: 1,769 Python tests, 227 UI tests, contract/typecheck/lint/build and 27 API/browser checks
passed; six readiness requirements were uncovered. [Rehearsal details and screenshots](LOCAL_REHEARSAL.md) retain that scope.
PR #18 reports 365 frontend tests, typecheck/lint/build and zero audit findings on its branch. Neither count is a new
combined release-candidate result; no test or rehearsal was rerun for this documentation refresh.

Bixler records the merged `dev` commit, CI run, Python/UI checks, readiness output, clean-checkout target URL and rehearsal
result. List deferred features with visible labels and their responsible owners. After an approved merge-commit PR from
`dev` to `main`, record the resulting `main` commit and agreed tag here. Follow [CONTRIBUTING.md](../CONTRIBUTING.md#releasing-dev-into-main).
