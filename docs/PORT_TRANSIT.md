# Port transit simulation (S6)

Status: implemented, **unqualified surrogate**. Ships enter or leave port along lat/lon routes under their own propulsion or with
tugs; several vessels share one clock. Code: `modeling/mooring/transit/`; API: `modeling/modeling_api/routers/transit.py`;
contract: `modeling/mooring/core/schemas/transit.py`; tests: `modeling/tests/test_s6_*.py`.

**What this is not.** There are no qualified maneuvering, propulsion, rudder or tug data for any ship in the repository. Every
coefficient below is either a published regression applied outside its calibration evidence for these hulls, or a labeled assumption.
The model is for planning visualization and storyboard replay, not for navigation, pilotage or safety decisions. Presets are
demonstration routes (checked only against the OSM coastline, see section 7; not charted channels).

**Prominent limitation: thrust is likely 2 to 4 times too low.** T_max is the friction-only resistance at the nominal top speed (no wave-making or residuary resistance), so the calibrated
thrust, and with it acceleration, deceleration and astern stopping authority, are probably well below the real ships'. Cross-check against approximate public shaft power (DDG-51 ~100 000 shp, CG-47 ~80 000, LHD-1 ~70 000, CVN-68 ~260 000, labeled approximate):
the model's effective power T_max x v_max is 12.5, 14.1, 12.1 and 52.9 MW, i.e. 17 to 27 % of shaft power, against a typical propulsive efficiency of 50 to 65 %, so thrust is about 2 to 4 times low.
Consequence: runs accelerate, slow down and stop too sluggishly (the CVN needs about 1 km to stop from 12 kt on astern thrust alone, and the arrival planner has to start slowing earlier); steady speeds, turning
circles at constant speed and the rudder are not affected by T_max, but speed loss in a turn and any "can it stop in time" conclusion are. No residuary resistance was invented to correct this (a Holtrop-Mennen
estimate would need hull-form data not in the catalog); it stays a documented limitation.

**Intended use (S7).** This model is intended to serve as the open-water predictor for the "backup camera" view (S7): from a vessel's current
state and conditions, predict where it will be over the next minutes. The stepping core is therefore callable without a route:
`simulator.predict_constant_commands(vt, env, horizon_s, rudder_deg, engine_order)` holds commands constant from an arbitrary initial state
(it loops over `Vessel.advance`, the physics half of a step), keeps no global state (concurrent predictions are independent) and is deterministic;
a 10-minute, one-vessel, dt 0.2 s prediction takes about 0.06 s of wall time.

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
Clarke, Gedling and Hine (1983), L = LWL, B, T = mean draft of the loading, Cb (see below), with
`Y'v = -pi (T/L)^2 [1 + 0.40 Cb B/T]`, `Y'r = -pi (T/L)^2 [-1/2 + 2.2 B/L - 0.080 B/T]`, `N'v = -pi (T/L)^2 [1/2 + 2.4 T/L]`,
`N'r = -pi (T/L)^2 [1/4 + 0.039 B/T - 0.56 B/L]`, and added mass `Y'vdot = -pi (T/L)^2 [1 + 0.16 Cb B/T - 5.1 (B/L)^2]`,
`Y'rdot = -pi (T/L)^2 [0.67 B/L - 0.0033 (B/T)^2]`, `N'vdot = -pi (T/L)^2 [1.1 B/L - 0.041 B/T]`,
`N'rdot = -pi (T/L)^2 [1/12 + 0.017 Cb B/T - 0.33 B/L]`. Dimensionalised with 1/2 rho L^k U^n, U = sqrt(u^2 + v^2) floored at 0.25 m/s
(numerical). Sign check: the published set is in the SNAME frame (y starboard, yaw clockwise). Flipping both the y axis and the yaw
sense leaves every linear derivative and added-mass coefficient unchanged, so they are used as published (the rudder is not invariant
and is derived separately, section 2.5). The regressions were fitted to merchant hulls; their applicability to slender warships is not
established here.

