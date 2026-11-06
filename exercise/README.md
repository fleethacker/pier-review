# Exercise simulator

Replay a naval exercise in 3D on a Mapbox map: ships, aircraft, missiles, mines and sensors on open ocean, with a
storyboard that narrates the run and a red team that asks how often it comes out that way.

It stands on its own: the simulation runs in the browser, and the small service in `server/` only keeps a shared
scenario library, hands out the public map token and collects browser error reports. The app works with the service
switched off — scenarios then live in this browser and it asks you to paste a token.

## Run it

```bash
npm install            # Node >= 22.17
npm run dev            # http://localhost:4100

# optional, in another terminal: the shared library, map token and error log
cd server && uv sync && uv run uvicorn exercise_api.main:app --port 8200
```

Checks before a pull request:

```bash
npm run typecheck && npm run lint && npm test -- --run && npm run build
cd server && uv run pytest -q
```

## Layout

```
index.html            the page
src/main.tsx          mounts the chrome
src/Chrome.tsx        the page frame: tab bar and the panels around the map
src/index.ts          what the app is and which views it has
src/runtime.tsx       starts the simulator and hands the chrome its panels
src/sim.ts            the simulation
src/montecarlo.ts     the red team
src/mapView.ts        the Mapbox map
src/ui/, src/lib/     the handful of shared widgets and helpers the app uses
server/               the optional FastAPI service
e2e/                  the browser check (needs Playwright)
```

## What it does

Gather what an exercise produced into one timeline, play it back in 3D on a Mapbox map, and tell the story of it. The
page opens on that story: the map across the width of it, the **event feed** down the right as things happen, and the
**storyboard** along the bottom, always there. Pressing **Source** on any line of the feed opens the **data catalog** at
the record that line came from — a radar track, a sonar bearing, an emitter report, a tactical message.

The simulation that produces all of it is still here, one click away under **Setup**: the scenario, the conditions, the
forces, the contact table, what the map draws, and the red team. It is not the point of the page any more, which is why
it is behind a drawer.

**Mapbox token.** Mapbox GL needs a public access token (`pk.…`). The tab looks for one in this order: the build
(`VITE_MAPBOX_TOKEN=pk.…` in `exercise/.env` or the environment of whatever builds the app; Vite inlines it, which is
fine for a public token), one pasted into this browser (the prompt the tab shows when it has none, kept in local
storage), and the service (`MAPBOX_TOKEN` in the environment of the exercise service, served from
`/api/v1/exercise/config`; on Domino, set it as an environment variable on the app and restart it; secret `sk.` tokens
are never served). The server route means the token does not have to be present at build time. The default **Standard** map style works
with any valid token. The **Satellite** styles also need raster-tile access, which some tokens and plans do not have;
the tab says so if Mapbox refuses.

**What you can configure** (all of it is plain JSON, so scenarios can be saved, shared and edited by hand):

- Scenario: name, length, light (dawn, day, dusk, night; on the Standard styles), and the starting view.
- Environment: wind (speed, direction it blows from) and current (speed, direction it flows toward). Current sets every
  ship over the ground; wind pushes ships downwind a little, small craft more.
- Units: ships (CVN, LHD, CG, DDG, fast attack craft, merchant), **aircraft** (fighter, helicopter), **missiles**
  (anti-ship, surface-to-air) and **mines**. Each has a side (blue, red, neutral), start position, heading, speed and an
  optional turn-rate limit. Every unit has one behavior: follow a **route** (waypoints with optional per-leg speed and,
  for aircraft, altitude; optional loop; click the map to add waypoints), keep **station** on another unit, **pursue**
  one, **circle** a point (aircraft), **strike** a unit (missiles) or **hold** (ships drift, helicopters hover, fixed-wing
  aircraft circle where they are, mines stay put).
- Launches: any unit can be launched by another at a set time (a missile fired, an aircraft launched). It appears at the
  launcher; if the launcher has been destroyed by then, the launch does not happen. **+ Add salvo** fires several
  missiles in turn.
- Damage: every ship and aircraft has hit points and every missile and mine has a damage rating, a fuze radius and a hit
  chance. Anything that does at least a unit's hit points in one hit destroys it; a ship below half strength slows to half
  speed; a destroyed ship stays where it is, dark and burning, and a destroyed aircraft is gone. Ships also shoot at
  missiles aimed at their own side (a shot kill chance, shots per missile, a reload time, a magazine and a radar-horizon
  range), which is what makes a salvo a contest. All of these are set per class and can be overridden per unit.
