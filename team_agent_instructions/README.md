# Overnight agent instructions: shared rules (read first)

Written 4 November 2026 for `dev` at `5ce65d8`. Three agents work in parallel tonight. Each has its own file:

| Agent | File | Owns |
| --- | --- | --- |
| **UI** | [01-ui.md](01-ui.md) | `frontend/` |
| **Modeling and agents** | [02-modeling-and-agents.md](02-modeling-and-agents.md) | `agents/`, and in `modeling/` the physics, planning, rules, results and readiness code |
| **Data connections and simulation** | [03-data-and-simulation.md](03-data-and-simulation.md) | in `modeling/`: `environment/`, `telemetry/`, `approach/`, `berthing/`, `ws.py`, `sim_sessions.py`, and `scripts/` for data |

Read this file, then your own file, then `README.md`, `CONTRIBUTING.md`, `docs/PLAN.md`, `docs/MODELING_EXECUTION_PLAN.md`,
`docs/MODELING_BUILDOUT_STATUS.md`, `docs/MOTION_FRAME_DESIGN.md` and the other file's "Interfaces" section for any
agent you depend on.

## The mission

**A working product at 08:00 EST on 5 November 2026 (13:00 UTC).** Check the clock yourself with
`TZ=America/New_York date`; do not trust your sense of elapsed time. "Working" is defined by the
[acceptance gate](#acceptance-gate-the-product-at-0800) below, not by your own file's checklist.

## Do not stop

There is **no human awake tonight.** Nobody will answer questions, approve a PR or unblock you. Therefore:

1. **Do not end your turn, ask a question, or hand back "next steps" before 08:00 EST.** If you finish your list, start your
   file's hardening list, then re-read the acceptance gate and test it harder. Stop only at 08:00, after your final report.
2. **Every problem is yours to solve.** Failing test, missing dependency, flaky network, a provider that is down, a
   design question, an ambiguous spec, a merge conflict, a broken `dev` someone else caused: fix it, work around it, or
   route around it. Never stop and wait on it, and never ask the human.
3. **Use the degradation ladder**, in order, with a timebox of about 45 minutes per blocking problem (30 for UI polish):
   1. the best solution (correct, sourced, tested);
   2. the same approach with narrower scope (one ship class, one berth, one provider);
   3. a simpler or synthetic approach that is **clearly labeled** (`limited`, `synthetic`, `unavailable`, `mock` in the data,
      the API, and the UI);
   4. an explicit "unavailable" state that keeps every other part of the product working.

   Moving down the ladder is expected and fine. Moving down **silently** is not: write what you gave up and why in your
   log (below) so it is corrected tomorrow. A lesser solution that ships beats a perfect one that does not.
4. **Never block the whole pipeline on one item.** If an item is stuck at rung 4, mark it, move on, and come back if time allows.
5. Run long commands in the background with timeouts; do not sit on one. Commit and push at every green step so a crash or
   a context reset loses at most minutes. Keep your log current: after a context reset, your log and `git log` are your memory.

## Honesty rules (these do not bend, even at 7:55 am)

- Never fabricate data to make something green. A provider failure is `unavailable` or `limited` with a reason, not a
  plausible number. Recorded real fixtures are fine and are labeled `replay`.
- Seed and demo data stay labeled. Every real result with seed data is `limited`; do not remove the label to make a demo
  prettier. Do not claim validation, qualification or subject-matter review that did not happen.
- Do not delete, skip, weaken or `xfail` a test to get green. Fix the code. If a test encodes a wrong expectation, change it
  with a one-line justification in the commit message.
- Physics stays in `modeling/`. Agents never do arithmetic on physics numbers and never import physics code (see `agents/README.md`).
- No secrets in the repo. There may be no LLM key tonight: everything must run and demo with `AGENTS_LLM_PROVIDER=none`
  (deterministic behavior). LLM narration is an optional extra, never a dependency.
- Tests never touch the network. Live checks are opt-in smoke scripts.

## Decisions already made (so nobody waits for the human)

These replace every "ask the human" item in older docs. Record any new decision you make in your log under "Decisions".

- Target is **"demonstration within documented assumptions."** Qualified results for a specific ship and pier are out of reach tonight.
- Waves: use the DC4-approved order (NDBC 44099 observations, GFS-Wave forecast; see `docs/DC4_WAVE_SOURCE_INVESTIGATION.md`).
  Wave response of the ship is a **labeled synthetic surrogate**. Wake is `unavailable`, never zero. Tug wash is out of scope.
- 3D view is wanted, best effort, after the 2D view works. Vertical motion: tide-following heave plus quasi-static heel
  (RM4 options a and b). Dynamic roll/pitch is "not simulated" and flagged as such in frames.
- Tugs are scripted or commanded through the session; no autonomous tug controller.
- Live telemetry is out of scope for the demo. Provider default stays offline-safe (see C-agent file for the `auto` fallback).
- Units: Navy/Metric toggle already exists in the UI; the API keeps its current units.

## Git workflow tonight (this overrides CONTRIBUTING.md where they differ)

- Work in **your own git worktree**, never in another agent's: `git worktree add ../psp-<area> -b <area>/overnight origin/dev`
  with `<area>` = `ui`, `agents` (for agent B) or `ws-e` (for agent C). Never edit files in another agent's worktree.
- Integrate **often, in small pieces**: at least every 60 to 90 minutes, and after every completed item. Flow:
  `git fetch && git merge origin/dev`, run your checks, push your branch, then merge into `dev`:
  `gh pr create --base dev --fill` followed by `gh pr merge --merge` (no human review is available tonight; self-merge
  is authorized for green PRs). If `gh` fails, fall back to `git push origin HEAD:refs/heads/dev` only as a fast-forward after a
  fresh merge of `origin/dev`. Never force-push. Never touch `main`. Never delete branches you do not own.
- **`dev` must always be green**: `make test` passes, `npm run typecheck && npm run lint && npm test && npm run build` pass in
  `frontend/packages/web`, and `make mock` starts. If you break `dev`, fix forward immediately or revert your merge. If you
  find it broken by someone else, tell them in their log's "Requests" section and fix it yourself if they have not within
  15 minutes.
- Stay inside your ownership. Cross-boundary change is allowed only when small, additive, and logged in the other agent's
  inbox (see "Contract and cross-agent protocol").
- Commit messages end with the attribution line the harness gives you.

## Contract and cross-agent protocol

- `contract/` is generated. Change a schema additively (new optional fields, new endpoints), then run `make contract` and
  commit the regenerated files with the change. If you hit a merge conflict inside `contract/`, take either side and rerun
  `make contract`. Never hand-edit it. The UI agent regenerates its types with `npm run types`.
- **Per-agent files in `docs/overnight/`** (create yours on first commit; never edit another agent's file except to append to its
  `## Requests` section):
  - `docs/overnight/ui.md`, `docs/overnight/modeling-agents.md`, `docs/overnight/data-sim.md`
  - Sections: `## Log` (timestamped, short: what you did, what broke, what you gave up), `## Decisions`,
    `## Interfaces` (what you publish for others: endpoints, fixtures, env variables), `## Requests` (inbox: what
    others need from you, newest first), `## Tomorrow` (suboptimal solutions and deferred work).
  - Read the other two files at every integration point and act on your inbox.
- Prefer publishing an **interface with fixtures first**, implementation second, so others unblock early. Example frames
  and recordings under `contract/examples/` are the UI's source of truth until live data exists.
- Do not wait for a dependency. Build against the published fixture or a labeled stub, and swap in the real one when it lands.

## Acceptance gate: the product at 08:00

All of this must work on `dev`, from a clean checkout, with no network and no LLM key (live providers are a bonus):

1. `make install && make mock` starts modeling (:8000) and agents (:8001); `app.sh` builds and serves the UI on :8888 with
   both proxied, including WebSockets. `make test` passes (currently 1107 pass, 1 failing from a stale directory; see agent B).
2. **Phase 1 flow, in the browser:** choose a berth on the map, place the ship, see analyzed colored lines; run the intake
   agent, then the planner (SSE steps visible), then the safety review, then the safety sheet; approve it and print it. At
   least one scenario ends in an acceptable plan (with `limited` validity labeled), and the overloaded (RED),
   invalid-data and undetermined cases show clearly and do not crash the UI.
3. **Motion flow, in the browser:** start a berthing session; watch the ship move live in the 2D map (and the 3D view if it
   exists) with environment (wind, gusts, current, tide, waves where available), tugs with kinematics, lines, fittings and
   fenders; issue tug and line commands; pause, resume, reset, change speed, and replay a recording. Validity and provenance
   badges are visible. Anything synthetic says so.
4. **Environment honesty:** the UI shows each data source's state (live, replay, mock, unavailable) and age. With the network
   down, the product still demos from recorded real data and says so.
5. **Berth vision:** upload an image, get a draft berth that needs confirmation, confirm it, and use it (deterministic
   fallback when no LLM is configured, labeled).
6. `make demo-check` (owned by the UI agent) runs the above against the running stack headlessly and passes. Anything it
   cannot cover is listed in the UI agent's final report.

Priority if time runs short: **(2) then (3) then (4) then (5)**; items beyond the gate are stretch.

## Timeline (EST)

| Time | Milestone |
| --- | --- |
| Start | Create worktree and your `docs/overnight/` file with the start time. Run the baseline checks. Publish your first Interfaces entry within the first 45 minutes. |
| Start + 2 h | Everyone has merged a first piece into `dev`. C has published rm0 frames plus the scene endpoint from the legacy simulator, so the UI can go live. |
| 02:00 | Phase 1 flow works end to end on `dev` (agent B). Motion flow works end to end with mock-quality physics (agent C and UI). |
| 04:00 | Gate items 2 and 3 pass on `dev`, perhaps roughly. From here, improve fidelity, never break the flow. |
| 06:00 | Gate items 4 and 5 pass. |
| **07:00** | **Feature freeze.** Merge your last feature. Only fixes, docs and verification after this. |
| 07:00 to 07:45 | UI agent runs `make demo-check` and fixes or routes blame; everyone fixes what it finds; all update the README status tables and `docs/` they touched. |
| 07:45 | Final reports: `docs/overnight/<yourfile>.md` `## Final report` (what works, what is labeled limited, what was given up, what to do tomorrow, exact commands to run the demo). Merge to `dev`. |
| 08:00 | Stop. |

If you are behind at 07:00, cut scope to the highest-priority gate items and make them solid.
