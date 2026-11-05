# DC7 telemetry support boundary

Supported NMEA 0183 sentence format is one checksummed sentence per record,
maximum 82 characters. The declared subset is MWV (apparent/true wind), HDT
(true heading), VTG (true course and speed over ground), GGA (position and fix
quality), and DPT (depth and transducer offset). Checksums, status/fix quality,
units, finite numbers and physical bounds are enforced. Event time and receipt
time remain distinct; readings are independently ordered per sentence or
sensor channel.

Load cells require a registered sensor, vessel and line binding, calibration
revision/validity window, lbf units and configured bounds. The HTTP endpoint is
authenticated when `MOORING_TELEMETRY_KEY` is configured and batch size is
bounded. Source arbitration keeps an explicit scenario/manual input first and
never lets an observation silently displace a qualified forecast.

No AIS message type is supported yet. AIS input is rejected with
`AIS_UNSUPPORTED`; no position is guessed from an undecoded payload. HTTP and
WebSocket ingest enforce the same configured telemetry key. A live AIS
decoder requires the licensed/current IEC/NMEA payload definition and a named
set of message types. No proprietary load-cell wire payload is supported
without a vendor specification; the normalized authenticated JSON record is
the current boundary.