Block coefficient. The catalog Cb is kept unless it differs by more than 20 % from `m / (rho L B T)` (rho 1025, the catalog draft). Result: DDG-51 catalog 0.51 vs
displacement-derived 0.355 (replaced), CG-47 0.47 vs 0.357 (replaced), LHD-1 0.58 vs 0.637 (kept), CVN-68 0.62 vs 0.679 (kept). The catalog draft may include the
sonar dome, which would inflate T and lower the derived Cb; the catalog cannot distinguish a hull draft from the dome-inclusive one, so the catalog draft is used and
this is stated, not resolved. Effect on the turning circles: see section 8.

**Linear stability (reported, not hidden).** Clarke's linear stability index (det of the hull's linear sway-yaw matrix at speed U) is **negative for LHD-1 and CVN-68**
(hull alone: course-unstable, c = -4.3e13 and -1.0e15 at 8 kt) and positive for DDG-51 and CG-47 (1.7e15, 3.9e15). With the rudder held amidships in the loop
(the rudder's lateral-velocity term `v_R` adds sway and yaw damping) all four are stable in the linearised model (7.2e15 for LHD-1, 4.1e16 for CVN-68), but that stabilisation
rests on the assumed `gamma_R`, race and area values. `nomoto.py` reports both indices (`Linear.c_hull`, `Linear.c_total`).

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

Twin rudders. The four catalog classes are twin-screw ships with two rudders (public configuration; `RUDDER_COUNT` in `coefficients.py`, one rudder for any other class).
`A_R` above is the area PER rudder (DNV guidance); the equivalent rudder is `count x A_R`, each rudder sitting in its own propeller race, so the thrust used for the race
is `T / count` per rudder and the force is `count x` the single-rudder force. A twin arrangement therefore gives about 1.4 x (not 2 x) the side force of one rudder at the same
total thrust and speed (each race is slower). This replaced the single equivalent rudder at the minimum DNV area that the review identified as the cause of the large turning circles.

### 2.6 Bow thruster
If `bow_thruster_lbf` is set: lateral force at +0.4 L, linearly fading to zero at 3 m/s of surge speed, 5 s slew (labeled). Its command supplies the
same yaw-moment deficit that tugs would (section 4), in any mode.

### 2.7 Wind and current
Wind: the apparent wind (true wind, after the loads module's basis conversion, minus ship ground velocity, both in ENU) is passed to `compute_loads`
with a snapshot whose current is zero and depth 1000 ft (deep), `use_gust=False`; only the wind component is used, already in body axes. The apparent
speed is divided by the basis factor so the loads module's sustained-to-30 s conversion lands on the intended speed. Held constant over a step.
Current: the water moves at the environment current (TOWARD bearing); dynamics use water-relative velocities and kinematics add the current:
east/north = R(heading)(u, v) + current. No environment means explicit calm (labeled `CALM_ASSUMED`): zero true wind and still water. It is handled as a zero-wind, zero-current snapshot, so the
air drag of the ship's own motion (apparent wind) is still applied and `environment = null` gives exactly the same series as an explicit zero-wind environment of the
same water density (tested). A calm run's steady speed is therefore a little below the calibration speed (CG-47 29.4 kt at a 30 kt calibration).

### 2.8 Integration and clock
Fixed-step RK4 at dt_s for every vessel on one shared clock. Position, heading, u, v, r and delivered thrust are integrated states. Rudder angle, tug
and thruster force vectors, the wind wrench and the autopilot commands are updated once per step and held across the RK4 stages (zero-order hold), so the scheme
is first order in dt overall (measured below). A vessel never reads another vessel's state. Output frames every `sample_interval_s` (default 2 s) at exactly the requested times: the step is
`dt_eff = sample / ceil(sample / dt) <= dt` (a dt that does not divide the interval is shortened, never lengthened; the manifest reports `dt_s` = dt_eff and `dt_requested_s`).
Frames are at k x sample for every k with k x sample <= duration_s (no off-grid last frame). The run stops early only when every vessel has arrived, stopped short or failed,
and then at the next frame time. Forces are evaluated before frame 0 (and re-evaluated at each frame so the reported wind force belongs to the reported state).
An **arrived vessel is no longer integrated**: its state is frozen at the arrival step (status `arrived`; the berthing simulation takes over from there) while the other vessels continue.
Vessels that stop short keep being integrated.

## 3. Autopilot (`autopilot.py`, `nomoto.py`)

**Guidance.** Line of sight on the current leg, `chi_d = chi_track + atan(e/Delta)`, Delta = lookahead_ship_lengths x L (default 2 L), e the cross-track (+ port). Leg switch inside the
acceptance radius (default 2 L) or after passing the waypoint's perpendicular. The cross-track loop pole is U/Delta and the heading loop frequency below is wn = 2.5 U/L, so both scale
with U/L: the ratio (wn Delta / U = 5 at the default) is the same at every speed, which is the speed/length scaling of the lookahead. (With wn = 1.5 U/L the ratio was 3 and the cross-track
loop of the large ships oscillated for 40 minutes; 2.5 removes it. This is a design choice checked by the benchmark below, not ship data.)

**Heading controller, from each vessel's own linearised dynamics.** `nomoto.linearise` linearises the sway-yaw equations about steady ahead motion at speed U with the thrust that balances resistance,
using the hull derivatives (`U yv`, `U yr L`, `U nv`, `U nr L`, the Clarke added-mass matrix M) plus central finite differences of the actual rudder model (race, wake, MMG interaction, rudder count)
for `dY/dv, dY/dr, dY/ddelta` and the same for N. With `M x' = A x + b delta`, x = (v, r), the transfer function from rudder to yaw rate is `(n1 s + n0)/(a s^2 + b1 s + c)`, c = det A, and
the first-order Nomoto approximation (`T r' + r = K delta`) is `K = n0/c`, `T = b1/c - n1/n0`. K and T are tabulated per vessel on a 1 kt speed grid and interpolated (gain scheduling).
At 8 kt: DDG-51 K 0.029 1/s, T 21 s; CG-47 0.019, 18 s; LHD-1 0.032, 93 s; CVN-68 0.025, 137 s (K' = K L/U 1.0, 0.77, 1.9, 1.9; T' = T U/L 0.60, 0.47, 1.6, 1.8). K is checked against the simulated
steady yaw rate of a 1 degree rudder step (within 12 %: DDG 2 %, CG 1 %, LHD 11 %, CVN 12 %, the difference being the nonlinear cross-flow drag and the neglected sway coupling in the first-order reduction).
With theta the CCW heading, `T theta'' + theta' = K delta`; the law `delta = Kp e - Kd r + Ki int e` gives the closed loop `T s^2 + (1 + K Kd) s + K Kp = 0`, and placing the poles at (wn, zeta = 0.9) gives

    Kp = T wn^2 / K,   Kd = (2 zeta wn T - 1) / K,   wn = 2.5 U_s / L,   U_s = max(|u|, 2.5 kt).

The expressions are valid for a course-unstable hull: T < 0 and K < 0 give Kp > 0 and Kd > 0 (unit-tested with a synthetic unstable model). For a stable hull wn is raised if needed so that Kd >= 0.5/K.
A small integral term (Ki = Kp wn/10, clamped to 3 deg of rudder, active only for |e| < 0.2 rad at u > 2 m/s) removes steady bias. Astern (u < -0.3 m/s) the rudder command is inverted; the Nomoto
model is not valid there and heading is held only roughly. The pole placement ignores the rudder rate limit and the second (sway) pole; the benchmark below is the check.

**Crab compensation.** `psi_cmd = chi_d - beta`, beta a 30 s low-pass of the drift angle COG - heading, applied only when STW u > max(3 kt, 2 x current speed), clamped to +-20 deg, decaying to zero
otherwise, and never computed from COG - heading when moving astern. The current is estimated as ground velocity minus water velocity (GPS minus log).

**Speed and arrival, over ground.** On a normal leg: order = v_t/v_max + (v_t - u)/(2 kt) (v_t is the leg speed through the water; linear feedforward against quadratic drag leaves a fraction-of-a-knot bias).
In the arrival zone (within `arrival_slowdown_nm` of the end, or 2 L) the target is the along-track speed over ground g_t: a linear ramp from max(v_fin + c_t, arrival speed) to the arrival speed (c_t the
along-track current estimate, so the ramp is continuous at its start), additionally limited by the constant-deceleration profile `sqrt(v_arr^2 + 2 a_plan d)` with `a_plan = 0.7 x astern_fraction x T_max / m11`
(a planning margin, labeled ASSUMED; when the ship cannot decelerate as fast as the linear ramp requires the ramp starts earlier than `arrival_slowdown_nm`). The engine order is
`(g_t - c_t)/v_max + (g_t - g)/(2 kt)` with g the measured along-track ground speed, so the controller delivers the required ground progress: STW above g_t in a foul current, negative (astern) in a fair one.
`arrived`: inside the final waypoint's radius with **SOG** <= arrival speed + 0.5 kt. If the vessel passes the final waypoint's perpendicular outside the radius it emits `missed_approach`
(new event kind, additive to the schema) and re-approaches on a new leg from where it is to the waypoint with its speed capped at 6 kt; this can repeat. `stopped_short`: SOG below 0.3 kt for more than
120 s outside the radius while the ground-speed target exceeds 0.5 kt (not evaluated while a scripted engine order is active) - evaluated on SOG and distance, not speed through the water.
`helm_commands`: the latest command with t_s <= t defines both controls; a null field returns that control to the autopilot (a later command that omits `rudder_deg` releases a held rudder, and one that omits `engine_order`
releases the engine). Events: waypoint_reached, arrived, missed_approach, rudder_saturated, large_cross_track (> 0.5 L), stopped_short, tug_saturated, integration_failed.
`max_cross_track_ft` excludes the leg-switch corner: while inside the corner waypoint's acceptance radius or less than one lookahead distance along the new leg, the smaller of the distances to the previous and
the current leg line is used (so the swing around a turn is not counted as cross-track error).

**Arrival in current (DDG-51 unless noted; 12 kt approach, 0.5 nm slowdown, 300 ft radius, arrival speed 0):**

| Case | Before | After |
|---|---|---|
| 2 kt foul along the final leg | never arrived: stalled 477 ft short at SOG 0, STW 2 kt, no event | arrives at 1310 s, SOG 0.50 kt, STW 2.50 kt |
| 3 kt fair | "arrived" at SOG 3.5 kt (judged on STW 0.5 kt) | arrives at 878 s, SOG 0.50 kt, STW -2.50 kt (astern) |
| CVN-68, 3 kt fair | drifted away silently at 3 kt, 13 000 ft past the point | arrives at 895 s, SOG 0.50 kt, STW -2.50 kt |
| CVN-68, calm | stalled 689 ft short, no event | arrives at 1003 s (the planner starts slowing earlier than 0.5 nm) |
| 2 kt cross current, default 2 L radius | rudder pinned, drifted 6900 ft away | arrives (one missed approach and turn-around, rudder at its limit for under 150 s in total) |

Stopping over ground in a cross current without lateral thrust requires the ship to face the current, which the +-20 deg crab limit does not do; the autopilot only gets there through the missed-approach
re-approach, and with a 300 ft radius it may loop several times (DDG-51, 1 kt cross current: arrives after nine passes, 2845 s). Tugs or the bow thruster are the real answer and are not wired into the autopilot's lateral control.

**Heading/course benchmark** (`test_s6_fixes.py::test_sixty_degree_course_change_benchmark`, calm, 60 deg port course change onto a second leg, 2 L acceptance radius, 40 min, dt 0.2 s). Overshoot is measured against the
autopilot's own heading command (guidance course after LOS and crab), because the LOS term deliberately steers past the new leg bearing while the ship is off the new line; the overshoot against the new
leg bearing is also listed. "xt" is cross-track relative to the new leg: maximum |xt| in the first third and in the last third of the run (limits: last third < 20 % of the first and < 100 ft).

| Class | Speed | Overshoot vs command | Overshoot vs leg bearing | xt first third | xt last third |
|---|---|---|---|---|---|
| DDG-51 | 4 / 8 / 15 kt | 2.1 / 3.9 / 4.9 deg | 1.6 / 6.1 / 11.0 deg | 806 / 786 / 800 ft | 0.1 / 0.0 / 0.0 ft |
| CG-47 | 4 / 8 / 15 kt | 3.0 / 4.6 / 5.6 deg | 4.2 / 8.5 / 13.5 deg | 903 / 907 / 890 ft | 0.1 / 0.0 / 0.0 ft |
| LHD-1 | 4 / 8 / 15 kt | 3.1 / 4.3 / 5.6 deg | 3.0 / 5.9 / 10.7 deg | 1346 / 1345 / 1307 ft | 8.0 / 1.8 / 0.1 ft |
| CVN-68 | 4 / 8 / 15 kt | 2.7 / 3.8 / 5.1 deg | 2.4 / 4.7 / 8.5 deg | 1788 / 1776 / 1793 ft | 18.1 / 5.1 / 0.6 ft |

The overshoot against the new leg bearing exceeds 10 deg for DDG-51 and CG-47 at 15 kt (11.0, 13.5): this is the LOS geometry at a 2 L-radius corner (the ship is still about 0.9 L off the new line when it
switches, so atan(e/Delta) asks for more than the leg bearing), not a heading-loop overshoot. The pre-fix controller (fixed Kp 1.5, Td = L/U) was not benchmarked across classes.

## 4. Tugs and bow thruster (`tugs.py`, `simulator.py`)
Named hull points (LOA-based): bow (+0.45, 0), stern (-0.45, 0), port/starboard shoulder (+0.3, +-B/2), port/starboard quarter (-0.3, +-B/2). Direction is relative to the bow, clockwise
(0 ahead, 90 starboard, 180 astern, 270 port): body force F (cos th, -sin th); moment about midships `N = x Fy - y Fx`. Capacity is the catalog `bollard_pull_ahead_lbf` for any direction (labeled).
Delivered force vector slews toward the command at bollard/10 s (labeled). A tug that changes hull point restarts from zero force. Reported tug positions are the hull contact points;
**tug hulls, lines and their motion are not modeled.** Commands above bollard pull are clamped and emit `tug_saturated`.

Auto assist (mode `tug_assisted` with `tug_assist.policy = "auto"`; `tug_assist` null means manual commands only): below `assist_below_kt` of surge speed the first two tug ids act at the bow and
stern. The heading loop's desired yaw moment is `M = m33 (wn^2 e - 2 zeta wn r)`, wn = 0.03 rad/s, zeta = 1. **Allocation:** the deficit `M - N_rudder` (only if it has the same sign as `M`) goes first to the bow
thruster (if fitted; limited by its capacity and speed fade), and only the remainder is given to the tugs as a couple (force = |remainder| / (0.9 LOA) each, opposite directions), so the delivered moment is about the
demanded one instead of twice it (tested). The tugs also get a braking force `max(0, g - g_t) m11 / 20 s` (ground speed above the ramp target) split astern between them inside the arrival zone, vector-summed per tug and clamped to bollard pull.
When the speed is at or above `assist_below_kt` (or the policy is not auto) the auto-assist commands are set to zero (the forces slew down over 10 s) instead of keeping their last value. A tug that has received a
manual command is never driven by the auto policy. In the presets the rudder usually suffices for heading, so the tugs mainly brake.

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
| Rudder area A_R (per rudder) | (T L/100)(1 + 25 (B/L)^2) | DNV rule guidance for rudder area | PUBLISHED guidance, used as a size estimate |
| Arrival planning deceleration | 0.7 x astern_fraction x T_max / m11 (the arrival ramp is lengthened when the linear ramp would need more) | autopilot design choice (planning margin), not ship data | ASSUMED |
| Rudder count | 2 for DDG-51, CG-47, LHD-1, CVN-68; equivalent rudder = count x area, each in its own propeller race (thrust T/count per race) | public configuration, area per rudder from DNV guidance | ASSUMED (public configuration); one rudder for any other class |
| Block coefficient for the Clarke terms | catalog Cb, or m/(rho L B T) when the two differ by more than 20 % | displacement consistency check with the catalog draft (which may include the sonar dome; the catalog cannot distinguish) | DERIVED; DDG-51 0.51 -> 0.35, CG-47 0.47 -> 0.36, LHD-1 and CVN-68 keep catalog values |
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
All four are demonstration routes: **demonstration route checked only against OSM coastline; not a navigational route.** Waypoints: Thimble Shoal Channel entrance (36.995, -76.045), Thimble Shoal Channel (36.995, -76.160),
Hampton Roads (36.985, -76.270), Norfolk Harbor Entrance Reach (36.975, -76.315), off Sewells Point (36.969, -76.330), then a point 250 ft off the NAVSTA Norfolk Pier 12 north face (berth catalog),
final acceptance radius 300 ft. The earlier routes (copied from the approach mock) were wrong: the first two legs crossed OSM coastline ways (an artificial island at -76.114 and the Norfolk/Ocean View shore) and the last waypoints were on or at the shore.

Coastline check. `scripts/fetch_transit_coastline.py` queries the Overpass API for `natural=coastline` ways around Hampton Roads (36.88-37.05 N, 76.50-75.98 W) and for the Hampton Roads, Willoughby Bay and Elizabeth River water
relations, polygonizes the coastline (land on the left of each way), subtracts the water bodies, applies a 55 m morphological opening (removes slivers along OSM's closing line across the mouth of Hampton Roads),
simplifies to 8 m and writes `modeling/tests/fixtures/transit/hampton_roads_coastline.geojson` (49 kB; (c) OpenStreetMap contributors, ODbL 1.0, attribution and licence in the file's properties). OSM's `natural=coastline` ends at that closing line,
so the harbour behind it is only known through the water relations. `test_s6_presets_coastline.py` (offline) checks that no preset leg (any vessel, including the +-0.0007 deg offset lanes of the two-vessel preset) intersects the land polygon,
that every leg keeps at least 100 m clearance, and that the simulated tracks of the inbound and outbound presets never enter land. Clearances: 171 m minimum (leg ending off Sewells Point), 320 m to 2 km elsewhere.
Limits: the OSM Hampton Roads outline is a crude polygon near Sewells Point, so the Pier 12 point itself lies about 640 m inside the polygon's land; legs are exempt within 1000 m of that point. This is not a depth,
channel, bridge-tunnel or traffic check (the demonstration crosses the Hampton Roads Bridge-Tunnel alignment without any air or depth clearance consideration).

| Preset | Vessel(s) | Result (dt 0.2 s) |
|---|---|---|
| ddg-inbound-own-thrust | DDG-51 from Thimble Shoal entrance, 10 to 12 kt legs, 0.5 nm slowdown | arrives 4861 s, 14.53 nm, max cross-track 307 ft (corners excluded), max rudder 35 deg in the final turns |
| ddg-inbound-tug-assisted | same, auto assist below 5 kt with T1 (bow) and T2 (stern) | arrives 4884 s, max tug force 19.5 klbf (braking) |
| ddg-outbound-own-thrust | DDG-51 from the pier area to the entrance (10 kt), from rest | arrives 5067 s, 14.38 nm |
| two-vessels | DDG-51 inbound + CG-47 outbound on offset lanes | DDG arrives 4885 s, CG arrives 5044 s |

## 8. Benchmarks (all offline; `uv run --all-packages pytest -q modeling/tests/test_s6_*.py -s` prints the numbers)

| Benchmark | Result |
|---|---|
| Lat/lon round trip | exact to 1e-6 m over +-40 km at four latitudes |
| Tangent-plane error vs exact ENU (37 N) | 1.7 / 6.8 / 27 / 108 m at 5 / 10 / 20 / 40 km |
| Steady speed at full ahead (calibration check) | DDG-51 30.000 kt, CG-47 30.000, LHD-1 22.000, CVN-68 30.000 (limit +-2 %); supplied 24 kt gives 24 kt +-2 % |
| 63 % rise (DDG, step from 95 % to 100 % speed) | simulated 126.0 s vs 123.2 s from the independent two-lag linear model (hull tau = m11 / (dR/du) = 101.6 s, engine tau 20 s); limit +-6 % |
| Zero rudder, calm | v = r = 0 and track exactly straight |
| Rudder sign and mirror symmetry | +35 deg turns to port, -35 to starboard; tracks are exact mirror images (1e-6 ft); yaw rate sign matches rudder |
| Turning circle, 35 deg from full speed, tactical diameter / LWL (twin rudders, displacement-derived Cb) | before: DDG-51 7.21, CG-47 8.80 (strict xfail), LHD-1 4.69, CVN-68 4.89. **After:** DDG-51 **5.06** (advance 1.76 L, speed falls to 13.3 kt, steady 1.28 deg/s), CG-47 **5.87** (1.62 L, 14.7 kt), LHD-1 **3.93** (1.99 L, 5.6 kt), CVN-68 **4.09** (1.99 L, 8.0 kt); all inside the 2-8 band, so the CG-47 xfail is now an ordinary assertion |
| Small rudder step (2 deg at ~15 kt) | monotone first-order-like yaw rate; steady 0.125 deg/s, 63 % time 9.0 s; values at 2T and 3T within 0.08 of 0.865 and 0.95 |
| Engine stop | monotonically decelerating; matches a separately coded integration of u' = -R/m11 with thrust decay within 0.5 % |
| Zero thrust in a 2 kt current (toward 090) | over-ground speed 2 kt within 2 % (the drifting hull feels the apparent wind: about 1 % retardation), course 090 +-1 deg, position change equals current x time within 2 % |
| Balanced sway push (two tugs +-0.3 LOA) | zero tug moment, yaw rate 0 at t = 0; sway to starboard; yaw after 10 s is 0.10 of the rate from the same force at the bow, caused by Clarke cross-coupling (N_v, Y_rdot, N_vdot), not by a tug moment |
| Bow tug push to port | moment = 0.45 LOA x force, yaw CCW; stern push to port yaws CW |
| Tug bollard limit | delivered force never exceeds the catalog bollard pull; saturation event emitted; slew linear at bollard/10 s |
| Auto assist, engine stopped, 90 deg turn to a waypoint | tugs only, source auto_assist, force <= bollard; heading within 250-290 deg after 400 s (target ~270) |
| Multi-vessel independence | vessel A frames identical alone, with B, and with B listed first |
| Determinism | same request gives identical series and resolved hash |
| Time step | position error vs dt 0.05 s after a 400 s turn: 16.3 ft at dt 0.5 s, 5.5 ft at dt 0.2 s (of ~3000 ft), first-order convergence |
| Presets | all four arrive within their durations |
| API | POST simulate -> job succeeded -> series -> summaries; 422 for own_thrust with tug commands, unknown tug/class, missing speed basis, duplicate vessel ids |

Added with the review fixes (`test_s6_fixes.py`): arrival in current (table in section 3), crab, Nomoto K versus simulated step, stability indices, the 60 deg course-change table, tug stale commands, thruster/tug allocation,
helm release, frozen arrived vessels, exact sampling, frame-0 wind force, calm air drag, corner cross-track, degenerate routes (422), twin rudders, Cb rule, route-free prediction, and the preset coastline check.

Runtime (CPython 3.12, one thread, Apple silicon laptop, dt 0.2 s): 0.32 s wall per simulated vessel-hour with default 2 s frames (0.28 s with 60 s frames); 4 vessels 1.25 s for 3600 s
(0.31 s per vessel-hour); with wind, current and auto assist 0.49 s per vessel-hour.

## 9. Known limits and findings
* **Thrust calibration (see the prominent note at the top):** T_max from friction-only resistance is likely 2 to 4 times low; acceleration, stopping and astern authority are too sluggish.
* Turning circles after the twin-rudder and Cb changes are 3.9 to 5.9 L at 35 deg from full speed (table in section 8). They are still produced by the Clarke/DNV/Fujii chain with assumed race and interaction
  coefficients, not identified from any ship; no data in the repository can confirm them. Nothing else was adjusted. The DDG-51 and CG-47 Cb values changed because the catalog Cb was inconsistent with displacement
  (section 2.3); the catalog draft may include the sonar dome and the catalog cannot say.
* The linear Clarke stability index of the bare LHD-1 and CVN-68 hulls is negative (course-unstable); the rudder stabilises them in the linear model only through assumed coefficients (section 2.3).
* No wave-making resistance. Twin rudders are modeled as one equivalent rudder pair with a shared yaw arm; no differential thrust between shafts, no propeller side force.
* Autopilot: gains come from the vessel's own linearised model but design parameters (wn = 2.5 U/L, zeta 0.9) are choices; the first-order reduction ignores the sway pole and the rudder rate limit; astern heading is rough.
  Cross-current stops need the ship to face the current (section 3). Arrival tolerates repeated missed approaches rather than guaranteeing arrival.
* The autopilot hands off to tugs on surge speed through the water only. Arrived vessels are frozen (no drift in current after arrival); berthing simulation is expected to take over.
