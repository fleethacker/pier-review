# Release review — integrated modeling, agents and UI

Reviewed on 5 November 2026 against `dev` at `62e754ec8921cc8311fd499d34c84cf28b03178c`
and `main` at `daf7e36`. The release diff contains the overnight modeling/data work,
the integrated UI and the data/simulation next-step plan. This review used an
isolated worktree; the colleagues' UI worktrees were not modified.

## Recommendation

Merge the release-review fixes before promoting `dev`. The reviewed `dev` was not
ready: its CI failed generated-type verification, and its new Intake display was
not connected to the selected scenario or Planner.

With these fixes and green CI, the result is suitable for a **demonstrator release**
into `main`. This is not approval for operational docking decisions or an exposed,
production deployment. The qualification and integration gaps in
[deployment readiness](DEPLOYMENT_READINESS.md) and the
[data/simulation next-step plan](../team_agent_instructions/04-data-simulation-next-steps.md)
remain applicable. The entire original overnight acceptance gate is not being
declared complete.

## Findings and fixes

| Priority | Finding at reviewed `dev` | Resolution |
| --- | --- | --- |
| P1 | `agents.d.ts` included `detector` in Intake/Planner narration enums, although the API only added it to vision extraction. Regeneration changed the file and failed CI. | Regenerated types from the checked-in contract; no schema change. |
| P1 | Intake submitted berth/ship/side rather than the selected scenario. Manual or saved conditions could differ from the displayed assessment, and Planner never received its report ID. | Intake resolves the same immutable scenario used by Planner and motion, stores the report in controller state, and passes `intake_report_id` to Planner. Manual conditions remain explicitly steady/synthetic. |
| P1 | An old Intake submission could use a newer request's abort signal and overwrite its result. Editing environment, loading or lines did not invalidate a displayed report. | Each operation owns its abort controller and input identity. Saving, submission, polling, progress and error callbacks discard stale work; changes invalidate the report. |
| P1 | A generated plan or recommendation could still be applied after an environment edit because applicability checked geometry only. | Environment is part of the applicability identity; edits during scenario saving also prevent plan submission. |
| P1 | Motion displays exposed invalid/unknown frame or component loads, and mapped a taut line to GREEN without a capacity assessment. | Withhold unusable load values and load statuses while retaining geometry, alerts and validity reasons. Taut lines use a neutral cyan state color, not a safety status. |
| P2 | Browser checks only established that an Intake panel and planning result appeared; they did not verify the report/source handoff or four initial scenario outcomes. | Assert saved wind inputs, common scenario identity, report ID propagation, AMBER/limited supported plan and four initial analysis outcomes. Block external browser requests during the check. |
| P2 | CI ran for PRs into `dev`, but not release PRs into `main`. | Run the same checks on PRs and pushes to both branches. |

Focused regressions cover cancellation and late success/failure callbacks, edits
during scenario saving, source/report propagation, stale plan applicability,
invalid/missing component validity and neutral motion line rendering. The legacy
frame test now expects unavailable force when validity is absent; this strengthens
the validity rule rather than allowing unknown numbers to appear usable.

## Verification

| Check | Evidence |
| --- | --- |
| Python suite / contract | `make contract-check` passed; `make test`: **1,736 passed**, no skips or xfails. Backend code was not changed by the fixes. |
| Frontend | Generated types reproduce without a diff; TypeScript, lint and production build pass. **227 tests passed**, no skips or xfails. |
| Real HTTP/WS/browser flow | **24 checks passed**, zero failures/skips on implementation commit `62e94ff`. `demo_check.py` started both services and the built UI on private loopback ports, using synthetic data and no LLM. All temporary services stopped. |
| Native PDF | With `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`, confirmed the native renderer was available and passed `test_safety_sheet_lifecycle`, including an actual PDF response. |
| Review source | The merged `dev` CI failure was independently reproduced locally and matched GitHub run `42039696517`. |
| Change hygiene | Generated types were regenerated, not hand-edited; no physical coefficients, backend schemas, seed data or contract artifacts were changed. |

The browser flow checks Intake → Planner, sheet approval/print controls, motion
recording/2D/3D/live pause/reset, unit switching, and berth image confirmation. The
four-case check covers saved initial analysis: supported AMBER/limited, overloaded
RED/limited, invalid depth RED/invalid, and underconstrained RED/invalid. It does
not assert that planning preserves an initial failure that a new configuration can
legitimately repair. Independent Safety review is exercised through the API and
sheet creation; a separate review-selection UI is still absent.

The harness uses a 120-second agent tool timeout for headless WebGL CPU contention;
the product default remains 30 seconds. This is functional integration evidence,
not a latency, throughput or long-soak guarantee. The earlier overnight soak ran
on an earlier revision and is not attributed to this release candidate.

The final browser run used `uv run --all-packages --with playwright python
scripts/demo_check.py --skip-build` after the successful production build, with
installed Chrome selected through `DEMO_CHECK_BROWSER_EXECUTABLE`. Logs and
screenshots were written outside the checkout. The subsequent commit adds only
this review document.

## Dependency and deployment review

`npm audit --omit=dev` reported **zero production dependency findings**. The full
audit reported **13 development dependency findings: 2 critical, 1 high and 10
moderate**, including Vitest, Tinypool, nested Vite and minimatch paths. They are
not fixed by this PR. Do not describe the full dependency audit as clean.

Examples include [Vitest's UI-server advisory](https://github.com/advisories/GHSA-5xrq-8626-4rwp)
and [Tinypool's worker-options advisory](https://github.com/advisories/GHSA-85c8-ppgw-ccpr).
Upgrade the test toolchain in a dedicated compatibility-tested follow-up; do not
use `npm audit fix --force`, which proposes unrelated major changes/downgrades.
The acceptance run uses `vitest run`, not an exposed Vitest UI server. Keep CI and
test tooling restricted to trusted code and do not publish development/test
servers as part of the demonstration. The audit is an advisory snapshot, not a
comprehensive security assessment of all Python and JavaScript dependencies.

Open local-demo authentication, native browser SSE/WS authentication limits,
single-process storage/session behavior and retention/capacity limits remain as
documented. `VITE_API_BEARER_TOKEN` is embedded in the browser bundle and does not
provide per-user identity; it is not a production credential design. The hosted
Domino entry point exposes the UI/proxy port and needs the host's access controls.

## Scope still deferred

- Public NWS/CBOFS readers are not a composed, qualified docking forecast. Manual
  steady snapshots and synthetic replay are labeled demonstrations, not public
  forecasts or recorded real observations.
- Berthing uses surrogate vessel dynamics and legacy runtime frames. Rich replay
  fixtures do not establish live tug kinematics, vertical response or wave loads.
  Playback speed is not a live simulation-speed control.
- Seed geometry, ratings and vessel data remain unqualified. Invalid results must
  remain visibly unusable, and limited results cannot become operational clearance.
- Full four-case Intake/Planner/review/sheet browser chains, explicit independent
  review selection and production authentication/provider integration need follow-up.
- Optional trained detector/LLM paths and external NOAA availability were not
  qualified by the offline demo run.

## Release sequence

1. Review and merge the release-readiness PR into `dev`; verify its CI and the
   subsequent `dev` CI. If `dev` changes, review the delta before using this evidence.
2. Open the release PR **from `dev` into `main`**, with demonstrator scope and the
   qualification limits above. The added CI trigger validates that PR as well.
3. Obtain the approval required by [CONTRIBUTING.md](../CONTRIBUTING.md), then use a
   merge commit so `main` retains the integrated history. Do not squash the release
   or push directly to `main`.

This review does not merge or tag `main`.
