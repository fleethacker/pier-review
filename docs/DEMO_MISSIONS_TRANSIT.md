# Demo: mission storyboard (S5) and port transit (S6)

A 5-minute script for the Missions app, how to prepare its data, what to say about limits, and what to check when it
misbehaves. Specs: [MISSION_STORYBOARD.md](MISSION_STORYBOARD.md), [PORT_TRANSIT.md](PORT_TRANSIT.md). Plan:
[MASTER_PLAN.md](MASTER_PLAN.md) (S5, S6). Everything shown is synthetic or demonstration data.

## 0. Before you start (5 minutes, once)

Run the services and the UI (prerequisites: [uv](https://docs.astral.sh/uv/), Node 20):

```bash
make install && make mock                  # repo root: modeling :8000, agents :8001
cd frontend/packages/web && npm install && npm run dev      # UI on http://localhost:4000
```

Or `./app.sh` (builds the UI and serves everything on :8888; the Domino entry point). Open
`http://localhost:4000/?app=missions` (or `:8888`). There are two tabs: **Storyboard** and **Transit**. Missions are kept
by the backend between runs, so use a fresh mission name each rehearsal.

Make the demo files (offline, deterministic):

```bash
uv run --all-packages --with pillow python scripts/make_demo_mission_data.py ~/demo-mission
```

This writes `track.csv`, `on_track.jpg`, `in_gap.jpg`, `clock_off.jpg` and `reports.json`. The track is a 2 hour sortie
starting 2026-11-05 12:00 UTC, one fix every 30 s, with a deliberate 10 minute gap from 12:50 to 13:00. Rehearse once
with `scripts/check_missions_ui.py` if you have Playwright (see its docstring); it drives this same flow and prints
PASS/FAIL per step.

Do the first Transit run once before the demo to warm it up (a run takes seconds, longer on a slow machine).

## 1. Storyboard demo (about 2.5 minutes)

| # | Click or type | Say |
| --- | --- | --- |
| 1 | Open `?app=missions`, tab **Storyboard**. In **Create mission** enter name `Hampton Roads sortie` and vessel id `DDG-99`, press **Create**. | "After a mission we have recorded fixes, photos and reports. The storyboard ties them together by time." |
| 2 | **Upload track file**: choose `track.csv`, Format `csv`, leave the UTC offset blank (the file has zones), **Upload track**. | "The result box says how many fixes were accepted and lists duplicates or out-of-order fixes. Nothing is silently dropped." Point at the **Track ingest result**. |
| 3 | **Upload image**: `on_track.jpg`, caption `On the track`, **Upload image**. | "Time and position come from EXIF." |
| 4 | `in_gap.jpg`, caption `Inside the gap`. | "This photo was taken during a recording gap." |
| 5 | `clock_off.jpg`, **Camera clock offset** `120`, caption `Camera clock slow`. | "The camera clock was two minutes slow, so we add 120 seconds. The offset is explicit, not guessed." |
| 6 | **Add report**: Time `2026-11-05 12:10`, Title `Bridge log entry`, **Add report**. Again: Time `13:20`, Title `Stated position report`, Stated latitude `36.999`, Stated longitude `-76.216667` (same values as `reports.json`), **Add report**. | "Reports carry a time, text and optionally a stated position." |
| 7 | Read the **Mission summary** (fixes, longest gap). | "Longest gap is about ten minutes, longer than the interpolation limit of 5 minutes." |
| 8 | Drag the **Mission time** slider to about 30 minutes in. | "The ship marker moves along the recorded path. Between two fixes the position is interpolated; at a fix it is exact." |
| 9 | Drag into the gap (about 55 minutes in). | "Here the app says **position not established**. We never fill a gap and never extrapolate before the first or after the last fix." |
| 10 | In the **Events** list click **Inside the gap**. | "The photo is listed with no position. The detail panel says Position not established." |
| 11 | Click **Stated position report**. | "The report claims a position. It is shown as roughly 1 km off the track (`~1000 m off`; the detail reads 'differs from the track by ...'). We report the discrepancy; we do not decide who is right." |
| 12 | Click **Download GeoJSON**; open the file or show the link. | "Track, events and discrepancies export as GeoJSON for other tools." |

Tip: the map shows about 8 km at a time. Leave **Keep the ship centered** on while scrubbing; turn it off to pan freely.

## 2. Port transit demo (about 2.5 minutes)

| # | Click or type | Say |
| --- | --- | --- |
| 1 | Tab **Transit**. Preset **DDG-51 inbound, tug-assisted final approach**, press **Run**. | "A DDG inbound from the Thimble Shoal entrance to a point 250 ft off the Pier 12 north face, with a bow and a stern tug helping below 5 knots." |
| 2 | Wait for **Run** to re-enable. Press **Play**; use the **Simulation time** slider and speed. | "The ship follows the route with a line-of-sight autopilot and slows over the last half mile." |
| 3 | Scrub to the last third of the run. Point at the **orange arrows**. | "Orange arrows are tug force at the hull contact point, length proportional to force. Tug hulls are not modeled; the arrow shows force only." |
| 4 | Show the **Vessels** table, then the **Transit events** list. | "Per-vessel speed, heading, turn rate and tug state, and a list of events such as waypoint reached and tug saturated." |
| 5 | Show the **Assumptions** box and validity badge. | "Validity is always limited. These are the labeled assumptions: surrogate maneuvering model, assumed propulsion. This is a demonstration route, not navigational advice." |
| 6 | Preset **Two vessels on one clock: DDG inbound, CG outbound**, **Run**, **Play**. | "Two ships on one clock on laterally offset lanes. There is no ship-ship interaction in the model, and we say so." |
| 7 | Press **Save as mission**. The app switches to **Storyboard**. Scrub **Mission time**. | "The simulated track uses the same fix format as a real one, so it replays in the storyboard. Same tool for plan and for review." |

Optional first comparison: run **DDG-51 inbound ... own thrust** and then the tug-assisted preset; the tug run shows the
orange arrows and a controlled final approach, the own-thrust run does not.

## 3. What to say about limits

Say these out loud. They are the honest answer to "can I trust it?".

Storyboard:
- Positions between fixes are interpolated (great-circle, linear in time) only if the fixes are at most 300 s apart.
- Gaps longer than that are never filled: the app says position not established.
- Nothing is extrapolated before the first or after the last fix.
- Photo and report times depend on the camera clock and UTC offsets you supply; naive timestamps are rejected unless an
  offset is given. A stated position is compared with the track, never used to correct it.
- Tracks are shown as recorded; duplicates and out-of-order fixes are reported.

Port transit:
- A surrogate 3-DOF maneuvering model (published main-dimension regressions), not validated for any ship.
- Propulsion, rudder and tug response are labeled assumptions; the reference data has no ship speed/power.
- Deep water only: no squat, bank effect or under-keel clearance.
- No ship-ship interaction; tug hulls are not simulated, only their forces.
- Routes are demonstration routes with approximate waypoints, not charted channels. Not navigational advice.
- Validity is always limited, with reasons shown in the UI. Do not present any result as a qualified prediction.

## 4. Troubleshooting

| Symptom | Check |
| --- | --- |
| Page loads but Storyboard/Transit show errors or "sample data" | Backends not running. `curl http://127.0.0.1:8000/api/v1/health`. Vite proxies `/api/modeling` to `127.0.0.1:8000`; override with `MODELING_PROXY_TARGET` (use the numeric address, not `localhost`). |
| Port in use | UI dev :4000, `app.sh` :8888 (set `PORT`), modeling :8000, agents :8001. Stop the old process or change the port. |
| Upload fails with 413 "Request body exceeds configured limit" | Body limits. S5 uploads use `MOORING_MAX_UPLOAD_BYTES` (default 32 MiB); other POSTs use `MOORING_MAX_BODY_BYTES` (default 1 MiB). Images are capped at 8 MB, track files at 20 MB, 300 images per mission. Restart the modeling service with a larger value if needed. |
| 401/403 | Auth is off by default. With `MOORING_AUTH_REQUIRED=1` the UI needs `VITE_API_BEARER_TOKEN` at build time. |
| Images or GeoJSON download are broken only when auth is on | The image `<img>` and the GeoJSON link are plain browser requests and send no Bearer header. Demo with auth off, or put a trusted gateway in front. |
| Track upload says naive timestamps rejected | Fill in "UTC offset of naive timestamps" (minutes east); the demo CSV uses `Z` and needs none. NMEA GGA-only files need the NMEA date. |
| Image shows no position or the wrong time | The EXIF has no GPS or time: use "Captured time override". Wrong by a constant: set Camera clock offset (camera slow = positive). |
| Map shows empty water or the ship is off screen | The map shows about 8 km. Turn on **Keep the ship centered** (follow toggle), or select an event to jump to it. Without a Mapbox token the backdrop is plain. |
| Transit Run never finishes | Wait up to 3 minutes on slow machines; check the modeling log. Re-run after a reload; reducing the vessel list or duration is not needed for the presets. |
| Old missions clutter the list | They persist in the backend store. Use a unique mission name per rehearsal, or restart with a fresh store. |