- Sensors and detection (a switch in the Scenario panel, off by default so older scenarios behave as before): units only
  know what their side's sensors can see. Radar range grows with the fourth root of the target's cross-section (so a
  radar signature a tenth the size cuts range to about 56%), is cut off by the radar horizon (an antenna 22 m up sees a
  sea skimmer at about 30 km, a jet at 8 km altitude at about 380 km) and by sea clutter on low targets; sonar hears
  noise, which is why a quiet submarine is heard at a fraction of the range at which it hears a ship. Tracks are shared
  across a side, so a scouting helicopter or aircraft can find a target for a ship that cannot see it. Missiles and
  torpedoes are held until the target is tracked and in range (the salvo then goes off at the spacing it was planned
  with, and the event list says "held: not tracked" or "held: out of range"), and ships only shoot at missiles they have
  been tracking for a few seconds. A **Detected** event marks the first time each side picks a unit up.
- Rough seas (a switch next to it): the wind sets a sea state, and small craft slow down in it (fast attack craft from
  sea state 4, carriers hardly at all). Radar also loses low targets in the clutter.
- Decoys: a ship can carry decoys and jammers. Each missile or torpedo that gets close uses one up and may be led away.
- Submarines and torpedoes: a submarine is drawn as a dark hull and sail, heard rather than seen, and fires torpedoes that run
  under the water. Ship missile defences cannot shoot torpedoes; decoys are the defence.
- Storyboard: pictures and captions that come up beside units as the run plays. See below.
- Playback: play, pause, restart, scrub, 1x to 600x. **Follow** keeps the selected ship centered, and **Present** plays
  the whole exercise: it fills the screen, winds back to the top, picks a
  speed that plays the run out in about a minute and a half, and starts, with the storyboard coming up as it goes and the
  caption large enough to read from the back of a room. Pause, scrub and speed are still there, *Play again* restarts it,
  and Esc or *Exit* leaves. The view opens with a fly-in to the main group. Under Setup → Map: ship size exaggeration
  (so ships read when zoomed out), wake length, names, routes, sensor ring, storyboard bubbles.
- Look: the light preset (dawn, day, dusk, night) lights the sea, and at dusk and night the ships' navigation and deck
  lights glow. Dusk and night are the most dramatic; the presets use them.

