# Port transit simulation (S6)

Status: implemented, **unqualified surrogate**. Ships enter or leave port along lat/lon routes under their own propulsion or with
tugs; several vessels share one clock. Code: `modeling/mooring/transit/`; API: `modeling/modeling_api/routers/transit.py`;
contract: `modeling/mooring/core/schemas/transit.py`; tests: `modeling/tests/test_s6_*.py`.

**What this is not.** There are no qualified maneuvering, propulsion, rudder or tug data for any ship in the repository. Every
coefficient below is either a published regression applied outside its calibration evidence for these hulls, or a labeled assumption.
The model is for planning visualization and storyboard replay, not for navigation, pilotage or safety decisions. Presets are
demonstration routes (approximate coordinates, not charted channels).

## 1. Conventions (as in the schema)

Body +x forward, +y port, +z up; yaw rate r positive counterclockwise (turning to port). Headings/courses are true bearings
clockwise from north. Local plane x = east, y = north. Rudder positive turns the bow to port. Wind FROM, current TOWARD. Engine
order -1..1. SI internally; feet, knots, lbf and ft-lbf at the API boundary.

Verified, not assumed: `compute_loads` returns wind force in these body axes (a wind from the starboard beam gives +sway, wind from
the bow gives negative surge); `test_s6_dynamics.py::test_wind_from_starboard_beam_pushes_ship_to_port_in_body_axes` pins it.

## 2. Model

### 2.1 Geometry (`geo.py`)
Local tangent plane at the request origin: `east = (lon - lon0) N cos(lat0)`, `north = (lat - lat0) M` with WGS84 prime-vertical radius
N and meridional radius M at the origin latitude. Round trip is exact to float precision. Versus an exact ECEF East-North-Up conversion
(37 N, worst case over all bearings): 1.7 m at 5 km, 6.8 m at 10 km, 27 m at 20 km, 108 m at 40 km (about 0.27 %; quadratic in range,
dominated by the variation of cos(lat) with the north offset). The 40 km limit is a validity reason (`GEO_TANGENT_PLANE_RANGE`), not a rejection.

### 2.2 Rigid body and added mass (`hull.py`)
m = displacement_lt x 1016.047 kg (catalog loading condition). Iz = m (0.25 L)^2 and xG = 0 (labeled). Equations, water-relative u, v, r:

    (m - X_udot) du/dt                 = X + m v r                 X_udot = -0.05 m (labeled)
    (m - Y_vdot) dv/dt - Y_rdot dr/dt  = Y - m u r
    -N_vdot dv/dt + (Iz - N_rdot) dr/dt = N

Sway and yaw are solved together as a 2x2 system (Y_rdot, N_vdot kept). Only rigid-body Coriolis terms appear because the Clarke linear
derivatives already contain the Munk moment (adding the separate (Y_vdot - X_udot) u v term would double count).

### 2.3 Hull forces (`hull.py`)
Clarke, Gedling and Hine (1983), L = LWL, B, T = mean draft of the loading, Cb, with
`Y'v = -pi (T/L)^2 [1 + 0.40 Cb B/T]`, `Y'r = -pi (T/L)^2 [-1/2 + 2.2 B/L - 0.080 B/T]`, `N'v = -pi (T/L)^2 [1/2 + 2.4 T/L]`,
`N'r = -pi (T/L)^2 [1/4 + 0.039 B/T - 0.56 B/L]`, and added mass `Y'vdot = -pi (T/L)^2 [1 + 0.16 Cb B/T - 5.1 (B/L)^2]`,
`Y'rdot = -pi (T/L)^2 [0.67 B/L - 0.0033 (B/T)^2]`, `N'vdot = -pi (T/L)^2 [1.1 B/L - 0.041 B/T]`,
`N'rdot = -pi (T/L)^2 [1/12 + 0.017 Cb B/T - 0.33 B/L]`. Dimensionalised with 1/2 rho L^k U^n, U = sqrt(u^2 + v^2) floored at 0.25 m/s
(numerical). Sign check: the published set is in the SNAME frame (y starboard, yaw clockwise). Flipping both the y axis and the yaw
sense leaves every linear derivative and added-mass coefficient unchanged, so they are used as published (the rudder is not invariant
and is derived separately, section 2.5). The regressions were fitted to merchant hulls; their applicability to slender warships is not
established here.

Low-speed damping: cross-flow drag by strip integration over the length, `Y = -1/2 rho Cd T sum (v + x r)|v + x r| dx`, `N = sum x dY`,
Cd = 0.8, 20 strips (labeled). It is always on, so it double counts a little damping with the linear terms at moderate drift.

