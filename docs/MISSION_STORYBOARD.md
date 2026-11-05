# S5 Mission storyboarding

Rebuild a ship's path after a mission from its recorded fixes, and tie timestamped images and reports to positions on
that path. Code: `modeling/mooring/missions/` (parsers, exif, locate, geo, store, storyboard); routes:
`modeling/modeling_api/routers/missions.py`; contract: `modeling/mooring/core/schemas/missions.py`.

Principles: a position is never invented. Missing is `null`. Events are located only by time, with an explicit method,
and never extrapolated beyond the recorded fixes. Every timestamp on the wire is timezone-aware UTC.

## Track formats

Upload with `POST /missions/{id}/track/file` (multipart: `file`, `format`, optional `utc_offset_min`, `nmea_date`;
at most 20 MB) or JSON `POST /missions/{id}/track` (`{"fixes": [...]}`, at most 200 000 fixes per mission in total).
Units: degrees WGS84, knots, degrees true. Fixes merge with those already stored.

| Format | Accepted | Rejected (counted, first 50 reported with line/record numbers) |
|---|---|---|
| `csv` | Header row required (comment lines `#` and BOM tolerated; comma, semicolon or tab). Columns, case-insensitive: time = `time, timestamp, datetime, time_utc, t_utc, utc`; `lat, latitude`; `lon, lng, long, longitude`; optional `heading, hdg`; `cog, course`; `sog, sog_kt, speed_kt, speed_kn, knots` (knots; a bare `speed` column has no stated unit, is ignored and produces one warning in `errors`); `hdop`. Time is ISO-8601, compact ISO (`YYYYMMDD[T]HHMMSS` with `Z`/offset, or `utc_offset_min`), or epoch seconds (see below). | naive timestamp without `utc_offset_min`; unparseable numbers; lat/lon out of range; heading/COG outside 0..360; negative speed; epoch values that look like milliseconds; bare dates such as `20260105`; any time outside 1970..2100 (UTC) |
| `gpx` | `trkpt`, `rtept`, `wpt` with `<time>`; `<hdop>`, `<course>` (COG), `<speed>` (m/s, converted to kt) | points without `<time>`; input that is not UTF-8 (UTF-16/32 BOM or NUL bytes, or an XML declaration naming another encoding) is refused outright, as is any `<!DOCTYPE` or `<!ENTITY` anywhere in the text (case-insensitive, checked before XML parsing) |
| `nmea` | `RMC` (date, time, position, SOG, COG) and `GGA` (time, position, HDOP); other sentences ignored. Checksums are required (`*` + exactly two hex digits) and verified. An RMC and GGA with the same timestamp merge into one fix. A GGA takes its date from the latest RMC or from `nmea_date`; the date advances one day whenever the time of day (RMC or GGA) jumps back more than 12 h, so GGA-only files crossing midnight roll over. | bad or missing checksum; RMC status `V`; RMC mode other than `A`/`D` (`E` estimated, `S` simulator, `M` manual, `N` not valid; an absent mode field is accepted); GGA quality 0; hemisphere not `N`/`S` for latitude or `E`/`W` for longitude; seconds >= 60; GGA with no date; malformed fields; non-NMEA lines |
| `geojson` | `Point` with `time`/`timestamp`/`datetime` property (optional `sog`, `cog`, `heading`, `hdop`); `LineString`/`MultiLineString` with per-vertex `coordTimes` or `times` (or `coordinateProperties.times`). Image/report markers from this service's own export are skipped, so an export re-imports. | Points without time; vertex/time count mismatch (each vertex counts as rejected) |
| `json` | `TrackFix` objects; naive `t_utc` is a schema error (422) | |

Epoch seconds are accepted only (a) as a JSON number (GeoJSON), (b) in an explicitly named numeric column (CSV header
`epoch`, `epoch_s`, `unix`, `unix_time`, `time_s`), or (c) as a plain 10-digit string (optional fraction) within
2000..2100. Digit-only strings of other lengths are never epoch seconds: 14 digits are compact ISO (`20260105120000`,
needs `utc_offset_min`), 8 digits (a bare date) and 13 digits (milliseconds) are rejected. All times (fixes, reports,
supplied `captured_utc`) must fall within years 1970..2100 UTC; outside that range a file record is rejected and a JSON
`/track`, `/reports` or `/media` request is a 422.

Naive timestamps: rejected unless `utc_offset_min` (minutes east of UTC) is given; a zone in the data always wins.
Quality is derived from HDOP when present (`good` <= 2.0, `degraded` above) and is `unknown` otherwise; `source` is the format name.

Merge rules (result counters): sorted by time on storage; a timestamp already stored (or earlier in the same upload)
is a `duplicate` and the first one is kept; `reordered` counts fixes earlier than the one received just before them;
`rejected` counts bad records. `accepted + duplicates + rejected` equals the records seen. A file with no valid fix is
a 422 with the errors in `detail`. The 200 000 fix cap rolls the whole upload back (409); for files, parsing stops
(409) as soon as the file holds more than 200 000 distinct timestamps. Parsing and storing run in a worker thread, off
the event loop. GeoJSON nested deeper than 64 levels is a 422.

## Images

`POST /missions/{id}/media` (multipart `image`, optional `metadata` JSON = `MediaMetadata`). JPEG, PNG or WebP, at most
8 MB, identified by magic bytes (never filename), verified decodable. 413 too large, 415 not an accepted type, 422
empty or corrupt. Bytes are stored untouched (EXIF is not stripped). At most 300 images per mission (409).

Capture time rules, in order:

