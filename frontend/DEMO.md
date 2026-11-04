# Demo walkthrough

A five-minute path through the Phase 1 demo (gate G2): a green plan for a DDG 51 at a mock NAVSTA pier, tug
horsepower, gust warnings in a storm, and an approved Mooring Evolution Safety Sheet. Everything runs on the mock
backends, so every screen says **MOCK DATA**; say so out loud when you present it.

## Setup

```bash
make install && make mock                 # repo root
cd frontend/packages/web && npm install && npm run dev      # http://localhost:4000
```

## Script

1. **The picture.** The app opens on Mock Pier 12 North with a DDG 51 starboard side to and six recommended lines,
   colored by how loaded they are. Point out the mock banner, the wind and current arrows, and the compass.
2. **Move the ship.** Drag the ship along the pier. The lines follow it and the analysis refreshes on release. The
   slider in the Scenario panel does the same. Switch **3D**, orbit by dragging, then back to **2D**.
3. **Edit the plan.** Click a line to see tension, % working load and angles. Click **Add line on canvas**, click a
   ship bitt and then a pier fitting. The new line is analyzed straight away. Change a rope or parts count in the
   list. **Remove** a line with the ✕.
4. **Read the analysis.** In the Analysis panel, point at the status, the tightest line, and a finding with its
   NSTM 582 paragraph.
5. **Ask the agent.** In *Planning agent* click **Ask the agent to plan**. Watch the steps arrive, then the plan:
   tug assist (horsepower and force per tug, drawn on the canvas), the line sequence, and the rationale. Click a
   cited result id to see the stored number behind a claim. **Undo agent changes** restores your own lines.
6. **Storm.** In the bottom dashboard, **Live** tab, choose *Storm ramp (what-if)*, ramp to 55 kt over 1 minute.
   Wind and gust climb on the chart, the arrows grow, lines recolor, and the **Alerts** tab lists the warnings with
   their NSTM references. Open **Wind limits** and **Gust risk** and run them for the limiting wind and the chance of
   exceeding working load.
7. **Safety sheet.** Back in the agent panel click **Create safety sheet**. Review the margins, rationale and layout
   image, press **Print**, then approve as pilot, first lieutenant and CO. The sheet locks after the first approval.

## Things to say

- Numbers are placeholders. Line geometry and the NSTM rule checks are real; loads and the agent are mock.
- Every number the agent cites links to a stored result; nothing on the sheet is typed in by a model.
- The same screen can drive another application. The shell does not know about mooring; the mooring adapter lives in
  one folder.

## If something goes wrong

- *Could not reach the modeling service*: start `make mock`, then press **Retry**.
- Only DDG 51 has fittings in the mock data; other classes show a hull so you can show the berth size.
- The first render after a long idle can take a moment on machines without a GPU.