Resistance: `R(u) = 1/2 rho S C_T u|u|`, S = 1.7 L T + V/T (Mumford), `C_T = (1+k) C_F + C_A` with C_F from ITTC-57 at Re = U L / nu,
k = 0.15, C_A = 0.0004 (labeled). **Wave-making resistance is not modeled**, so the resistance curve is friction-dominated; acceleration
and coast-down times are consequences of this and of the calibration below, not predictions.

### 2.4 Propulsion (`propulsion.py`)
Commanded thrust = order x T_max ahead, order x astern_fraction x T_max astern. T_max is calibrated so that calm deep-water steady speed at
full ahead equals max_speed_kt: T_max = R(max_speed). Delivered thrust is an integrated state, `dT/dt = (T_cmd - T)/tau_e`. Defaults for
max_speed_kt are public nominal figures (DDG-51 30, CG-47 30, LHD-1 22, CVN-68 30 kt), "public nominal maximum, not a trial result". A class
with no default and no supplied value is a 422. When an environment is supplied the apparent-wind drag of the ship's own motion is an
extra force, so the realized maximum is slightly below max_speed_kt (calibration is for calm, no-wind water). Initial delivered thrust
is set to R(start speed) (the ship starts in force equilibrium).

### 2.5 Rudder (`propulsion.py`)
Area `A_R = (T L / 100)(1 + 25 (B/L)^2)` (DNV guidance), aspect ratio 1.5, lift slope `f_a = 6.13 L/(2.25 + L)` (Fujii), effective angle clamped at
30 deg (stall, labeled). Inflow: `u_a = (1-w) u`, w = 0.2; propeller race by actuator-disc momentum theory, `u_s = sqrt(max(u_a,0)^2 + 2T+/(rho A_D))`,
D = 0.6 T, `u_R = u_a + 0.7 (u_s - max(u_a,0))`, so the rudder works at low speed with the engine ahead and is weak when stopped or astern.
Lateral inflow `v_R = 0.5 (v + x_R r)`, x_R = -0.5 L. `alpha = delta sgn(u_R) + atan2(v_R, |u_R|)`, `F_N = 1/2 rho A_R f_a sin(alpha) U_R^2`, and
MMG-style `X = -(1-t_R) F_N sin(delta)`, `Y = -(1+a_H) F_N cos(delta)`, `N = -(x_R + a_H x_H) F_N cos(delta)` with a_H = 0.25, x_H = -0.4 L, t_R = 0.28.
For delta > 0 the force is toward starboard acting aft: bow to port, N > 0 (tested for sign and exact mirror symmetry). Rate limit and maximum angle
come from `PropulsionAssumptions` (defaults 2.33 deg/s and 35 deg). The rudder angle is updated once per step by the rate limiter.

### 2.6 Bow thruster
If `bow_thruster_lbf` is set: lateral force at +0.4 L, linearly fading to zero at 3 m/s of surge speed, 5 s slew (labeled). Its command supplies the
same yaw-moment deficit that tugs would (section 4), in any mode.

### 2.7 Wind and current
Wind: the apparent wind (true wind, after the loads module's basis conversion, minus ship ground velocity, both in ENU) is passed to `compute_loads`
with a snapshot whose current is zero and depth 1000 ft (deep), `use_gust=False`; only the wind component is used, already in body axes. The apparent
speed is divided by the basis factor so the loads module's sustained-to-30 s conversion lands on the intended speed. Held constant over a step.
Current: the water moves at the environment current (TOWARD bearing); dynamics use water-relative velocities and kinematics add the current:
east/north = R(heading)(u, v) + current. No environment means explicit calm (labeled `CALM_ASSUMED`): no wind (also none from own motion) and still water.

### 2.8 Integration and clock
Fixed-step RK4 at dt_s for every vessel on one shared clock. Position, heading, u, v, r and delivered thrust are integrated states. Rudder angle, tug
and thruster force vectors, the wind wrench and the autopilot commands are updated once per step and held across the RK4 stages (zero-order hold), so the scheme
is first order in dt overall (measured below). A vessel never reads another vessel's state. Output frames every `sample_interval_s` (default 2 s, rounded to a
multiple of dt); the run stops early when every vessel has arrived, stopped short or failed (duration_s is a maximum).

