"""Mock telemetry ingest (M13): validates records and keeps the latest per source in memory."""

from mooring.core.schemas import TelemetryAccepted, TelemetryBatch, TelemetryRecord

LATEST: dict[str, TelemetryRecord] = {}


def _check(r: TelemetryRecord) -> str | None:
    if r.source == "ship_nmea" and not (r.sentence and r.sentence.startswith(("$", "!"))):
        return "ship_nmea records need an NMEA sentence starting with '$' or '!'"
    if r.source == "load_cell" and (r.line_number is None or r.tension_lbf is None):
        return "load_cell records need line_number and tension_lbf"
    if r.source == "ais" and not r.mmsi:
        return "ais records need mmsi"
    return None


def ingest(batch: TelemetryBatch) -> TelemetryAccepted:
    errors = []
    for i, r in enumerate(batch.records):
        err = _check(r)
        if err:
            errors.append(f"record {i}: {err}")
            continue
        key = f"{r.source}:{r.line_number or r.mmsi or ''}"
        LATEST[key] = r
    return TelemetryAccepted(accepted=len(batch.records) - len(errors), rejected=len(errors), errors=errors)
