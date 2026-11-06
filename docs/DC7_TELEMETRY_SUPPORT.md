# DC7 telemetry support boundary

Supported NMEA 0183 sentence format is one checksummed sentence per record,
maximum 82 characters. The declared subset is MWV (apparent/true wind), HDT
(true heading), VTG (true course and speed over ground), GGA (position and fix
quality), and DPT (depth and transducer offset). Checksums, status/fix quality,
units, finite numbers and physical bounds are enforced. Event time and receipt
time remain distinct. State, history, sequence replay checks and ordering are
independent for each authenticated principal, vessel and sentence/sensor channel.

Load cells require a registered sensor, vessel and line binding, calibration
revision/validity window, lbf units and configured bounds. The HTTP endpoint is
protected by the additional `MOORING_TELEMETRY_KEY` when configured and batch size is
bounded. Source arbitration keeps an explicit scenario/manual input first and
never lets an observation silently displace a qualified forecast.

When API authentication is enabled, both HTTP and WebSocket ingest also require
`MOORING_TELEMETRY_VESSELS`, a JSON mapping from authenticated principal names to
explicit vessel ID lists, for example `{"bridge-a":["DDG-1"],"bridge-b":["CG-2"]}`.
The bearer key determines the principal; a record's claimed vessel ID does not
grant permission. Missing or malformed configuration rejects every record with
`AUTHORIZATION_UNAVAILABLE`. An unlisted principal/vessel or a missing vessel ID
is rejected with `VESSEL_NOT_AUTHORIZED`. Configuration errors never echo the
mapping. Load-cell sensor/line/calibration checks remain required after vessel
authorization. The extra shared telemetry key alone grants no vessel authority.

With API authentication unset, local-demo ingestion remains unverified and allows
an absent vessel ID in a separate demo channel; it is not a deployment security
boundary. Ingest retains at most 4,096 channels, 100 records per channel and 10,000
accepted sequence markers. New channels beyond capacity receive `CHANNEL_LIMIT`;
existing channels remain usable and their order history is not evicted. Rejected
records never reserve a sequence number or alter any accepted state. This state
is in memory and is reset on process restart; it is not a durable anti-replay log.

No AIS message type is supported yet. AIS input is rejected with
`AIS_UNSUPPORTED`; no position is guessed from an undecoded payload. HTTP and
WebSocket ingest enforce the same configured telemetry key. A live AIS
decoder requires the licensed/current IEC/NMEA payload definition and a named
set of message types. No proprietary load-cell wire payload is supported
without a vendor specification; the normalized authenticated JSON record is
the current boundary.