## 3. Autopilot (`autopilot.py`)
Line-of-sight guidance on the current leg, `chi_d = chi_track + atan(e/Delta)`, Delta = lookahead_ship_lengths x L, e the cross-track (+ port). Leg switch inside the acceptance radius
(default 2 L) or after passing the waypoint's perpendicular. Crab: `psi_cmd = chi_d - beta`, beta a 30 s low-pass of (COG - heading) when SOG > 0.5 m/s. Heading PD(+I):
`delta = Kp (e - Td r) + Kp/Ti integral(e)`, Kp = 1.5, Td = clamp(L/U, 8, 60) s, Ti = 400 s, integral limited to 3 deg, active only when |e| < 0.2 rad and u > 2 m/s
(heuristics scaled from L/U; not tuned to any real autopilot). Speed: order = v_target/v_max + (v_target - u)/(2 kt) clamped to +-1 (no speed integrator, so a
fraction-of-a-knot bias remains because the feedforward is linear while drag is quadratic); the arrival ramp lowers v_target linearly with remaining distance over
`arrival_slowdown_nm`; astern is allowed only inside the arrival zone (remaining distance < slowdown distance or < 2 L). `arrived`: inside the final waypoint's radius with
speed through the water at most arrival_speed + 0.5 kt (0.5 kt for the default zero arrival speed). `stopped_short`: speed through the water below 0.3 kt for more than 120 s
while the target speed is above 0.5 kt and the vessel is outside the final radius (not evaluated while a scripted engine order is active). `helm_commands`: per field, the latest
non-null value with t_s <= t overrides the autopilot and persists (there is no release; a null field leaves that control as it was). Events: waypoint_reached, arrived,
rudder_saturated, large_cross_track (> 0.5 L), stopped_short, tug_saturated, integration_failed.

## 4. Tugs (`tugs.py`, `simulator.py`)
Named hull points (LOA-based): bow (+0.45, 0), stern (-0.45, 0), port/starboard shoulder (+0.3, +-B/2), port/starboard quarter (-0.3, +-B/2). Direction is relative to the bow, clockwise
(0 ahead, 90 starboard, 180 astern, 270 port): body force F (cos th, -sin th); moment about midships `N = x Fy - y Fx`. Capacity is the catalog `bollard_pull_ahead_lbf` for any direction (labeled).
Delivered force vector slews toward the command at bollard/10 s (labeled). A tug that changes hull point restarts from zero force. Reported tug positions are the hull contact points;
**tug hulls, lines and their motion are not modeled.** Commands above bollard pull are clamped and emit `tug_saturated`.

Auto assist (mode `tug_assisted` with `tug_assist.policy = "auto"`; `tug_assist` null means manual commands only): below `assist_below_kt` of surge speed the first two tug ids act at the bow and
stern. The heading loop's desired yaw moment is `M = m33 (wn^2 e - 2 zeta wn r)`, wn = 0.03 rad/s, zeta = 1; the tugs supply `M - N_rudder` (only if it has the same sign as `M`) as a couple
(force = |M| / (0.9 LOA) each, opposite directions), plus a braking force `max(0, u - v_target) m11 / 20 s` split astern between them inside the arrival zone, vector-summed per tug and clamped to bollard pull.
A tug that has received a manual command is no longer driven by the auto policy. In the presets the rudder usually suffices for heading, so the tugs mainly brake.

## 5. Validity and assumptions in every response
`validity.state = "limited"` always (`invalid`/RED only on integration failure), with reasons `TRANSIT_SURROGATE_MANEUVERING`, `PROPULSION_ASSUMED`, `DEEP_WATER_NO_SQUAT_OR_BANK`,
`NO_SHIP_INTERACTION`, plus `TUG_KINEMATICS_NOT_MODELED` (any tug-assisted vessel), `CALM_ASSUMED` (no environment), `SYNTHETIC_EPOCH` (no start_utc: tracks count from 2000-01-01T00:00:00Z so they
still fit the S5 `TrackFix` format), `GEO_TANGENT_PLANE_RANGE` (> 40 km). No squat, shallow water, bank effect, ship-ship interaction, UKC, waves, wave-making resistance, propeller side force,
rudder-propeller interaction beyond the race term, or tug hull kinematics. Backend `real`, status AMBER. `manifest.resolved_inputs_hash` covers the request, the catalog records
actually used, the origin and the coefficient table; the same request gives an identical series.

