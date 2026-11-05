# Human-supplied data requests

Public feeds cannot qualify the assets below. Do not infer, scrape, or invent
missing values. Synthetic seed records may support a labeled demonstration,
but they cannot make an operational result valid. Before committing supplied
material, confirm that its distribution, export-control, privacy, and licensing
terms permit repository use; otherwise store only an approved derived record
with provenance and keep the controlled source outside the repository.

Priority is the minimum set needed to qualify one named ship/loading condition
at one named berth with one identified tug fleet. Every delivery needs an owner,
revision or effective date, units, coordinate/datum definitions, and an approval
contact who can answer discrepancies.

## Berth and pier arrangement

| Needed | Preferred format | Blocked capability | Plausible holder |
| --- | --- | --- | --- |
| Pier-face origin, orientation, outline, stationing, and berth limits | Georeferenced CAD/GIS (`DXF`, `GeoJSON`, or `GPKG`) plus a signed PDF plan; WGS84 horizontal control identified | DC6 berth geometry, M4 line geometry, M8 map, M12 approach display | NAVFAC public works/geospatial office; installation port operations; waterfront facilities engineer |
| Every bollard, bitt, cleat, chock, camel, separator, and fender used by the berth, including coordinates/elevations and stable IDs | CAD/GIS point layer and schedule keyed by fitting ID; elevations relative to a named vertical datum | M4 equilibrium and rule checks; M7 line-plan search; M11 contact | NAVFAC facilities engineering; berth owner; port engineer |
| Horizontal and 45-degree fitting ratings, inspection condition, restrictions, and current inspection date | Approved fitting schedule or inspection export (`CSV`/`XLSX`) plus source document references | Valid fitting utilization and any GREEN mooring conclusion | NAVFAC structural engineer; waterfront inspection program; port engineer |
| Fender force-deflection and energy-absorption curves, rated reaction/energy, geometry, installation spacing, and condition | Manufacturer curve tables as `CSV` plus legally shareable data sheet and installation/inspection record | M4 nonlinear contact; M11 contact energy and reaction | Fender manufacturer; NAVFAC designer; facilities maintenance/inspection office |
| Berth depth profile and latest hydrographic survey, with survey date, sounding uncertainty, dredged limits, and horizontal/vertical datums | Point/grid data (`XYZ`, BAG, GeoTIFF, or `GPKG`) and survey report | DC6/DC3 datum alignment, under-keel clearance, depth-sensitive loads and dynamics | NAVFAC hydrographic survey office; harbor master; USACE district where applicable |

Photographs or satellite imagery alone do not establish fitting type, rating,
elevation, condition, or underwater depth. A vision-confirmed outline remains
limited unless the responsible human verifies each derived item against an
approved source.

## Ship class and loading condition

| Needed | Preferred format | Blocked capability | Plausible holder |
| --- | --- | --- | --- |
| Loading-specific displacement, forward/aft/mean draft, trim, freeboard, CG, and waterline geometry | Approved loading-condition export (`CSV`/`JSON`) with drawing/report revision and units | M3 exposed areas/depth ratio; M4 geometry; M11 mass properties; M12 UKC | Ship's stability officer; class design authority; NAVSEA program office; approved stability booklet custodian |
| Mooring bitts, chocks, fairleads, and padeyes: stable IDs, ship-frame coordinates/elevations, side, lead restrictions, SWL/yield rating, and maximum line size | Coordinate table (`CSV`/`JSON`) plus approved arrangement drawing; ship frame explicitly defined | M4 line geometry and ship-fitting utilization; M7 plan/sequence | Ship's force; NAVSEA design authority; shipbuilder; class maintenance planning activity |
| Approved tug push/pull locations and local hull limits by loading condition | Ship-frame coordinate/range table with maximum force and direction restrictions | M6 tug allocation; M11 tug-force application | NAVSEA structures/design authority; shipbuilder; port operations guidance owner |
| Wind/current projected areas and coefficients, including loading/configuration applicability | Machine-readable coefficient/area tables plus cited test/report edition and domain | Qualification of M3 loads beyond the present limited public estimates | NAVSEA hydrodynamics/aerodynamics authority; model-basin report custodian; shipbuilder |
| Surge/sway/yaw mass and inertia, added-mass terms, damping/drag coefficients, shallow-water corrections, maneuvering derivatives, and validity ranges | Versioned `JSON`/`CSV` parameter set plus equations, frame/sign convention, test report, and uncertainty | RM3/M11 motion model; M12 maneuvering simulation | NAVSEA/Carderock; shipbuilder; class design authority; approved trials/model-test custodian |
| Ship-specific wave response amplitude operators and mean/slow-drift coefficients by heading, frequency, loading, and water depth | Complex RAO tables and drift coefficients (`CSV`, netCDF, or documented hydrodynamic-tool export) with phase convention | RM2/RM4 qualified wave-induced motion and force | NAVSEA/Carderock; shipbuilder; hydrodynamic model-test or analysis custodian |

