# Motion workspace build — 6 November 2026

The user authorized an overnight overhaul confined to the Motion UI, with backend changes wherever needed,
four existing vessel classes at Norfolk, explicitly labeled synthetic configurations when verified inputs are missing,
parallel implementation and independent review, followed by CI, merge to `dev` and update of the
`fleet-hack-physics-sim` Domino app. Other tabs remain outside the UI scope.

Base: `ec41de786a5381482a12c8f40d4ef51ae1eeda01` (PR #32 audit remediation). Coordinator branch
`ws-b/motion-workspace`; individual lanes use their own worktrees. Implementation and targeted acceptance are below;
the final PR records combined checks, CI and target deployment. `MASTER_PLAN.md` retains project-wide qualification gates.

## Scope and ownership

| Lane | Implementation | Required acceptance |
| --- | --- | --- |
| Motion UI | `motion_ui`: Motion package and only its navigation integration | Direct tab entry, paused start, collapsible detail, map without a private token, clear ship rendering, accessible controls, geographic and forward/aft/side views, wind/current animation and reduced motion. |
| Physics | `motion_physics`: mechanics/berthing runtime and additive controls | Ship engine/helm/thruster forces, rotational inertia, cargo mass/CG/inertia, small-angle synthetic loading response, working lines, tug geometry and coupled tug dynamics; analytical and conservation checks. |
| Prediction | `motion_prediction`: immutable clone rollout | Same current model and commands, complete state and forcing, current path and what-if updates, bounded work, source identity, no mutation and honest hazard/uncertainty limits. |
| Integration/data | Coordinator: workspace schemas/router/service and data simulation | Four class demos, saved custom scenarios, live/snapshot/synthetic separation, route guidance, future telemetry state boundary, session release and ownership, source evidence. |
| Acceptance | Fresh independent reviewers after integration | Full suites, generated contract/types, actual-browser interactions and geometry, adversarial invalid/stale/race cases, CI and target deployment. |

## Design basis

Separate commanded orders from actual actuator response. Group helm and propulsion beside the operational view;
make detailed diagnostic readouts collapsible while keeping validity, source and critical warnings visible. This
applies the information grouping and source/validity presentation principles of
[IMO MSC.191(79)](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.191%2879%29.pdf)
and the terminology and interaction guidance of
[MSC.1/Circ.1609](https://wwwcdn.imo.org/localresources/en/OurWork/Safety/Documents/IMO%20Documents%20related%20to/MSC.1-Circ.1609.pdf).
It is a design rationale, not a claim of equipment compliance.

The existing model is a planar rigid body with surge, sway and yaw, rather than a point mass. Its inertia, Coriolis
terms and force/moment frame conventions must remain explicit; see
[Fossen's marine craft formulation](https://www.fossen.biz/html/marineCraftModel.html). New loading and propulsion
parameters are supplied or synthetic, never vessel-qualified by their presence in the UI. Cargo changes at rest
avoid inventing momentum exchange from instantaneous mass movement. Small-angle trim/heel is not a complete
six-degree-of-freedom seakeeping or damage-stability model.

Satellite imagery supplies visual geographic context, not water depth or clearance. Attribution must remain visible
according to [Esri's attribution guidance](https://doc.arcgis.com/en/arcgis-online/reference/display-copyrights.htm).
NOAA's [GIS services](https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html) and
[ENC Direct guidance](https://www.nauticalcharts.noaa.gov/learn/encdirect/) distinguish GIS derivatives from
navigation-certified chart products. Existing authored Norfolk route stations are only coastline-tested demonstration
inputs. This build extracts actual NOAA ENC Online land/shoreline/pier geometry into a bounded, attributed fixture with
source dates and response hash. The original direct final route crossed neighboring piers; the new route goes around
their western ends and aligns before entering the basin. Four full rigid-body rollouts check swept LOA/beam footprints
against this geometry, using the existing OSM coastline outside its declared box. No near-pier exemption remains in
these tests. Missing seabed coverage stays unknown, never a constant depth extrapolated across the port.

## Implemented behavior and limits

The four class demos start paused. A run uses one RK4 clock with bounded engine/rudder/thruster ramps and independent
synthetic tug rigid bodies. A free tug transfers no force; compliant push contact and taut towlines transfer equal and
opposite forces/moments, with declared capacity, deformation and energy limits. Standby tug bows start 45 ft off the
assigned hull point, an authored demo placement, not a recommended clearance. Tug ambient forcing, tug-to-tug contact
and general hull-impact response are absent; unsupported overlap is invalid, not successful penetration.

The route controller issues ordinary bounded actuator orders on simulation time, never overwrites pose/velocity,
and remains in synthetic holding at the final approach point. Its authored orientation supports starboard side to;
automatic port-side following is rejected, while manual port-side maneuvers remain available. Any manual helm order disables it. This is not an
autonomous docking or pilotage system. The approximately 14-nautical-mile channel demo permits four simulated hours;
the speed control changes wall-time playback without skipping physics. Actual final line handling remains explicit.

Payload changes are permitted only while paused and stationary. They change mass, offset CG and yaw inertia; draft,
small-angle trim/heel and local clearance use the declared synthetic waterplane/stability inputs. These are quasi-static
attitudes on planar dynamics, not six-degree-of-freedom seakeeping, ballast-transfer or damage-stability calculations.
The constant notional depth patch is restricted to the berth area and is labeled synthetic; leaving it makes clearance
unknown. Known negative clearance and invalid attitude remain visible.

The camera clones the complete actual model, including tug states, ramps, lines, loading, guidance and forcing phase.
Preview does not command the live run. Requests are bounded and stale/expired outputs are rejected. Runtime coast,
shoal and traffic hazards and calibrated uncertainty remain unavailable; route-test geography does not imply those
hazards ran in each prediction. A measured local DDG 60-second preview with two free tugs completed in 0.243 s; that is
one-machine evidence, not a target-host latency guarantee.

`POST /motion/sessions/{id}/state` accepts explicit ship or selected tug pose/velocity in berth coordinates, with
timestamp, sequence, source and optional measured acceleration. It requires an owned paused session; rejects stale,
future, replayed, wrong-entity and wrong-frame inputs; starts a new paused run at t=0; preserves actuator/forcing phase;
and records immutable acceptance evidence. Acceleration is evidence, not an invented force. Ordinary Reset restores the
complete authored initial model, including attached lines. There is no hardware connection or authentication of a
caller-supplied sensor label. Recorded inputs obey the HTTP freshness policy; historical replay needs an explicit
replay clock rather than relabeling an old fix as live.

Public acquisition succeeded during acceptance using NOAA CO-OPS wind 8638614, water level 8638610 and currents cb0402
bin 4. The received observation was marked suspect, roughly 17 minutes old at acquisition, with unspecified wind
averaging/height and a provider note about current-direction interpretation. Those qualifications remain attached.
Each run holds the acquired snapshot; it is not a continuously refreshed weather feed. Provider failure produces an
error, not synthetic replacement values. Edited training conditions receive fresh scenario provenance.

## Independent review

Non-author reviewers exercised rotated push/tow force and moment conservation, connection power balance, ownership,
state adoption, invalid/unknown display, real browser workflows and concurrency. Fixed findings included expired
forecast display; reversed legacy tug labels; unsupported commands; mirrored sectional payload/CG; hidden negative
clearance; failed session-release retry; Reset losing authored lines; DELETE/expiry/attach races; delayed import/reset
responses; per-entity sequence confusion; forcing phase after reseed; and omitted guidance work accounting.
The final PR records exact full-suite counts and the additional fresh acceptance pass.

## Completion ledger

- [x] Direct Motion workspace, paused first frame and reliable session replacement/release.
- [x] Multi-class catalog, four demos, saved scenario reopening and explicit engine authoring.
- [x] Engine/helm/thruster, independent tug and line controls with authoritative feedback.
- [x] Cargo placement, mass/CG/inertia and depth/trim/heel readouts within stated model bounds.
- [x] Same-engine prediction and what-if updates during the run, with stale-output rejection.
- [x] Channel-to-pier demonstration with geographic and hull-track evidence; no autonomous navigation claim.
- [x] Animated wind/current from active frame conditions and explicit source states.
- [x] Public data acquisition and future ship/tug state boundary, without synthetic fallback under live labels.
- [x] Independent review and local Python/frontend/contract acceptance; final PR checks record exact head/counts.

CI, `dev` merge and Domino target verification are release steps, recorded on
[PR #33](https://github.com/fleethacker/pier-review/pull/33) after their completion. A checked implementation row does
not establish deployment or operational qualification.

Unresolved items stay unchecked until their evidence is recorded. Engineering qualification, calibrated trajectory
uncertainty, complete hydrographic/traffic coverage and operational navigation approval remain separate project gates.

## Playback and forecast refresh — 6 November 2026

Ship animation and trajectory calculation have different rates. The default demonstration integrates at 0.1-second
steps, yielding about 10 authoritative state updates per second at 1× playback. A smooth display can interpolate
between those received states at 30–60 frames per second without calculating a new 60-second forecast at every
display frame. Interpolation must remain a display operation: no extrapolation beyond received states, no changes to
the integration clock, and no delayed validity or control feedback.

An isolated before/after/before probe on deployed commit `8e3e9e6`, using the same synthetic DDG reset between phases,
found prediction-related stream contention. Domino's Small tier reported both CPU request and limit as one core,
with 4 GiB memory. Each phase lasted 18 seconds; the first second was excluded from frame-rate statistics.

| Prediction requests | Received frames/s | 95th-percentile frame gap | Largest frame gap |
| --- | ---: | ---: | ---: |
| Off, first control | 10.00 | 109.6 ms | 122 ms |
| On, one request per second | 4.93 | 604 ms | 881 ms |
| Off again | 9.73 | 109.5 ms | 512 ms (two gaps above 250 ms) |

The simulation continued near 1× speed by delivering larger simulation-time jumps. Seventeen prediction requests
averaged 0.931 seconds end to end; eight completed the full 60-second horizon and the others returned their actual,
limited 58–60-second coverage. A separate browser probe maintained 60 animation callbacks per second with no long
tasks, while the Preview button changed disabled state 18 times and the forecast HUD changed 19 times in 18 seconds.
This distinguishes server delivery contention and UI refresh churn from browser rendering capacity on that test machine;
it does not distinguish Python scheduling from container CPU throttling without additional process metrics.

Prediction now returns already accepted integrator endpoints without a redundant zero-duration RK4 calculation.
Its worker yields for 1 ms after approximately 5 ms of work so live simulation and socket delivery get scheduling
opportunities. This wall-time pacing leaves physics steps and work limits intact, and counts against the existing
0.8-second prediction budget. Tests compare complete trajectories and energy accounting and verify source immutability
and honest truncation when the wall-time budget is exhausted.

The primary plan/satellite display interpolates received ship, tug and attachment geometry with a 120 ms presentation
buffer, targeting 30–60 visible updates per second. It holds at the last received state and resets the buffer across
feed gaps above 250 ms, scene/run changes and unavailable or invalid states. Pausing or disconnecting stops the
animation. Authoritative clocks, force values, validity, command feedback and forecast clipping keep using the newest
received evidence. This does not increase the integration frequency or invent a trajectory between future forecast
samples. The separate Cesium and sectional views retain their authoritative update behavior.

Forecast refresh is driven by changed state, with at most one request in flight and up to one automatic request per
second. An unchanged paused snapshot does not repeatedly calculate the same forecast. Background work retains a
still-current result and does not toggle the headline or disable Preview. A new draft preview supersedes queued intent;
it does not launch overlapping server work. Sent orders wait for backend acknowledgement before a replacement forecast
is accepted. While paused, Start/Resume applies queued orders; Preview can inspect an unsent draft before Apply.
The map keeps the user's viewport stable until an explicit Fit action or a new scene/run.

Independent local browser acceptance measured 58.77 actual ship-polygon updates per second with predictions both on
and off, with a 16.8 ms p95 geometry-update interval. All 1,872 sampled centers stayed within the envelope of same-run
authoritative positions already received. Paused intervals and a settled withheld-frame gap produced zero geometry
updates; no browser exceptions occurred. These checks measure changing hull geometry, rather than merely counting
animation callbacks. The PR records final CI and the deployment comparison on the existing tier.

These are workload-specific observations, not capacity guarantees. Acceptance for the responsiveness fix must measure
actual displayed ship movement as well as animation callbacks, preserve forecast expiration and snapshot identity,
and repeat the target stream comparison before recommending more compute.
