# UI/modeling compatibility review — 5 November 2026

## Integration follow-up

The user subsequently authorized integrating **only** `ui/frontend-updates`; `frontend-exercise` is excluded.
The separate `agents/ui-integration` checkout preserves current dev fixes and resolves nullable vision boxes,
8,000,000-byte PNG/JPEG/WebP validation, uncalibrated confidence/source wording, stale motion snapshots,
input changes during session creation/scene loading, and changed initial offsets. Holding assistance and
plan-bound sheet-image behavior come from current dev. Merge conflicts preserve both Makefile targets and
all peer Requests. The earlier review below remains historical evidence.

The combined suite passes 1,734 Python tests and 191 UI tests, with contract/typecheck/lint/build checks.
The final scoped browser/API harness passed 20 checks with no failures/skips after correcting its validity lookup,
using the supported scenario, asserting explicit API Intake/review outcomes, using a working Chrome
configuration and supplying the missing favicon. The final scene-loading race fix has an additional unit
counterexample and is included in that browser run. A separate four-case initial-analysis browser check
also passes, including unavailable load displays for invalid cases.

Explicit Intake/review UI controls and the full four-case browser flow remain incomplete. A passing scoped
`make demo-check` must not be called completion of the whole overnight gate.

## Original held-branch review

UI branch: `ui/frontend-updates` at `6faddf0`. Its log explicitly asks to leave it unmerged; modeling has respected that
hold. Review used a separate local worktree, merged with `dev` at `edcc1ae`. No peer branch or worktree was changed.
This is an integration review, not an approval of the UI branch.

## Findings to resolve before integration

1. **Blocking vision type/runtime mismatch.** `BerthVisionPanel.tsx:166` destructures `bbox_px`, which can now be null
   when the backend has no measured image geometry. Skip the rectangle in that case, preserving the confirmation table
   and limitations. `vision/logic.test.ts:5` also needs `center_px: null` for the generated type. The wire field may be
   absent; consumers must handle that. Typecheck failed before these two local review fixes.
2. **Holding assistance differs from the assessed analysis.** `AgentSession.applyPlan` copies berthing
   `tug_plan.assignments` into holding reanalysis. Use `plan.holding_tugs`, including an explicit empty list. Berthing
   assistance is not the assistance used in the holding analysis. This mismatch was also reproduced in the earlier
   browser audit: map percentages differ from the same plan's sheet.
3. **Motion can reuse a stale scenario.** `controller.motion.ensureScenario` reuses `scenarioId`, but changes through
   `setEnv`, `setLoading`, `setShipX`, `setStandoff` and `setTugAssignments` do not invalidate that saved snapshot.
   `layoutKey` omits environment. Bind sessions to a full input signature and create a fresh snapshot when it changes.
   Test changes after loading/saving an existing scenario, not just initial session creation.
4. **Browser rendering failure.** Strict offline Chrome review reached the sheet, then Cesium reported
   `DeveloperError: Expected width to be greater than 0, actual value was 0` and stopped rendering. Its error modal
   blocked approval and subsequent motion/vision steps. Reproduced at 1600×1000, Ask agent → Create sheet. Root cause
   is not established; investigate framebuffer sizing/capture timing. Do not dismiss the modal and count the flow as green.
5. **Upload acceptance differs from the service.** UI accepts GIF and 12 MiB; the backend accepts PNG/JPEG/WebP and
   at most 8,000,000 bytes. Align validation and error text. Deterministic catalog drafts are not pixel extraction.
6. **Demo gate is incomplete.** The API demo-check plan completed RED. Saving and approving that sheet does not prove
   the supported-limited case. Exercise `/demo/docking-cases` and assert the four documented outcomes. Explicit intake
   and independent review remain missing from the UI flow; new forecast conditions must reach the planner.

## Evidence and review-only changes

- With only the null-box guard and detection fixture correction: typecheck, lint, **135 UI tests** and build pass.
- Demo check: **14 passed, 4 failed, 0 skipped**. API/proxy health, vision draft confirmation, planner SSE, sheet rendering/
  approval recording, and live motion pause/resume/reset pass. Browser startup, source panel, lines and planner pass;
  the rendering error blocks the remaining flow. Later motion/vision failures are downstream of that modal, not evidence
  of separate root causes.
- Browser used installed Chrome, blocked nonlocal requests, and saved screenshots outside git. These are review-only
  harness changes; no product assertion was removed or weakened. Logs: `/tmp/psp-ui-review-demo.log`; screenshots:
  `/tmp/psp-ui-review-screens/`. Local checkout: `/Users/michaelsnyder/repos/psp-ui-review`.
- Two integration conflicts were resolved locally: preserve both `demo-check` and `smoke-live` Makefile targets, and
  preserve the UI log plus modeling's Requests inbox. Generated contracts/types came from current dev.

Current interface suggestions are in [MODELING_UI_RECOMMENDATIONS.md](../MODELING_UI_RECOMMENDATIONS.md).
Findings were sent to the UI Requests inbox and directly to the UI branch's commit discussion. No acknowledgment is claimed.

## Follow-up capture experiment (23:48 EST)

In the isolated review checkout, removing the synchronous `viewer.render()` call from `store.capture` and reading the existing preserved canvas (with a zero-size guard) removed the reproducible render error. The browser/proxy run then reports **19 passed, 1 failed, 0 skipped**, with no browser errors. Sheet approval, motion and replay pass. This demonstrates a small mitigation; it does not establish every internal Cesium timing cause.

The remaining vision failure is the final harness expectation `BERTH DATA: VISION`: the backend returns a deterministic catalog draft with estimated provenance, and the banner correctly shows `ESTIMATED`. The screenshot shows the berth saved, selected and rendered. Align that assertion with returned provenance, and expose `extraction_source`/`extraction_note` rather than hard-coding the saved message as vision extraction. Detection confidence is a heuristic score, not calibrated probability; avoid “percent sure” wording.

The UI branch remains held. The experiment and earlier null-box/fixture corrections are local review changes, not merged UI features. Log: `/tmp/psp-ui-capture-experiment-browser.log`. A preliminary run without Playwright skipped the browser and is not counted as browser evidence.
