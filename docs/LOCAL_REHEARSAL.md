# Local rehearsal: 5 November 2026

Validated the Bixler changes on `agents/a0-bixler-integration`, based on `dev` at `282c046`, on macOS arm64 with
Python 3.12.13 and Node 22.17.0. Runtime used `AGENTS_LLM_PROVIDER=none` and `MOORING_ENV_SOURCE=mock`.
Dependencies came from lockfiles; the actual launcher rehearsal used populated local caches and offline package
settings. No Domino deployment or clean-`main` release rehearsal was performed, as requested.

| Check | Result |
| --- | --- |
| Full Python suite (`pytest -q`) | 1,769 passed; no skips |
| Contract export (`scripts/export_contract.py --check`) | Up to date; no contract changes |
| UI typecheck, lint, unit tests, production build | Passed; 227 unit tests |
| Launcher syntax / ShellCheck | Passed |
| Launcher regression cases, included in Python total | 14 passed: runtime exits, readiness failure, SIGINT/SIGTERM during bootstrap and service execution |
| Isolated baseline API/proxy run | 14 passed, 0 failed; browser and six unimplemented acceptance requirements explicitly excluded |
| Actual `app.sh` plus headless Chromium | 27 API/browser checks passed, no browser errors |
| Strict readiness profile | Exit 1: six outstanding requirements reported; not release-ready |

The API checks completed all four Intake → Planner SSE → independent Safety review → HTML sheet chains. They
preserved initial and final outcomes, selected review identity and approve/reject decisions. The initially
underconstrained input stayed RED/invalid in its saved result while search produced a separate AMBER/limited plan.
Synthetic advance planning retained its seed/source labels, installation tide and paid-out lengths; uncovered
arrivals stayed unavailable. WebSocket resume, tug command, pause and reset worked through the UI proxy.

The browser exercised the supported planning path, Intake binding, sheet/print controls, source labels, motion
fixture playback and live controls, unit toggle, vision confirmation and the initial analysis of all four cases.
HTML printing was exercised through the browser controls; native server PDF rendering was not part of this run.
The launcher shut down its service processes after SIGINT.

The six open readiness checks are live rm0 frames; S1 scene/recording/speed/reconnect coverage; D1 component
availability and source selection; P1/A3 revision handoff; U1/U4 complete browser planning/review/advance stories;
and S2/U5 simulation-time forcing. They remain explicit failures in the readiness profile. The baseline does not
silently count authored recordings or supplied synthetic forecasts as those capabilities.

## Reproduce locally

Install the locked dependencies, run the Python/UI checks, then launch in one terminal:

```bash
AGENTS_LLM_PROVIDER=none MOORING_ENV_SOURCE=mock \
PORT=48888 MODELING_PORT=48000 AGENTS_PORT=48001 ./app.sh
```

With Playwright and its Chromium installed, use another terminal:

```bash
DEMO_CHECK_SCREEN_DIR=/tmp/pier-review-screens \
uv run --all-packages --with playwright python scripts/demo_check.py \
  --base-url http://127.0.0.1:48888/ --profile readiness --browser-timeout 600
```

The target mode creates demonstration records in the local app. The expected readiness failures above are separate
from a failing implemented flow. Stop `app.sh` with Ctrl-C after the run. Use `make demo-check` for a fresh isolated
baseline stack, or `make demo-check DEMO_CHECK_ARGS=--no-browser` for the explicitly scoped CI path.

## Presentation images

These screenshots come from that local browser run; they are not rendered mockups.

| Image | What it demonstrates |
| --- | --- |
| [Workspace](screenshots/2026-11-05/workspace.png) | Seed-data banner and AMBER/limited supported case |
| [Safety sheet](screenshots/2026-11-05/safety-sheet.png) | Printed independent-review ID, assessed conditions and qualification limits |
| [Motion replay](screenshots/2026-11-05/motion-replay.png) | Authored rm0 fixture with explicit mock/unavailable labels; not live rm0 evidence |
