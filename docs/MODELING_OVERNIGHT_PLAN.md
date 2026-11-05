# Overnight modeling execution and advance docking forecasts

Agent B, 4–5 November 2026. Extends team_agent_instructions/02-modeling-and-agents.md. Shared overnight ownership/integration rules apply; generated contracts define wire shapes. Target 08:00 EST: demonstrable integration, not operational qualification.

## UI coverage audit

| Existing UI | Backend/integration gap | Required work |
| --- | --- | --- |
| Planner target, SSE and apply/undo | No explicit intake supplied; completion is not feasibility | Four named outcome cases; intake/planner/safety chain; governing result references |
| Recommendations and tug rendering | Search omits assisted cases | Evaluate assistance, preserve actual assignments in final analyses |
| 24h risk timeline | Saved weather freezes a snapshot | Separate issued forecast from training scenario; preserve coverage and issue times |
| Sheet approval/print | Direct creation from plan | Independent review, immutable approval, prominent seed/limited labels |
| Berth map and fittings | Vision returns fixed mock berth | Metadata-driven draft, estimated capacities, confirmation registers selectable berth |
| Environment/replay/ramp | Missing/stale components can fail intake | Findings instead of invented zeros; complete offline path |
| Double-up and sequence | Final equilibrium does not validate handling | Intermediate state checks, draft/unreviewed durations |
| Envelope/exceedance charts | Unknown can look like zero | Preserve undetermined outcomes and unqualified probability provenance |
| Motion and 3D | Unqualified synthetic vessel response | Consume C-owned contracts; no operational fidelity claim |

## Execution

1. M0 baseline and contract freshness; ignore stale bytecode in source architecture check.
2. M1–M3 named limited/overload/invalid/undetermined examples; deterministic planning and independent safety; tug search and stop rules.
3. F24 publish additive forecast contract/fixtures early, then implement below.
4. M4 metadata-driven berth draft and confirmation, optional guarded extraction.
5. M5–M7 provider options, sequence/readiness fixes, data inventory and benchmarks.
6. M8 error/concurrency tests, clean-stack integration. Freeze features at 07:00 EST.

## F24 — docking planned at least 24 hours ahead

Planning time differs from arrival time. Acquire at least 48h where supported: 24h starting now cannot cover an operation beginning tomorrow plus docking/initial holding.

Inputs: scenario, explicit as-of UTC, candidate arrival interval, operation/holding duration, forecast or source, utilization target, bounded budget. Outputs: selected arrival and alternatives, governing element/time, evaluated conditions and immutable result IDs, coverage/issue metadata, line placements, tug assignments and draft sequence.

- Reject future-issued data relative to as-of; duplicates, unordered times, missing coverage and unsupported datums must not silently pass. Never extrapolate calm conditions over a gap.
- Use coincident snapshots, not artificial combinations of independent maxima. Evaluate interior gust/current/tide peaks and direction changes throughout docking/holding.
- Search lines against the full required conditions and tide range; check fittings/fenders and available tugs. Budget/cancellation are explicit; incomplete search is undetermined.
- Recheck on new forecast, missing/stale component, arrival or asset changes. Approval never automatically transfers to changed inputs.
- Tests: arrival ≥24h after as-of; coverage past day one; interior peak; circular direction; truncated/missing forecast; future-issue leakage; UTC/DST; offline determinism; cancellation; consumer validation.

## Public sources and simulation

C owns acquisition/normalization. [NWS API](https://www.weather.gov/documentation/services-web-api) /points resolves berth coordinates to grid endpoints; hourly forecasts cover seven days. Use numeric wind/gust with actual basis metadata. [CO-OPS API](https://api.tidesandcurrents.noaa.gov/api/prod/) provides tide/current predictions; preserve bin and MLLW datum. Tidal predictions omit weather-driven residuals. CBOFS is useful where coverage/datum are supported. Unknown averaging basis stays limited.

Temporary public pulls are opt-in and timestamped outside git; tests use small recorded fixtures and never network. New synthetic planning generators belong in modeling/mooring/data_simulation/, with explicit seed/UTC anchor, scenario provenance and reusable parameters for a future training UI. Coordinate with C; no silently fabricated forecasts.

## Modeling recommendations and operational blockers

Prioritize verified line/fitting/fender geometry and ratings; loading/draft/freeboard; depth/datum/clearance; available tugs; forecast freshness and spatial representativeness; safe handling sequence and abort/replan conditions. A fine wave mesh is unnecessary, but unmodeled swell/wake/contact remains explicit. UKC/navigation needs official bathymetry and validated squat, not seed depth. Qualified data and accountable pilot/deck-officer review are necessary before crew operational use. Add berth-applicable current-profile and station-transfer evidence to the data acquisition plan: station/bin or model-layer provenance alone does not establish a representative full-draft forcing input. No profile integration or transfer coefficient is invented tonight.

## Integration

Watch remote refs and peer inboxes every five minutes; log changes locally. Never auto-merge unchecked work. Merge dev at each completed item and every 60–90 minutes, regenerate contract, run Python/UI gates and merge green PRs. Publish interfaces and append peer requests without editing owned implementations.

User addition: maintain [MODELING_UI_RECOMMENDATIONS.md](MODELING_UI_RECOMMENDATIONS.md) as a living optional UI handoff, distinguishing implemented capabilities from proposals. Send coordination requests through both peer inboxes; monitor all active peer branches/inboxes and acknowledge dependencies at integration points.
