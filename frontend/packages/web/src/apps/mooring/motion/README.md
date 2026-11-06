# Motion workspace

Motion enters the maneuvering workspace directly. Its first catalog scenario is created paused; only Start or Space
sends `resume`. Reopening the tab reuses the paused session. A new scenario closes and releases the previous session.

The controller owns one simulation socket and at most one prediction request. The one-second prediction refresh calls
the session's backend dynamics. Helm drafts stay local until Apply; Preview sends them only to the prediction clone.
The display never integrates vessel motion or constructs trajectories. Expired predictions disappear, past samples are
excluded, and remaining time ticks are relative to the displayed simulation time. Backend echoes distinguish sent orders
from applied orders; actual actuator response remains separate. Legacy rm0 recording and planner sessions remain available.

Satellite tiles use Esri World Imagery and street tiles use OpenStreetMap, with visible attribution. Neither needs a
Mapbox token. Only visible tiles are requested using browser caching; failures retain the supplied schematic. Images are
context, not charts or hazard geometry. Class-specific deckhouses are cosmetic, not contact or loading geometry.

Flow texture uses active-frame wind/current direction and simulation time. Its display speed is illustrative, not a force
model. Animation starts disabled for `prefers-reduced-motion`; paused simulation freezes the texture. Sectional views use
backend loading, attitude, draft, payload and local depth fields. Unknown clearance is never zero.

The layout follows information grouping and separation in
[IMO MSC.191(79), §5.1](https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.191%2879%29.pdf)
and terminology/usability guidance in
[IMO MSC.1/Circ.1609](https://wwwcdn.imo.org/localresources/en/OurWork/Safety/Documents/IMO%20Documents%20related%20to/MSC.1-Circ.1609.pdf).
This is design guidance, not navigation-equipment certification. The operational view, immediate controls and collapsible
diagnostic area remain distinct; validity, synthetic provenance, simulation time and unknown hazard coverage stay visible.

Tile sources: [Esri service metadata](https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer),
[OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