If controlled ship data cannot be shared, request an approved calculation
service or a sanitized parameter set with explicit permitted uses. Do not derive
restricted geometry or coefficients from an unapproved document.

## Mooring lines

| Needed | Preferred format | Blocked capability | Plausible holder |
| --- | --- | --- | --- |
| Exact product/construction, diameter or circumference, MBS, working limit/design factor, wet strength, and certification/inspection status | Inventory export keyed by line serial/product ID plus manufacturer certificate/data sheet | M2 qualification; M4 line/fitting utilization; M7 inventory constraints | Ship's boatswain/First Lieutenant; supply activity; rope manufacturer |
| Load-versus-elongation curves for new and relevant aged/wet conditions, test method, cycle history, and temperature/rate domain | Digitized monotonic curve (`CSV`: load or fraction MBS versus strain) plus test report/data sheet | M4 nonlinear line response; M11 line dynamics | Rope manufacturer; NAVSEA materials authority; qualified test laboratory |
| Installed paid-out length, parts/reeving, pretension, chock route, wet/dry state, and tending actions for the evolution | Timestamped line-plan/evolution export (`JSON`/`CSV`) using stable fitting IDs | Reproducible M4 analysis, tide tending, M7 sequence, telemetry comparison | Ship's mooring team; First Lieutenant; deck log/evolution plan custodian |

## Tug fleet

| Needed | Preferred format | Blocked capability | Plausible holder |
| --- | --- | --- | --- |
| Identified tug, propulsion type, certified ahead/astern/side bollard pull, certification date and test conditions | Fleet `CSV`/`JSON` plus current bollard-pull certificate | M6 holding/berthing allocation and any fleet-feasibility claim | Tug operator; port operations; classification society/certifying surveyor |
| Direction-dependent force envelope, minimum controllable force, response lag/slew limits, speed dependence, and environmental operating limits | Polar/performance tables and versioned dynamic parameters with source report | M6 directional allocation; RM5/M11 tug dynamics | Tug builder/operator engineering; propulsion vendor; trials report custodian |
| Permitted ship contact/pull points, fender geometry, line arrangement, stand-off, and local restrictions | Tug/ship interface table keyed to ship push-point IDs, with approved operating guidance | Safe force application and M11 contact geometry | Harbor pilot organization; tug master/operator; ship design authority |
| Availability, crew/status constraints, transit time, and dispatch rules | Authorized scheduling/API export or manually approved scenario input | Real berthing-window and resource plan | Port operations dispatcher; tug operator |

Published horsepower is not a substitute for certified bollard pull, and a
generic propulsion label is not a direction-dependent force envelope.

## Local measurements and telemetry