1. `metadata.captured_utc` wins: `time_source: "supplied"`.
2. Else EXIF `DateTimeOriginal` (+ `SubSecTimeOriginal`) with EXIF `OffsetTimeOriginal`; else, if the EXIF time is naive,
   with `metadata.exif_utc_offset_min`. `time_source: "exif"`. The supplied-offset case is flagged on the located event
   (`EXIF_UTC_OFFSET_ASSUMED`).
   The generic `DateTime` tag (306) is the file modification time, never a capture time: if it is the only date,
   `captured_utc` is null and `time_note` says so.
3. Naive EXIF time and no offset: `captured_utc` is null and `time_note` says why. The zone is never guessed.
4. `camera_clock_offset_s` (seconds to add to the camera time; slow camera = positive) is added to EXIF-derived times
   (flag `CAMERA_CLOCK_OFFSET_APPLIED`). It describes the camera, so combining it with `captured_utc` is a 422.

EXIF GPS latitude/longitude with N/S/E/W references become `exif_lat`/`exif_lon` (out-of-range values and 0,0 are
ignored with a note in `time_note`).

## Locating an event at time t

One function (`mooring.missions.locate.locate`) serves images and reports. Earth is a sphere of radius 6 371 008.8 m
(IUGG mean); distances are great-circle (haversine), nautical mile = 1852 m.

| `method` | When | Position |
|---|---|---|
| `exact_fix` | within 0.5 s of a fix inside the recorded span, or within 1 ms of the first/last fix | that fix |
| `interpolated` | between fixes spaced <= `max_interp_gap_s` (default 300) | great-circle interpolation, linear in time (antimeridian and pole safe); `sog_kt` = distance/time; heading = circular interpolation of recorded headings if both fixes have one, else segment bearing (null if the fixes are < 1 m apart) |
| `gap` | between fixes spaced further apart | null; `gap_s` reported |
| `before_track` / `after_track` | outside the recorded span (more than 1 ms before the first fix or after the last; no 0.5 s snapping at the ends) | null, never extrapolated |
| `no_track` / `no_time` | no fixes / event without a timestamp | null |

`distance_along_track_nm` is the cumulative great-circle length of the recorded fixes up to the position (null when not
established). If the event states a position (EXIF GPS or the report's lat/lon) it is returned as `stated_*`, and
`discrepancy_m` (great-circle) when the track position exists.

Validity: `valid` only for an `exact_fix` of `good` quality with no other caveat. Otherwise `limited`, with reasons:
`INTERPOLATED_POSITION` (plus `FIX_QUALITY_NOT_GOOD` when either bracketing fix is not `good`), `POSITION_NOT_ESTABLISHED` (gap, outside, no track, no time), `FIX_QUALITY_NOT_GOOD`,
`STATED_POSITION_DISAGREES` (> 500 m), `EXIF_UTC_OFFSET_ASSUMED`, `CAMERA_CLOCK_OFFSET_APPLIED`. The storyboard
aggregates reasons across events (with the event ids) and adds `TRACK_GAPS_OVER_LIMIT` / `NO_TRACK`.

## Storyboard and exports

- `GET /missions/{id}/storyboard?max_interp_gap_s=300&max_points=2000`: stats, decimated track, events in time order
  (events without a time last), aggregated validity.
- Decimation is Douglas-Peucker in a local equirectangular plane, run best-first so the result has at most
  `max_points` points: first/last always kept, gap endpoints kept (longest gaps first) while the budget allows.
  `GET /missions/{id}/track?max_points=5000` reports `decimated`.
- `GET /missions/{id}/storyboard.geojson`: FeatureCollection. Track as `LineString`s (one per stretch between gaps over
  the limit; property `times`, full resolution); a lone fix between gaps is a `Point` of kind `track_point`. Located
  events are `Point`s with `kind, id, t_utc, method, title, media_url, validity`. Unlocated events are only in the
  top-level `properties.unlocated_events`. Positions and times round-trip through the GeoJSON importer; speed,
  heading, HDOP and quality are not exported.

## Storage and limits

SQLite (the process database, `MOORING_DB`): missions are `docs` rows with ownership claimed on create; fixes are
rows keyed `(mission_id, t_us)` in `mission_fixes`; images are BLOBs in `mission_media`; reports are JSON rows in
`mission_reports`. Tables are created on first use. Limits: 200 000 fixes, 300 images of 8 MB, 5 000 reports per
mission; track file 20 MB. Missing or not-owned missions, images and reports answer 404.

The global request-body limit (`MOORING_MAX_BODY_BYTES`, default 1 MiB) is enforced by the API middleware before these
routes run. Raise it (about 21 MB for 20 MB tracks, 9 MB for images) wherever S5 uploads are used.

## API flow

```bash
H='Authorization: Bearer <key>'; B=http://localhost:8000/api/v1
MID=$(curl -s -H "$H" -H 'content-type: application/json' $B/missions \
  -d '{"name":"Harbor transit","vessel_id":"DDG-51"}' | jq -r .mission_id)
curl -s -H "$H" $B/missions/$MID/track/file -F format=csv -F file=@track.csv -F utc_offset_min=0
curl -s -H "$H" $B/missions/$MID/track/file -F format=nmea -F nmea_date=2025-06-01 -F file=@gps.nmea
curl -s -H "$H" $B/missions/$MID/media -F image=@bridge.jpg \
  -F 'metadata={"exif_utc_offset_min":-240,"camera_clock_offset_s":90,"caption":"bridge wing"}'
curl -s -H "$H" -H 'content-type: application/json' $B/missions/$MID/reports \
  -d '{"t_utc":"2025-06-01T12:02:00Z","title":"Pilot aboard","lat":36.95,"lon":-76.3}'
curl -s -H "$H" "$B/missions/$MID/storyboard?max_interp_gap_s=120&max_points=1000" | jq .stats
curl -s -H "$H" "$B/missions/$MID/storyboard.geojson" > storyboard.geojson
```
