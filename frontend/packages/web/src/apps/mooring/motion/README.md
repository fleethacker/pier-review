# Motion workspace

Motion enters the maneuvering workspace directly. Its first catalog scenario is created paused; only Start or Space
sends `resume`. Reopening the tab reuses the paused session. A new scenario closes and releases the previous session.
Saved scenarios are available from the maneuver selector and builder. Loading saves an immutable copy. The optional
propulsion editor resolves a complete configuration from the backend without allocating a session; edited thrust limits,
rudder limits and actuator slew rates are explicitly synthetic, user-authored inputs.

The controller owns one simulation socket and at most one prediction request. Advancing authoritative frames refresh the
backend forecast at most once a second; an unchanged paused snapshot performs no repeated work. The latest explicit Preview
queues behind any active request and stays usable during background work. Requests time out after eight seconds; transient
errors remain visible alongside any still-current forecast. Commands, run/scene changes and expired horizons invalidate it.
Helm drafts stay local until Apply; Preview sends them only to the prediction clone. Applied orders wait for a backend echo
before forecasting. Orders queued while paused require Start/Resume. Actual actuator response remains separate.

The primary SVG plan, satellite and street-map views interpolate supplied geometry between received states with a 120 ms
presentation delay. They never extrapolate or integrate vessel motion. Clock, numerical readouts, force magnitudes, validity
and warnings use the newest authoritative state. Pause, disconnect, run/scene changes and invalid frames snap to that state;
stream gaps hold the last received position. Sectional and shared Cesium views retain authoritative frame pacing. The camera
holds its initial fit until the user chooses Fit maneuver or changes the run/scene; forecast refreshes do not move it.

Expired predictions disappear, past samples are excluded, and remaining time ticks are relative to authoritative simulation
time. Legacy rm0 recording and planner sessions remain available.

Satellite tiles use Esri World Imagery and street tiles use OpenStreetMap, with visible attribution. Neither needs a
Mapbox token. Only visible tiles are requested using browser caching; failures retain the supplied schematic. Images are
context, not charts or hazard geometry. Class-specific deckhouses are cosmetic, not contact or loading geometry.

Flow texture uses active-frame wind/current direction and simulation time. Its display speed is illustrative, not a force
model. Animation starts disabled for `prefers-reduced-motion`; paused simulation freezes the texture. Sectional views use
backend loading, attitude, draft, payload and local depth fields. Unknown clearance is never zero.

Live environment acquisition supplies a held snapshot for one run, with source, valid time and available acquisition age;
it is not a continuous feed. The synthetic route controller can remain active after reaching its holding point. Applying a
manual helm order disables both route following and holding; neither establishes hazard clearance.

The layout follows information grouping and separation in
[IMO MSC.191(79), §5.1](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.191%2879%29.pdf)
and terminology/usability guidance in
[IMO MSC.1/Circ.1609](https://wwwcdn.imo.org/localresources/en/OurWork/Safety/Documents/IMO%20Documents%20related%20to/MSC.1-Circ.1609.pdf).
This is design guidance, not navigation-equipment certification. The operational view, immediate controls and collapsible
diagnostic area remain distinct; validity, synthetic provenance, simulation time and unknown hazard coverage stay visible.

Tile sources: [Esri service metadata](https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer),
[OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