## 6. Coefficient register
| Item | Value / form | Source | Status |
|---|---|---|---|
| Mass m | displacement_lt x 1016.047 kg | ship catalog loading condition | PUBLISHED catalog value (itself an estimate) |
| Yaw inertia Iz | m (0.25 L)^2 | common radius-of-gyration rule of thumb | ASSUMED |
| Longitudinal CG xG | 0 (midships) | simplification | ASSUMED |
| Surge added mass X_udot | -0.05 m | common naval-architecture rule of thumb | ASSUMED |
| Sway/yaw added mass and cross derivatives Y_vdot, Y_rdot, N_vdot, N_rdot | Clarke et al. regressions | Clarke, Gedling & Hine (1983), Trans. RINA 125 | PUBLISHED regression (hull-form range not checked for these ships) |
| Linear derivatives Y_v, Y_r, N_v, N_r | Clarke et al. regressions in L=LWL, B, T, Cb | Clarke, Gedling & Hine (1983) | PUBLISHED regression |
| U floor in dimensionalisation | 0.25 m/s | numerical | NUMERICAL |
| Cross-flow drag Cd | 0.8, 20 strips | Hoerner-type flat-plate value for a ship section | ASSUMED |
| Wetted surface S | 1.7 L T + V/T | Mumford (1965) | PUBLISHED regression |
| Friction line C_F | 0.075/(log10 Re - 2)^2 | ITTC-57 | PUBLISHED |
| Form factor (1+k) | 1.15 | typical slender-hull range 1.1-1.3 | ASSUMED |
| Allowance C_A | 0.0004 | typical 0.0002-0.0006 | ASSUMED |
| Wave-making resistance | not modeled | omitted | LIMITATION |
| Kinematic viscosity / water density | 1.19e-06 m2/s / environment value or 1025.0 kg/m3 | seawater ~15 C | ASSUMED |
| Max speed (calibrates T_max) | 30 kt DDG-51, CG-47, CVN-68; 22 kt LHD-1 | public nominal maximum speed | ASSUMED; not a trial result |
| Astern thrust fraction | 0.6 default (request) | request value | ASSUMED |
| Engine time constant | 20 s default (request) | request value | ASSUMED |
| Wake fraction w | 0.2 | typical 0.1-0.3 | ASSUMED |
| Propeller diameter D | 0.6 T | typical 0.5-0.7 T | ASSUMED |
| Race fraction at rudder | 0.7 | between disk (0.5) and fully contracted slipstream (1.0) of momentum theory | ASSUMED |
| Rudder area A_R | (T L/100)(1 + 25 (B/L)^2) | DNV rule guidance for rudder area | PUBLISHED guidance, used as a size estimate |
| Rudder aspect ratio | 1.5 | typical | ASSUMED |
| Rudder lift slope | f_a = 6.13 L/(2.25 + L) | Fujii (1960) as used in the MMG standard method (Yasukawa & Yoshimura 2015) | PUBLISHED |
| Rudder stall angle | 30.0 deg clamp on effective angle | typical | ASSUMED |
| Rudder max angle / rate | 35 deg / 2.33 deg/s defaults (request) | steering-gear criterion 35 to 30 deg in 28 s | ASSUMED |
| a_H, x_H, t_R, x_R, gamma_R | 0.25, -0.4 L, 0.28, -0.5 L, 0.5 | MMG standard form (Yasukawa & Yoshimura 2015), typical magnitudes | ASSUMED values |
| Bow thruster | at +0.4 L, fade to 0 at 3.0 m/s, slew 5.0 s | typical | ASSUMED |
| Tug capacity | bollard_pull_ahead_lbf of the catalog tug, any direction | tug catalog (rough rules of thumb) | ASSUMED |
| Tug slew | 10.0 s from zero to full pull | typical | ASSUMED |
| Wind | UFC 4-159-03 loads on the apparent wind; sustained-to-30 s conversion applied by the loads module | UFC 4-159-03 | PUBLISHED, with deep-water/zero-current snapshot |

## 7. Presets (`GET /transit/presets`)
All four are demonstration routes: the approach-mock waypoints (copied, since the architecture check forbids importing mock code) and a point 250 ft off the NAVSTA Norfolk Pier 12 north face
(from the berth catalog), final acceptance radius 300 ft. Not navigational advice; not charted channels.

| Preset | Vessel(s) | Result (dt 0.2 s) |
|---|---|---|
| ddg-inbound-own-thrust | DDG-51 from Thimble Shoal entrance, 10 to 12 kt legs, 0.5 nm slowdown | arrives 4656 s, 13.67 nm, max cross-track 91 ft, max rudder 3.6 deg |
| ddg-inbound-tug-assisted | same, auto assist below 5 kt with T1 (bow) and T2 (stern) | arrives 4678 s, max tug force 11.9 klbf (braking) |
| ddg-outbound-own-thrust | DDG-51 from the pier area to the entrance (10 kt), from rest | arrives 4769 s, 13.54 nm |
| two-vessels | DDG-51 inbound + CG-47 outbound on offset lanes | DDG arrives 4662 s, CG arrives 4759 s |