Twelve presets ship with it: a carrier group transit, a surface contact intercept at night, a formation drill, a **missile
salvo on a carrier group**, a **minefield transit**, an **air raid with SAM defence**, a **submarine ambush** and
**over the horizon** (a hostile destroyer that cannot see the carrier group sends a helicopter to find it; sweep the
helicopter's altitude in the red team). The last five include red-team setups. Four more are large (60 to 220 units) and use
everything: a **joint task force** (carrier group with fighters, early warning, ASW helicopters and a scouting drone
against destroyers, fast attack craft, raiders, two submarines, twenty attack drones and a minefield), a **convoy
through a submarine strait** (sweep the number of escorts) and a **drone swarm defence** (sweep the number of drones
against ships with limited magazines) and a **theater campaign** (over 200 units: a carrier group and an amphibious group on two
axes against two surface groups, four submarines, two raid waves, two drone carriers, early warning on both sides and two
minefields; a run takes about three seconds, so a red-team batch wants several cores). Newer unit classes: frigate (good sonar), diesel submarine (quiet), surveillance
drone, attack drone and airborne early warning. Each large one takes a few seconds per run, so batches of them are
best on a machine with several cores (the red team uses worker threads). Use **Edit as JSON** or **Download** in the Scenario panel to save or load your own, or **Saved scenarios** to keep them
in this browser or in a **shared library** on the server that everyone using the app can open (saving over a scenario
someone else changed since you opened it is refused, so nobody's work is lost). The shared library is one JSON file per
scenario in `EXERCISE_DATA_DIR` (default `/mnt/data/exercise` if it can be written, else `.exercise-data`); in a container
whose disk is thrown away on restart, point it at a persistent volume.

**Editing on the map.** With the clock at the start, drag a ship to move where it starts. Select a ship with a route, then
drag its waypoints, or drag one of the small dots between two waypoints to add a waypoint there; right-click a waypoint to
remove it. A dashed line follows the pointer and nothing is recomputed until you let go, and Esc cancels. Dragging is off
while placing waypoints, in a replay, and for units that are launched rather than placed. **Record** plays the scenario and
saves the map as a WebM video (the map itself; panels and labels are not in the picture, and it needs a recent Chrome, Edge
or Firefox). The **Events** tab at the
bottom lists launches, hits, interceptions and losses in words (click one to jump to it) and the timeline marks them.

## Data catalog: where each event came from

The **Data catalog** button lists the collection sources reporting in the run — surface and airborne radar, acoustic,
ELINT, tactical comms, full-motion video, overhead passes and the weapon-system log — with how many records each
carries, over what span, and from which platforms. Pick a source to read its records, or press **Source** on a line of
the event feed to jump straight to the record behind that event. Every record opens its raw payload: JSON for the
machine feeds, a formatted message for comms.

None of it is a real observation. Each record is synthesised from the simulation's own geometry and timing at the moment
in question — the range in a radar track is the distance between those two units at that instant — and every feed states
what it was derived from. Imagery feeds carry frame metadata only; the simulation produces no pictures.

## Storyboard: pictures that come up as it plays

Exercises are usually storyboarded by hand, as images on slides. This does the same job against the running simulation.
A **storyboard** is a list of moments, each a picture and a line or two pinned to a time and to a unit. As the run plays,
each moment comes up in a bubble beside its unit, stays for as long as it is given, then fades; a later moment on the same
unit replaces an earlier one, and different units can have bubbles up at the same time.

- **Build from the run.** The **Storyboard** button in the map toolbar opens the panel. *Build from the run* picks the
  moments worth telling — losses, hits, mine strikes, first contacts, launches — ranks them, spreads them across the units
  so no one ship takes them all, writes a caption for each from what happened, and puts a fitting stock picture on it. Say
  how many moments you want. It is a starting point to edit, not a finished product.
- **Pictures.** Three ways: **capture the map** as it looks at that instant (the picture is taken inside a render, scaled
  down and kept in the scenario); **load a picture** from a file, which is scaled the same way; or pick one of the
  **stock pictures**. The stock set is thirteen public-domain photographs — carriers, destroyers, a frigate, a submarine,
  a missile launch at night, aircraft, a drone, damage control, a bridge watch, replenishment, and the sea from orbit —
  taken from Wikimedia Commons, nearly all United States Navy work, which is public domain as work of the federal
  government. Each one's source, author and licence are recorded in `stockImages.ts` and shown in the picker.
- **Editing.** Every moment has a title, a caption, a time, how long it stays up, and the unit it hangs on (or a spot on
  the map, for scene-setting). Click a bubble on the map to open that moment; click a moment to wind the clock to it.
- **Showing it.** **Present** in the toolbar plays the whole thing by itself, full screen, with each moment's picture and
  caption coming up as its time arrives — one button, nothing to drive.
- **On the page.** The **Storyboard** tab at the bottom shows the whole thing as a strip that runs with the clock: the
  moment that is up is lit and scrolled to, past ones are solid, ones still to come are dimmed. Click a card to jump to it.
  The moments also appear as marks above the timeline.
- **Out of the app.** *Storyboard to print* opens the whole thing as a page laid out two cards to a row, which prints or
  saves to PDF from the browser — the direct replacement for the slide deck. *Download the page* saves the same file.

Pictures you capture or load are kept inside the scenario, so a scenario travels as one file with its storyboard in it;
the panel shows how much they weigh, since the shared library refuses a scenario over about a megabyte. Stock pictures
are references, so they cost nothing to save.

Four presets ship with a written storyboard, so the feature can be seen without building one: **Missile salvo on a
carrier group** (a salvo gets one hit through the screen), **Submarine ambush** (she hears them first and is never
found), **Over the horizon** (finding the group costs the attacker seven minutes and the shot) and **Drone swarm
defence** (cheap drones against magazines that run out). Every time quoted in those captions is an event the simulation
really produces, and a test holds them to it, so retuning a scenario cannot quietly leave the words wrong.

## Red team: how likely is it?

**Red team** in the map toolbar runs the scenario hundreds or thousands of times with random variation and measures how
often things happen. You set three things, all saved with the scenario:

- **Outcomes**: the questions to ask. A unit is hit, destroyed or falls below a strength; a side loses N units; a mine goes
  off; N missiles are shot down; two units come within some distance of each other; a unit is detected (by anyone, or by one
  side). Any of them can be limited to "by this time", and they combine: **all of**, **any of** or **not** other outcomes
  listed above (so "the carrier is hit and a destroyer is lost", or "the carrier is not hit within 12 minutes").
- **What varies**: any of wind and current, or, per unit, speed, heading, start position, route position, launch time,
  altitude, hit points, damage, hit chance, defence kill chance and shots, radar signature and range, decoys and decoy
  chance, or whether it is present at all. Each draws from
  a uniform, normal, triangular or listed distribution, and replaces, adds to or multiplies the scenario's value.
  Missile hits, defensive shots and mines are chances on top of that.
- **A sweep** (optional): repeat the whole batch at several values to draw a curve, for example how the chance a carrier
  is hit grows as the salvo goes from 1 to 8 missiles.

Results show each outcome's chance with a 95% interval (Wilson), a histogram of when it happens, a ranking of which
variation drives it (the correlation between each draw and the outcome, with the average value when it happens and when it
does not), and average hits, interceptions and losses per run. Every chance carries its "±", and a chart shows it settling
as runs accumulate, with a note of how many runs would get within ±2 points. Tick **Stop early when sure enough** to end a
batch as soon as every interval is that narrow. Runs go on worker threads (up to seven, fewer on small machines; if workers
are blocked the batch quietly runs on the page's own thread), with progress and a Stop button. Results can be downloaded as
**CSV** or **JSON** (scenario, settings and results together), or opened as a printable **report**.

**Comparing.** **Keep as baseline** remembers a finished batch; change the scenario or a setting, run again, and each chance
shows how far it moved, with an interval on the change (grey arrows are within noise). This is the way to answer "does
adding a destroyer help?" without squinting at two percentages. **Show their paths together on the map** draws up to six runs
where an outcome happened (red) and six where it did not (green).

Every batch is reproducible: the same seed, scenario and settings give the same numbers, and every run can be **replayed
on the map** (choose a run where an outcome happened, or one where it did not) with the same random draws and the same
chance rolls. Replays are in the batch's own scenario, not yours, which is untouched; **Exit replay** goes back. Sweep
values share the same random draws run for run, so the curve is not noise.

These are chances on illustrative numbers, so the output is only as good as what you put in: the point is to see which
assumptions the answer depends on, not to predict a real engagement.

**How it works.** `src/sim.ts` runs the whole scenario up front at a fixed step (deterministic, so scrubbing
and rewinding are free) and the map interpolates between samples. Ships are generated hull outlines with
class-specific superstructure (masts, radar domes, flight-deck markings and parked aircraft on the carriers, container
stacks on the merchant), drawn as Mapbox fill-extrusions at true size times the size slider. Hulls are stacked slices,
which gives a dark waterline band and a flared deck edge. Wakes are a fading center trail plus a V; foam around the hull
scales with speed; lights are tiny emissive pillars with a soft glow. Aircraft are drawn at their altitude with a
glow on the sea beneath them, missiles are drawn large enough to see with an exhaust glow and a faint line to their target,
and hits, interceptions and launches flash where they happen. `src/montecarlo.ts` draws the random variation, runs batches
and computes the statistics; `sim.ts` takes a seed for the chance rolls so any run can be repeated. Ship dimensions and handling are rounded, illustrative figures, not for operational use. Handling is simple on
purpose: speed and turn rate are limited per class, and escorts hold station with a proportional controller. Formation
turns need a slow guide turn rate (see `maxTurnRateDegPerS` in the presets), because an escort 1.5 km abeam cannot keep
up with a guide that turns on a 300 m radius.

Tests cover the simulation (including the engagements, sensors and the Monte Carlo statistics), the storyboard, the
scenario JSON, the map view (against a fake Mapbox), the panels, and the server's library, token and error endpoints. `npm run test:e2e` drives a
production build and the real exercise service in headless Chromium (software WebGL, so it checks that things load and work,
not how the map looks); it needs Playwright, which is not a dependency: `npm i --no-save playwright && npx playwright install chromium`.
Browser problems (uncaught errors, a lost WebGL context, a refused token) are sent to the exercise service's log under the
`exercise` logger, with any Mapbox token blanked first. Check the look on a real GPU before demoing.

**Not modeled**: terrain and coastlines (the scenarios are open ocean; Mapbox draws real land, but nothing in the
simulation knows about it), electronic warfare beyond decoys, weather beyond wind and sea state, anything that flies a
deck cycle (carrier flight operations), and fuel. Detection is deterministic: in range means seen.