| Needed | Preferred format | Blocked capability | Plausible holder |
| --- | --- | --- | --- |
| Berth-applicable current profiles across the vessel draft, with bin elevations/depths, instrument heading/calibration, QC, tide/weather coverage and any validated station-to-berth transfer | Time-stamped depth-bin east/north velocities or speed/set in netCDF or documented CSV, with units, True North convention and uncertainty/source report | Qualification of point/bin/model-layer forcing used for M3/M4/F24; a selected bin is not evidence of a representative full-draft load input | Port/NAVFAC oceanography office; NOAA PORTS partner; ADCP owner; harbor pilot organization |
| Berth-side wave gauge records and instrument metadata (location, depth, sampling, calibration, QC, datum) covering representative swell, local chop, and traffic | Time series/spectra in netCDF or documented `CSV`, with QC flags and calibration records | DC4 berth transfer validation; RM2/RM4 wave qualification | NAVFAC/port oceanography office; NOAA/academic partner; installed sensor owner |
| Directional fetch/shoreline obstruction geometry validated for the berth | `GeoJSON`/`GPKG` shoreline and obstruction layers with source date | DC4 local-chop estimate | DC6 chart-data owner; NAVFAC GIS office |
| AIS access and retention authority for relevant passing ship/tug traffic, including vessel dimensions where licensed | Approved feed or bounded historical extract with terms and timestamps | DC4 wake investigation; DC7 tug-position ingest | USCG/authorized AIS provider; port operations |
| Sensor registry: device identity, sentence/payload types, calibration revision, units, sample rate, clock source, authentication method, and bounds | Versioned `YAML`/`JSON` registry with certificate/key references but no secrets | DC7 authenticated telemetry and source arbitration | Ship systems owner; port IT/OT security; sensor vendor |
| Load-cell calibration curves, installation mapping to line/fitting IDs, rated range, uncertainty, and synchronized event timestamps | Calibration `CSV`/certificate and versioned mapping | DC7 measured-versus-modeled line-load comparison | Load-cell/smart-bollard owner; calibration laboratory; ship/port engineer |

## Delivery and acceptance checklist

For each dataset, the responsible reviewer must record:

1. Asset/site identity and stable record IDs.
2. Source organization, document/data revision, effective date, and contact.
3. Units, coordinate frames, sign/direction conventions, horizontal datum,
   vertical datum, and time zone/clock basis where applicable.
4. Applicability limits, uncertainty or tolerance, inspection/calibration state,
   and known missing fields.
5. Distribution/licensing decision and approved storage location. Secrets and
   restricted source documents never enter this repository.
6. Cross-check results against the repository schema and the independent source
   record. Conflicts remain explicit blockers; they are not silently averaged.
7. Human approval naming the capabilities that the delivery qualifies. Data
   receipt alone does not automatically change a capability from limited to
   valid.

## Operational decision and procedure inputs

The modeling workstream also requires the following items to turn numerical checks into an accountable
crew procedure. These supplement the asset and sensor inventory above.

| Needed | Preferred format | Blocked capability | Plausible holder |
| --- | --- | --- | --- |
| Engine, rudder and thruster limits, response delays and verified low-speed trials | Versioned response curves and applicability envelope, with loading/depth and test provenance | Approach and abort simulation | Ship design authority / vessel operator |
| Wind averaging/gust durations, reference height, forecast issue/valid times, spatial/depth basis and station-to-berth comparison | Provider metadata plus local representativeness review | Load normalization and forecast acceptance | NOAA/provider metadata owner and local engineering reviewer |
| Approved line-handling procedure, crews/stations, equipment limits, snap-back zones, dependencies and reviewed timing | Versioned procedure/rule table keyed to line and fitting IDs | Operational line sequence and briefing | Deck officer / pilot / port operations |
| Abort/replan criteria, forecast expiry, observed deviations, traffic/tug contingencies, alternate berths and decision times | Reviewed decision table with accountable authority and applicability | Crew-use release and contingency planning | Commanding officer / pilot / harbor master |

Tug wash remains outside tonight's model. Missing wake or dynamics inputs mean unavailable/unqualified,
never zero. Synthetic training records cannot qualify an asset. Numeric or configuration changes invalidate
affected recommendations and require fresh independent review.

Current seed inventory limitation (5 November 2026): CG-47, LHD-1 and CVN-68 have hull/load inputs but no vessel fitting layouts. The template service refuses to construct their line plans. DDG-51-FIIA has a seed layout for limited demonstrations. Prioritize approved fitting coordinates and ratings for any additional class before promising mooring/sequence support; do not borrow the DDG layout.