## 8. Benchmarks (all offline; `uv run --all-packages pytest -q modeling/tests/test_s6_*.py -s` prints the numbers)

| Benchmark | Result |
|---|---|
| Lat/lon round trip | exact to 1e-6 m over +-40 km at four latitudes |
| Tangent-plane error vs exact ENU (37 N) | 1.7 / 6.8 / 27 / 108 m at 5 / 10 / 20 / 40 km |
| Steady speed at full ahead (calibration check) | DDG-51 30.000 kt, CG-47 30.000, LHD-1 22.000, CVN-68 30.000 (limit +-2 %); supplied 24 kt gives 24 kt +-2 % |
| 63 % rise (DDG, step from 95 % to 100 % speed) | simulated 126.0 s vs 123.2 s from the independent two-lag linear model (hull tau = m11 / (dR/du) = 101.6 s, engine tau 20 s); limit +-6 % |
| Zero rudder, calm | v = r = 0 and track exactly straight |
| Rudder sign and mirror symmetry | +35 deg turns to port, -35 to starboard; tracks are exact mirror images (1e-6 ft); yaw rate sign matches rudder |
| Turning circle, 35 deg from full speed, tactical diameter / LWL | DDG-51 7.21 (advance 2.00 L, speed falls to 16.4 kt, steady 1.10 deg/s); LHD-1 4.69; CVN-68 4.89; **CG-47 8.80, outside the 2-8 band** (recorded as a strict xfail) |
| Small rudder step (2 deg at ~15 kt) | monotone first-order-like yaw rate; steady 0.085 deg/s, 63 % time 11.0 s; values at 2T and 3T within 0.08 of 0.865 and 0.95 |
| Engine stop | monotonically decelerating; matches a separately coded integration of u' = -R/m11 with thrust decay within 0.5 % |
| Zero thrust in a 2 kt current (toward 090) | over-ground speed 2 kt within 2 % (the drifting hull feels the apparent wind: about 1 % retardation), course 090 +-1 deg, position change equals current x time within 2 % |
| Balanced sway push (two tugs +-0.3 LOA) | zero tug moment, yaw rate 0 at t = 0; sway to starboard; yaw after 10 s is 0.10 of the rate from the same force at the bow, caused by Clarke cross-coupling (N_v, Y_rdot, N_vdot), not by a tug moment |
| Bow tug push to port | moment = 0.45 LOA x force, yaw CCW; stern push to port yaws CW |
| Tug bollard limit | delivered force never exceeds the catalog bollard pull; saturation event emitted; slew linear at bollard/10 s |
| Auto assist, engine stopped, 90 deg turn to a waypoint | tugs only, source auto_assist, force <= bollard; heading 273.5 deg after 400 s (target ~270) |
| Multi-vessel independence | vessel A frames identical alone, with B, and with B listed first |
| Determinism | same request gives identical series and resolved hash |
| Time step | position error vs dt 0.05 s after a 400 s turn: 13.0 ft at dt 0.5 s, 4.4 ft at dt 0.2 s (of ~3000 ft), first-order convergence |
| Presets | all four arrive within their durations |
| API | POST simulate -> job succeeded -> series -> summaries; 422 for own_thrust with tug commands, unknown tug/class, missing speed basis, duplicate vessel ids |

Runtime (CPython 3.12, one thread, Apple silicon laptop, dt 0.2 s): 0.32 s wall per simulated vessel-hour with default 2 s frames (0.28 s with 60 s frames); 4 vessels 1.25 s for 3600 s
(0.31 s per vessel-hour); with wind, current and auto assist 0.49 s per vessel-hour.

## 9. Known limits and findings
* Turning circles are large: the Clarke/DNV/Fujii chain gives TD/L = 7.2 for the DDG-51 and 8.8 for the CG-47 at 35 deg rudder from full speed. Real warships of these classes are commonly
  quoted well below that; no data in the repository can confirm or correct it. The test band (2-8) is kept for the DDG, LHD and CVN, and the CG-47 miss is an explicit strict xfail rather than a retuned coefficient.
* No wave-making resistance: friction-dominated drag calibrated to a nominal top speed gives plausible steady speeds but unverified acceleration/deceleration times.
* Single equivalent propeller and rudder for twin-screw ships; no propeller side force or rudder-induced loss of speed beyond the MMG drag term.
* Autopilot gains are heuristics; speed tracking has a small bias; arrival uses speed through the water.
* The autopilot hands off to tugs on surge speed through the water only.
