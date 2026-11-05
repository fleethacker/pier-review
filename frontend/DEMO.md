# Demo walkthrough

A five-minute path through the current Phase 1 demonstration: a supported **AMBER/limited** plan for a DDG 51
at a seed NAVSTA pier, tug assistance, synthetic storm warnings and a reviewed Mooring Evolution Safety Sheet.
The modeling and agent workflows are implemented; the reference data and surrogate motion remain unqualified.
Point out the seed-data and synthetic-source labels when presenting. This is not a completed G2 acceptance gate.

## Setup

```bash
make install && make mock                 # repo root
cd frontend/packages/web && npm install && npm run dev      # http://localhost:4000
```

`make demo-check` at the repo root runs the whole demo headlessly and saves screenshots to `docs/overnight/screens/`.

## Current acceptance scope

The five-minute presentation below is the existing demo, not completion of the master plan. `make demo-check` now
checks the supported, overloaded, invalid-depth and initially underconstrained cases through the full **API** chain.
The underconstrained input is repaired by search; show its initial RED/invalid result separately from its final
AMBER/limited result. Independent review identity is printed on each reviewed sheet. Supplied training forecasts
retain their synthetic labels; a successful API check does not establish the advance-planning UI story.

Live motion still uses legacy frames on this branch; rich rm0 playback is an authored fixture. Source-component
availability, live scenes/recordings/speed, forecast revision binding and U1/U2/U4 browser acceptance remain open.
Run `make demo-check-readiness` to see the explicit gaps. Current rehearsal is local; no Domino or clean-`main`
release rehearsal is claimed.

[Local rehearsal screenshots](../docs/LOCAL_REHEARSAL.md) show the seed-data workspace, printed independent-review
identity and authored motion replay. Use them with their qualification labels visible.

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
7. **Safety sheet.** Back in the agent panel click **Create safety sheet**. Review the margins, rationale and the explanation for any unavailable plan-bound layout
   image, press **Print**, then approve as pilot, first lieutenant and CO. The sheet locks after the first approval.

8. **Motion.** Close the sheet and press **Open motion view**. Press **Replay recording**, then **Play**: a recorded mock
   fixture shows the hull, fittings, lines, tug and force arrows, and the badges say *limited*, *mock* and *rm0-v1*.
   Point at the wave rows (*unavailable*, never zero) and at heave (*not simulated*). Drag the scrubber, change the
   speed. Then press **Start session**, **Resume**, and issue a tug command. Space plays or pauses, R resets, Esc closes.
9. **Where the data comes from.** In the sidebar open *Data sources and capabilities*: every stream says whether it is
   mock, replay, typed or live, why, and the capability list says what each module is qualified for (today: none).
10. **Berth from an image.** In *Berth from an image* choose any picture, press **Analyze image**, tick each amber
    item, then **Confirm and use this berth**. The header reflects the returned provenance (estimated for a catalog draft). Without an LLM,
    this is a deterministic metadata/catalog draft, not extraction from the uploaded pixels. Review the source note.

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
