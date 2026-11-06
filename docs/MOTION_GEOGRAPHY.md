# Norfolk Motion geography — 6 November 2026

This fixes the Norfolk demonstration placement and map failures found during the independent visual review of
`1be7191`. It is confined to the Motion workspace and its backend scene/initial-state support. The same synthetic
dynamics and limited qualification remain. The PR records exact tests, browser evidence and deployed revision.

## Defects and acceptance

| Defect | Correction and acceptance |
| --- | --- |
| North-face approach placed CG-47 on Pier 14; all four classes inherited `y=900` | Author the starting pose within the existing Norfolk fixture and check full ship/tug footprints, both berth faces and supported sides. Keep the old pose as an invalid-input regression. |
| Missing berth outline became an unbounded gray `PIER` | Render the attributed, bounded NOAA polygons and open shoreline lines. Never close an open source line into an invented polygon or treat missing geometry as water. |
| Carrier opened with its 1,092-ft hull only about 13 pixels long | Start with a vessel view; provide separate ship, maneuver and route fits. Show the supplied route, physical scale and true north. Frame and forecast updates preserve the user's viewport. |
| Tug footprint changed with font/viewport size | Use supplied synthetic tug length and beam; keep icons with missing dimensions explicitly symbolic. Do not change the vessel's waterline beam to imitate its flight deck. |
| Channel imagery differed from backend coordinates by about 34 m | Convert geographic coordinates using the backend's declared WGS84 local-plane convention. Warp raster latitude in bounded strips; Norfolk control-point tests require less than 0.5 m image-to-model disagreement. |

## Geographic evidence and semantics

The existing fixture is `modeling/mooring/data_simulation/data/norfolk_piers_shoreline.geojson`. It contains selected
NOAA ENC Online `LNDARE`, `SLCONS` and `COALNE` features, clipped without simplification to the declared bounds
(-76.35, 36.95)–(-76.31, 36.98). Its response SHA256 is
`6f3de618caf2fe498115130d50f5a00e3117df7c2935fd271ba1dea78520cc1c`, retrieved on 6 November 2026.
Feature source dates vary; a recent retrieval is not a new survey. Source attribution, dates, coverage and limitations
travel with the scene. Pier 12's supplied shoreline construction is an open line, so it is rendered as a line.

The optional scene additions are `geographic_context` and `tug_dimensions`. Old scenes omit these fields as before.
Context geometry is in berth feet, with polygon holes retained and the same handed frame as the model. Missing
context remains unavailable. Recorded scene IDs include supplied context so a scene cannot silently acquire a different map.

Known-land initial-state rejection is a bounded input check. It does not establish a clear passage, navigable depth,
present-day pier layout, traffic clearance or successful runtime collision detection. The scene explicitly reports
`runtime_collision_checks: false`; the existing prediction hazard limitations remain. Unknown fixture coverage must
not become a green clearance result.
The ship envelope uses LOA and the catalog beam, including CVN's waterline beam; it does not establish clearance for
flight-deck overhang or other above-water projections.

Satellite imagery is an archived background. Photographed ships are not live traffic: the DDG/LHD alongside positions
can overlay vessels already present in the raster even when their model coordinates are on the water side of Pier 12.
Do not move a model merely to avoid those old pixels. The acquisition date is not asserted where unavailable.

## Projection and display limits

Motion uses the WGS84 origin-latitude meridional and prime-vertical scale from `mooring.transit.geo.LocalPlane`.
The UI performs no physics integration. Geographic points, route points, shoreline features and raster imagery use
the same mapping. Raster strips remove the previous single affine Mercator approximation across the channel.
The less-than-0.5 m check measures agreement with that local model at Norfolk demo scales, not accuracy against
surveyed/geodesic ground truth. The local model's existing range/curvature limitations still apply.

The 120 ms bounded display interpolation remains separate from geographic projection and physics. Static map geometry
is memoized; moving ship/tug geometry continues to interpolate received states. No map correction is allowed to
overwrite an authoritative vessel state or alter the clock.

## Ship views and demo presentation

The user also requested simultaneous forward, aft and side profiles alongside the map, with an independent collapse
control. These are vessel-class illustrations driven by backend draft, attitude, CG and supplied water/depth evidence;
they are not surveyed hull sections. Unsupported geometry or levels remain unavailable. Profile styling must not change
physical dimensions, compute new stability values or apply trim twice to already supplied forward/aft drafts.

Repeated background qualification banners move into expandable demo/source information. Active invalid-state,
collision, negative-clearance, stale/missing-data and truncated-forecast information must remain available where it
affects the displayed result. This changes presentation only; API validity, provenance and model qualification do not change.

## Remaining work

- Runtime coastline/structure collision and predicted hazard checks, plus complete bathymetry and traffic sources.
- Qualified vessel outlines distinguishing waterline/contact hull, above-water shape and carrier deck overhang.
- Legacy Setup Cesium geometry and its ECEF/ENU mapping; those views are outside this Motion-only UI change.
- Broader geographic coverage, imagery acquisition metadata and validation of arbitrary saved/custom routes.
- Operational qualification of dynamics, passage planning, loading and clearance. These demonstrations remain limited.

Acceptance must include all four stock presets in Plan/Satellite/Map, class/face/side starting-state checks, explicit
invalid ship/tug imports, the existing full-hull channel rollout regressions, and a real-browser animation check.
The final PR records executed checks and any limits; this document alone is not deployment evidence.
