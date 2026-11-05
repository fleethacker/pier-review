# Demo walkthrough

A five-minute path through the demonstration: a supported **AMBER/limited** plan for a DDG 51 at a seed NAVSTA
pier, an explicitly independent safety review and the sheet built from it, advance arrival planning 24 h+ ahead, and
a live motion session.
The modeling and agent workflows are implemented; the reference data and surrogate motion remain unqualified.
Point out the seed-data and synthetic-source labels when presenting. This is not a completed G2 acceptance gate.

## Setup

```bash
make install && make mock                 # repo root
cd frontend/packages/web && npm install && npm run dev      # http://localhost:4000
```

`make demo-check` at the repo root runs the whole demo headlessly and saves screenshots to `docs/overnight/screens/`.

## Current acceptance scope

This script assumes Kori's UI items are merged: U1 (Intake and independent review selection, four demo cases), U2
(live rm0-v1 session protocol), U3 (per-component availability), U4 (advance planning) and U5 (simulation time).
`make demo-check` drives the U1 and U4 browser steps and the existing motion steps headlessly.

What stays limited or open, and what to say about it:

- **Seed data everywhere.** Every result is AMBER/limited at best; the banner stays on.
- **Public forecast (D2) is not connected.** Advance planning runs on a seeded *training scenario*, labeled synthetic
  and "not a weather forecast". The panel says the public forecast is unavailable.
- **Live rm0-v1 frames and U2 are merged.** The UI consumes runtime scene/recordings, speed and reconnect state.
  Vessel dynamics remain synthetic; live authentication and deployment acceptance are separate gates.
- **Simulation-time forcing (S2) and tug kinematics/heel (S3) are not built.** The motion view says "forcing time:
  not reported" when absent and lists any missing roll/pitch under *Not drawn*; supplied fields are drawn conditionally.
- **Per-component availability (U3)** shows each component's own provider, basis and age only when the service
  supplies component provenance; the offline demo serves the mock, which reads *mock*.

[Local rehearsal screenshots](../docs/LOCAL_REHEARSAL.md) show the seed-data workspace, printed independent-review
identity and authored motion replay. Use them with their qualification labels visible.

## Script (about five minutes)

1. **The picture (20 s).** The app opens on Pier 12 North with a DDG 51 starboard side to and recommended lines
   colored by load. Point out the seed-data banner, the wind and current arrows, and the compass.
2. **Pick a demo case (40 s).** In *Demo cases* press **Load** on *DDG moderate weather — limited demonstration*. The
   panel shows the **initial** outcome of the plan exactly as supplied: AMBER, validity limited, with its result id.
   Mention the other three: storm (RED, overloaded), inadequate depth (RED, invalid) and the one-line plan that is
   initially RED/invalid. Its **final** outcome after planning is a repaired AMBER plan, shown separately, never relabeled.
3. **Data honesty (20 s).** *Data sources and capabilities*: wind, current and water level each say where they came
   from (here: mock), how old they are and why; waves, wake and telemetry say *unavailable*, never zero. A rejected
   or failed source turns every component red with *error*. Old values never pass as current.
4. **Intake, Planner, independent review (75 s).** *Environment intake* → **Assess conditions** (MST, windows of
   concern, data quality). *Planning agent* → **Ask the agent to plan**: the steps stream in and the plan lands on the
   canvas. Note that **Create safety sheet** is disabled. Press **Run independent review**: a separate Safety agent
   re-checks the finished plan against its own threshold and the same Intake report, and shows its verdict
   (*ready for signature*), each check, and the review id. Back in *Demo cases*, the **final** outcome now shows the
   Planner status and the review verdict next to the initial one.
5. **Safety sheet (40 s).** **Create safety sheet**. The sheet names the review it was built from (review id and plan
   id). Press **Print**, approve as pilot; the sheet locks.
6. **Advance planning (60 s).** *Advance planning (24 h+)*: as-of now, arrivals 24–30 h ahead, 2 h docking, 6 h
   holding. The public forecast reads *unavailable*; press **Use training scenario**. The coverage line says the
   series covers every arrival through holding. **Assess arrivals**: the alternatives table shows each arrival's
   outcome, peak % WLL and governing line; the selected arrival is starred. **Apply selected configuration** keeps
   the modeled paid-out lengths and the installation tide (not cutting lengths). Change *Holding* to 12 h:
   **Recheck required** appears and apply is disabled until you assess again.
7. **Motion (45 s).** **Open motion view** → **Start session** → **Resume**. Point at sim time vs wall time, the
   measured rate, the forcing time, and the *training · synthetic forcing* label. Set **Speed** to 4×; the session
   confirms it. Issue a tug command, **Pause**, **Reset**. Pick the session under **Session recordings** to replay it.
   **Map 2D/3D** shows the same frames in Cesium; *Not drawn* lists what the frame did not supply.

Keep these for questions: storm ramp (bottom dashboard, *Storm ramp*, 55 kt), wind limits and gust risk, berth from an
image, and the Navy/Metric toggle.

## Canvas and evidence walkthrough

- Drag the DDG along and away from the pier. Previous margins clear during the edit; release requests a fresh analysis.
  Escape restores the previous placement. Toggle side-to and repeat; yaw continues to follow side-to.
- Choose a line type, then drag a ship bitt to a pier fitting. Select the numbered line and drag one endpoint to
  another valid fitting. The line number, type, parts and installed-length fields are preserved. Invalid drops do
  not alter the plan. Expand **Edit endpoints** for keyboard controls.
- Select CG-47, LHD-1 or CVN-68. The hull and environmental inputs remain visible, while missing fitting data blocks
  planning. The previous ship's lines and agent plan must disappear.
- After planning, inspect the sequence's review state, each intermediate static check, issues, limitations and
  source link. Partial restraint remains indeterminate; matching geometry does not establish forecast revision binding.
- **Wind limits** separates the working-limit gust and application advisory from the unavailable ultimate breaking
  gust. **Gust risk** reports scenario statistics and does not turn missing MBS evidence into zero risk.

The reproducible pointer check is `frontend/browser_checks/canvas_drag.py`; run it against a Vite development server
as described in its docstring. [Delivery evidence and remaining dependencies](KORI_UI_DELIVERY.md) distinguish the
implemented UI from work still assigned to Snyder, Cruz and Bixler.

## Things to say

- Units: the header toggle switches the whole UI between Navy and Metric (the printed sheet stays Navy).
- The load/geometry solvers and agent workflow are implemented. Seed asset data, draft sequences and
  surrogate motion remain unqualified; real implementation does not establish operational readiness.
- Every number the agent cites links to a stored result; nothing on the sheet is typed in by a model.
- The same screen can drive another application. The shell does not know about mooring; the mooring adapter lives in
  one folder.

## If something goes wrong

- *Could not reach the modeling service*: start `make mock`, then press **Retry**.
- Only DDG 51 has fittings in the seed data; other classes show a hull so you can show the berth size.
- The first render after a long idle can take a moment on machines without a GPU.
